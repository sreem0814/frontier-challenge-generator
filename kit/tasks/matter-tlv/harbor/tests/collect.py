"""tests/collect.py: evidence only. Rebuilds libchipcore from the pristine tree plus the component files from
/app, runs the hidden cases through case_runner, writes evidence.json.

Every path writes evidence.json. The build and the cases run as an unprivileged uid in their own process groups
with time limits; the expected transcripts stay readable by root only. case_runner forks one process per case
and frames each transcript; the transcript is hashed here (SHA-256) and compared with the frozen hash of the
reference transcript. compute_reward.py turns the evidence into the reward.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app")
ap.add_argument("--base", default="/usr/src/chip-base")
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--tamper", default="", help="file with dpkg --verify findings for the verifier's packages")
ap.add_argument("--sweep", default="{}", help="JSON line from sweep.py: session leftovers that were stopped")
args = ap.parse_args()

DATA = os.path.join(HERE, "data")
WEIGHTS = {"tlv_write": 0.14, "tlv_read": 0.16, "tlv_tools": 0.18, "msg_header": 0.10, "json_tlv": 0.18,
           "onboarding": 0.24}
# The component directories. Files taken from /app: the listed implementation and header files, and any new
# source file (not present in the starting tree) placed directly in one of these directories.
COMPONENTS = {
    "src/lib/core": re.compile(r"^TLV\w*\.(cpp|h)$"),
    "src/transport/raw": re.compile(r"^MessageHeader\.(cpp|h)$"),
    "src/setup_payload": re.compile(r"^\w+\.(cpp|h)$"),
    "src/lib/support/jsontlv": re.compile(r"^\w+\.(cpp|h)$"),
}
NEW_FILE = re.compile(r"^[\w.-]+\.(cpp|cc|h|hpp|inc|ipp)$")
MAX_FILE, MAX_TOTAL = 4 << 20, 32 << 20

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
    "base_ok": None, "base_mismatch": [], "overlay": [], "skipped": [], "tamper": [],
    "build_seconds": 0.0, "run_seconds": 0.0, "build_log_tail": "", "cases_crashed": 0,
    "expected_sealed": None, "leftovers_stopped": [], "wall_s": 0.0,
}
t0 = time.time()


def write():
    ev["wall_s"] = round(time.time() - t0, 1)
    with open(args.out, "w") as f:
        json.dump(ev, f, indent=1)


def gate(reason, cheat=False):
    ev["gate_reason"] = reason
    if cheat:
        ev["cheat_detected"] = True
    write()
    sys.exit(0)


def drop_privileges():
    os.setsid()
    os.setgroups([])
    os.setgid(args.uid)
    os.setuid(args.uid)


def as_candidate(cmd, timeout, env, cwd, out=subprocess.PIPE):
    p = subprocess.Popen(cmd, preexec_fn=drop_privileges, stdout=out, stderr=subprocess.STDOUT, env=env, cwd=cwd)
    try:
        o, _ = p.communicate(timeout=timeout)
        return p.returncode, o or b""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        o, _ = p.communicate()
        return None, (o or b"") + b"\n[timeout]"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_regular(path, limit=MAX_FILE):
    """Read a regular file without following symlinks or blocking on special files."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        chunks = []
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def parse_frames(data):
    """case_runner output: 'C <id> <bucket> <n>\\n<n bytes>' or 'X <id> <bucket> <reason>'."""
    res, pos, n = {}, 0, len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split(b" ")
        pos = nl + 1
        if len(head) == 4 and head[0] == b"C" and head[3].isdigit():
            ln = int(head[3])
            res.setdefault(head[1].decode("ascii", "replace"), ("C", hashlib.sha256(data[pos:pos + ln]).hexdigest(), ln))
            pos += ln
        elif len(head) >= 3 and head[0] == b"X":
            res.setdefault(head[1].decode("ascii", "replace"), ("X", "", 0))
        else:
            break  # unframed output: everything after it counts as missing
    return res


def split_cases(path):
    blocks, cur = [], []
    with open(path) as f:
        for line in f:
            cur.append(line)
            if line == "END\n":
                blocks.append("".join(cur))
                cur = []
    return blocks


try:
    try:
        ev["leftovers_stopped"] = json.loads(args.sweep).get("stopped", [])
    except ValueError:
        ev["leftovers_stopped"] = []

    # 1. the verifier's own tools must be the packaged ones; no preloaded libraries
    if args.tamper and os.path.isfile(args.tamper):
        with open(args.tamper) as f:
            ev["tamper"] = [ln.strip() for ln in f if ln.strip()][:10]
    if os.path.lexists("/etc/ld.so.preload"):
        ev["tamper"].append("/etc/ld.so.preload exists")
    if ev["tamper"]:
        gate("system files used by the verifier were modified: " + "; ".join(ev["tamper"][:3]), cheat=True)

    # 2. the pristine tree in the image must match the shipped manifest
    manifest = {}
    with open(os.path.join(DATA, "base.manifest")) as f:
        for ln in f:
            h, rel = ln.rstrip("\n").split("  ", 1)
            manifest[rel] = h
    seen, bad = set(), []
    for root, dirs, files in os.walk(args.base):
        for n in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, args.base)
            seen.add(rel)
            if rel not in manifest:
                bad.append("added " + rel)
            elif os.path.islink(p) or not os.path.isfile(p) or sha256_file(p) != manifest[rel]:
                bad.append("changed " + rel)
    bad += ["missing " + rel for rel in manifest if rel not in seen]
    ev["base_mismatch"] = bad[:20]
    ev["base_ok"] = not bad
    if bad:
        gate(f"the pristine tree {args.base} was modified ({len(bad)} files, e.g. {bad[0]})", cheat=True)

    # 3. work tree: pristine copy plus the component files from /app
    work = tempfile.mkdtemp(prefix="grade-")
    os.chmod(work, 0o755)
    src = os.path.join(work, "src")
    shutil.copytree(args.base, src, symlinks=True)
    total = 0
    for comp, pattern in COMPONENTS.items():
        d = os.path.join(args.app, comp)
        if not os.path.isdir(d) or os.path.islink(d):
            continue
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            base_has = os.path.lexists(os.path.join(args.base, comp, n))
            if not (pattern.match(n) if base_has else NEW_FILE.match(n)):
                continue
            rel = f"{comp}/{n}"
            try:
                content = read_regular(p)
            except OSError:
                content = None
            if content is None or total + len(content) > MAX_TOTAL:
                ev["skipped"].append(rel)
                continue
            total += len(content)
            dst = os.path.join(src, comp, n)
            if os.path.lexists(dst):
                os.unlink(dst)
            with open(dst, "wb") as f:
                f.write(content)
            ev["overlay"].append(rel)
    hdir = os.path.join(work, "harness")
    os.mkdir(hdir)
    for n in ("case_runner.cpp", "CMakeLists.txt"):
        shutil.copy(os.path.join(HERE, "harness", n), os.path.join(hdir, n))
    for root, dirs, files in os.walk(work):
        os.chown(root, args.uid, args.uid)
        for n in files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chown(p, args.uid, args.uid)
    home = os.path.join(work, "home")
    os.mkdir(home)
    os.chown(home, args.uid, args.uid)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8"}

    # 4. build gate: configure and build libchipcore and case_runner as the candidate uid
    b0 = time.time()
    bdir = os.path.join(work, "build")
    rc, log = as_candidate(["cmake", "-S", hdir, "-B", bdir, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                            f"-DTREE={src}"], 600, env, work)
    if rc == 0:
        rc, log2 = as_candidate(["ninja", "-C", bdir, f"-j{args.jobs}", "case_runner"], 1800, env, work)
        log += log2
    ev["build_seconds"] = round(time.time() - b0, 1)
    ev["build_log_tail"] = log[-3000:].decode("utf-8", "replace")
    runner = os.path.join(bdir, "case_runner")
    if rc != 0 or not os.path.isfile(runner):
        errs = [ln for ln in log.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
        gate("library or case_runner build failed" + (": " + errs[0][:300] if errs else ""))
    ev["build_ok"] = True

    # 5. sealing evidence: the candidate uid must not be able to read the expected results
    probe = subprocess.run(["setpriv", f"--reuid={args.uid}", f"--regid={args.uid}", "--clear-groups",
                            "test", "-r", os.path.join(DATA, "expected.json")])
    ev["expected_sealed"] = probe.returncode != 0

    # 6. run every hidden case (fixed denominator: a crash, timeout or missing transcript fails the case)
    r0 = time.time()
    blocks = split_cases(os.path.join(DATA, "cases.txt"))
    jobs = max(1, args.jobs)
    cdir = os.path.join(work, "cases")
    os.mkdir(cdir)
    os.chmod(cdir, 0o755)
    paths = []
    for k in range(jobs):
        p = os.path.join(cdir, f"shard{k}.txt")
        with open(p, "w") as f:
            f.write("".join(blocks[k::jobs]))
        os.chmod(p, 0o644)
        paths.append(p)

    def run_shard(p):
        return as_candidate([runner, p, "--timeout", "10"], 1800, env, work)

    results = {}
    with ThreadPoolExecutor(jobs) as ex:
        for rc, out in ex.map(run_shard, paths):
            for k, v in parse_frames(out).items():
                results.setdefault(k, v)
    subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], capture_output=True)
    ev["run_seconds"] = round(time.time() - r0, 1)
    ev["cases_crashed"] = sum(1 for v in results.values() if v[0] == "X")

    # 7. verdicts against the frozen expected transcripts
    with open(os.path.join(DATA, "expected.json")) as f:
        expected = json.load(f)
    buckets = {b: {"passed": 0, "total": 0, "weight": w} for b, w in WEIGHTS.items()}
    for cid, e in expected.items():
        got = results.get(cid)
        ok = bool(got and got[0] == "C" and got[2] == e["n"] and got[1] == e["s"])
        buckets[e["b"]]["total"] += 1
        buckets[e["b"]]["passed"] += int(ok)
    ev["buckets"] = buckets
    ev["cases_total"] = sum(b["total"] for b in buckets.values())
    ev["cases_passed"] = sum(b["passed"] for b in buckets.values())
    shutil.rmtree(work, ignore_errors=True)
except SystemExit:
    raise
except Exception as e:  # an exception in our own code is a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    write()
sys.exit(0)
