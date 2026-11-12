"""perf.py: interleaved timing of three cvbench servers (shipped base, candidate, optimized upstream build).

Every server is a separate process running `cvbench serve`. For each timed case the driver prepares the same
inputs in all three, picks an iteration count from the base build, then runs R rounds; in every round each
server runs the same batch (same nonce, so the same input sequence) in a fresh random order. Wall time of a
batch is measured here, outside the timed process, from the command to its reply. Per round the driver forms
the ratios base/candidate and base/upstream; a case's speedup is the median over rounds. The candidate's
sampled outputs are compared with the base's every round, and its full outputs once per case.

Standalone: `python3 -I perf.py --base B --cand C [--up U]` times the given builds against each other.
"""
import json
import math
import os
import random
import select
import signal
import statistics
import struct
import subprocess
import sys
import time


class ServerError(Exception):
    pass


class Server:
    def __init__(self, name, binary, workdir, uid=None, cpu=None):
        self.name = name
        self.workdir = workdir
        self.uid = uid
        self.buf = b""

        def pre():
            os.setsid()
            if cpu is not None:
                try:
                    os.sched_setaffinity(0, {cpu})
                except OSError:
                    pass
            if uid is not None:
                os.setgid(uid)
                os.setuid(uid)

        env = {"PATH": "/usr/bin:/bin", "OPENCV_FOR_THREADS_NUM": "1", "OMP_NUM_THREADS": "1", "HOME": workdir}
        self.p = subprocess.Popen([binary, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, cwd=workdir, env=env, preexec_fn=pre, bufsize=0)

    def _readline(self, deadline):
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ServerError(f"{self.name}: timeout")
            r, _, _ = select.select([self.p.stdout], [], [], left)
            if not r:
                continue
            chunk = os.read(self.p.stdout.fileno(), 65536)
            if not chunk:
                raise ServerError(f"{self.name}: exited (code {self.p.poll()})")
            self.buf += chunk
            if len(self.buf) > 1 << 20:
                raise ServerError(f"{self.name}: flooded stdout")
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("latin-1")

    def cmd(self, text, expect, timeout):
        """Send one command; return (seconds from send to the expected reply, reply line)."""
        data = (text + "\n").encode()
        t0 = time.perf_counter_ns()
        try:
            os.write(self.p.stdin.fileno(), data)
        except OSError as e:
            raise ServerError(f"{self.name}: write failed ({e})")
        deadline = time.monotonic() + timeout
        while True:
            line = self._readline(deadline)
            if line == expect:
                return (time.perf_counter_ns() - t0) / 1e9, line
            # anything else on stdout is ignored (library chatter); the expected token carries the nonce

    def threads(self):
        """(threads in the process, number of child processes) or None if it is gone."""
        try:
            th = 0
            with open(f"/proc/{self.p.pid}/status") as f:
                for ln in f:
                    if ln.startswith("Threads:"):
                        th = int(ln.split()[1])
            kids = 0
            for t in os.listdir(f"/proc/{self.p.pid}/task"):
                try:
                    with open(f"/proc/{self.p.pid}/task/{t}/children") as f:
                        kids += len(f.read().split())
                except OSError:
                    pass
            return th, kids
        except OSError:
            return None

    def close(self):
        try:
            os.write(self.p.stdin.fileno(), b"Q\n")
        except OSError:
            pass
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self.p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def foreign_maps(server, own_binary):
    """Files mapped by a server other than its own (static) binary; pseudo mappings are ignored."""
    own = os.path.realpath(own_binary)
    bad = set()
    try:
        with open(f"/proc/{server.p.pid}/maps") as f:
            for ln in f:
                parts = ln.split(None, 5)
                if len(parts) < 6:
                    continue
                path = parts[5].strip()
                if not path.startswith("/"):
                    continue
                path = path.replace(" (deleted)", "")
                if os.path.realpath(path) != own:
                    bad.add(path)
    except OSError:
        pass
    return sorted(bad)


def read_records(path):
    """Records of a cvbench dump: list of (id, depth, ta, tr, tn, values tuple)."""
    out = []
    with open(path, "rb") as f:
        b = f.read()
    i = 0
    while i < len(b):
        magic, idlen = struct.unpack_from("<II", b, i)
        if magic != 0x52425643 or idlen > 4096:
            raise ValueError("malformed dump")
        i += 8
        rid = b[i:i + idlen].decode("latin-1")
        i += idlen
        depth, n, ta, tr, tn = struct.unpack_from("<IQddd", b, i)
        i += 4 + 8 + 24
        if n > (1 << 28) or i + 8 * n > len(b):
            raise ValueError("malformed dump")
        vals = struct.unpack_from(f"<{n}d", b, i)
        i += 8 * n
        out.append((rid, depth, ta, tr, tn, vals))
    return out


def values_match(ref, got, ta, tr, tn):
    """Same rule as `cvbench cmp`, for the small sample records."""
    if len(ref) != len(got):
        return False
    finite = [abs(x) for x in ref if math.isfinite(x)]
    M = max(finite) if finite else 0.0
    for x, y in zip(ref, got):
        if math.isnan(x) or math.isnan(y):
            if not (math.isnan(x) and math.isnan(y)):
                return False
            continue
        if x == y:
            continue
        if math.isinf(x) or math.isinf(y):
            return False
        ad = abs(x - y)
        if ad > ta and ad > tr * max(abs(x), abs(y)) and ad > tn * M:
            return False
    return True


def list_cases(binary):
    out = subprocess.run([binary, "list"], capture_output=True, text=True, timeout=60, check=True).stdout
    cases = []
    for ln in out.splitlines():
        p = ln.split()
        cases.append({"idx": int(p[0]), "id": p[1], "family": p[2], "rows": int(p[3]), "cols": int(p[4])})
    return cases


def measure(servers, cases, reps, target_s, rng, cmp_tool, workdirs, log=None, case_filter=None,
            batch_timeout=60.0, ref="base", cand="cand"):
    """Time every case. servers: dict name -> Server (must contain `ref`). Returns per-case results.

    Result per case: {"id", "family", "iters", "t": {name: [seconds per batch per round]},
                      "ratio": {name: median over rounds of t_ref/t_name}, "ok": bool, "why": str,
                      "threads": max thread count seen in the candidate}.
    """
    results = []
    names = list(servers)
    for c in cases:
        if case_filter and c["id"] not in case_filter:
            continue
        res = {"id": c["id"], "family": c["family"], "iters": 0, "t": {n: [] for n in names}, "ratio": {},
               "ok": True, "why": "", "threads": 1}
        try:
            seed = rng.getrandbits(63)
            for n in names:
                servers[n].cmd(f"P {c['idx']} {seed}", f"OK P {c['idx']}", 120)
            # warm-up and iteration count from the reference build
            for n in names:
                nonce = rng.getrandbits(63)
                servers[n].cmd(f"T 1 {nonce}", f"D {nonce}", batch_timeout)
            one = []
            for _ in range(3):
                nonce = rng.getrandbits(63)
                one.append(servers[ref].cmd(f"T 1 {nonce}", f"D {nonce}", batch_timeout)[0])
            iters = int(max(1, min(5000, round(target_s / max(statistics.median(one), 1e-7)))))
            res["iters"] = iters
            for rnd in range(reps + 1):        # round 0 is a full-size warm-up, not recorded
                nonce = rng.getrandbits(63)
                order = names[:]
                rng.shuffle(order)
                for n in order:
                    dt, _ = servers[n].cmd(f"T {iters} {nonce}", f"D {nonce}", batch_timeout)
                    if rnd:
                        res["t"][n].append(dt)
                if cand in servers:
                    th = servers[cand].threads()
                    if th is None:
                        raise ServerError(f"{cand}: process vanished")
                    res["threads"] = max(res["threads"], th[0])
                    if th[0] > 1 or th[1] > 0:
                        res["ok"] = False
                        res["why"] = f"extra threads or processes in the timed process ({th[0]} threads, {th[1]} children)"
                # compare the candidate's sampled outputs (every round) and full outputs (last round)
                if cand in servers and rnd:
                    full = rnd == reps
                    paths = {}
                    for n in (ref, cand):
                        paths[n] = os.path.join(workdirs[n], f"s_{c['idx']}_{rnd}.bin")
                        if os.path.exists(paths[n]):
                            os.unlink(paths[n])
                        servers[n].cmd(f"S {paths[n]}" + ("" if full else " samples"), "OK S", 120)
                    ra, rb = read_records(paths[ref]), read_records(paths[cand])
                    if not ra or not rb or ra[0][0] != rb[0][0] or not values_match(ra[0][5], rb[0][5], *ra[0][2:5]):
                        res["ok"] = False
                        res["why"] = res["why"] or f"sampled outputs differ from the shipped build (round {rnd})"
                    if full:
                        out = subprocess.run([cmp_tool, "cmp", paths[ref], paths[cand]], capture_output=True,
                                             text=True, timeout=300).stdout.splitlines()
                        tot = [ln for ln in out if ln.startswith("TOTAL ")]
                        if not tot or tot[0].split()[2] != "0":
                            res["ok"] = False
                            bad = [ln.split()[0] for ln in out if len(ln.split()) == 5 and ln.split()[1] == "0"]
                            res["why"] = res["why"] or "outputs differ from the shipped build: " + " ".join(bad[:4])
                    for pth in paths.values():
                        try:
                            os.unlink(pth)
                        except OSError:
                            pass
            for n in names:
                if n == ref:
                    continue
                rs = [a / b for a, b in zip(res["t"][ref], res["t"][n]) if b > 0]
                res["ratio"][n] = statistics.median(rs) if rs else 0.0
        except ServerError as e:
            res["ok"] = False
            res["why"] = str(e)
        results.append(res)
        if log:
            log(res)
        if not res["ok"] and cand in servers and ("exited" in res["why"] or "timeout" in res["why"]
                                                  or "vanished" in res["why"]):
            break   # the candidate server is gone; the caller fails the gate
    return results


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--cand")
    ap.add_argument("--up")
    ap.add_argument("--reps", type=int, default=15)
    ap.add_argument("--target", type=float, default=0.04)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--cpu", type=int, default=None)
    ap.add_argument("--only", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rng = random.Random(a.seed if a.seed is not None else int.from_bytes(os.urandom(8), "little"))
    wd = os.path.abspath("perf-work")
    os.makedirs(wd, exist_ok=True)
    servers, workdirs = {}, {}
    for n, b in (("base", a.base), ("cand", a.cand), ("up", a.up)):
        if b:
            workdirs[n] = wd
            servers[n] = Server(n, os.path.abspath(b), wd, cpu=a.cpu)
    cases = list_cases(os.path.abspath(a.base))
    only = set(x for x in a.only.split(",") if x)

    def log(r):
        rs = " ".join(f"{k}={v:.3f}" for k, v in r["ratio"].items())
        spread = ""
        for k in r["ratio"]:
            q = sorted(x / y for x, y in zip(r["t"]["base"], r["t"][k]))
            if q:
                spread += f" {k}[{q[0]:.3f}..{q[-1]:.3f}]"
        print(f"{r['id']:24s} {r['family']:10s} it={r['iters']:5d} tb={statistics.median(r['t']['base']) * 1e3:7.2f}ms "
              f"{rs}{spread} {'' if r['ok'] else 'FAIL ' + r['why']}", flush=True)

    t0 = time.time()
    res = measure(servers, cases, a.reps, a.target, rng, os.path.abspath(a.base), workdirs, log=log, case_filter=only)
    for s in servers.values():
        s.close()
    print(f"total {time.time() - t0:.0f}s", flush=True)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(res, f)


if __name__ == "__main__":
    main()
