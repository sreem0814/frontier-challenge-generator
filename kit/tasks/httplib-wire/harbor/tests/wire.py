"""tests/wire.py: run case lists against the probe and server programs (shared by collect.py and the case
generator). Nothing here imports from /app.

probe cases: {"id", "op", "args": [bytes...]}      -> result string (one line from probe)
wire cases:  {"id", "send": bytes}                   -> result string (the raw response, escaped)
"""
import os
import re
import select
import signal
import socket
import subprocess
import threading
import time

PROBE_CASE_SECONDS = 20
WIRE_CASE_SECONDS = 6


def esc(b):
    out = []
    for c in b:
        if 0x20 <= c < 0x7F and c != 0x5C:
            out.append(chr(c))
        else:
            out.append("\\x%02x" % c)
    return "".join(out)


def _kill(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        p.wait(timeout=5)
    except Exception:
        pass


def run_probe_shard(binary, cases, preexec=None, env=None, cwd=None, deadline=None):
    """Feed cases to one probe process; restart after a crash or a stuck case. Returns {id: result}."""
    res = {}
    todo = list(cases)
    deadline = deadline or time.time() + 3600
    while todo and time.time() < deadline:
        p = subprocess.Popen([binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             preexec_fn=preexec, env=env, cwd=cwd, start_new_session=preexec is None)
        feed = "".join(c["id"] + "\t" + c["op"] + "".join("\t" + a.hex() for a in c["args"]) + "\n"
                       for c in todo).encode()

        def writer():
            try:
                p.stdin.write(feed)
                p.stdin.close()
            except Exception:
                pass

        wt = threading.Thread(target=writer, daemon=True)
        wt.start()
        got = 0
        buf = b""
        last = time.time()
        fd = p.stdout.fileno()
        while True:
            r, _, _ = select.select([fd], [], [], 1.0)
            if r:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    cid, _, val = line.decode("utf-8", "replace").partition("\t")
                    if got < len(todo) and cid == todo[got]["id"]:
                        res[cid] = val
                        got += 1
                        last = time.time()
                if got == len(todo):
                    break
            elif time.time() - last > PROBE_CASE_SECONDS or time.time() > deadline:
                break
        _kill(p)
        wt.join(timeout=5)
        if got < len(todo):
            res[todo[got]["id"]] = "CRASH"      # the case that killed or stalled the process fails
            got += 1
        todo = todo[got:]
    for c in todo:
        res.setdefault(c["id"], "CRASH")
    return res


_BOUNDARY = re.compile(rb"multipart/byteranges; boundary=([0-9A-Za-z'()+_,\-./:=?]+)")


def normalize_response(b):
    m = _BOUNDARY.search(b)
    if m:
        b = b.replace(m.group(1), b"BOUNDARY")
    return esc(b)


# Sent after every case's bytes: the server answers it and closes, which marks the end of the transcript without
# half-closing the socket (a half-close makes the server abandon streamed bodies). When the case leaves the
# server mid-message, these bytes become part of that message, which is deterministic as well.
END = b"GET /end HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\n"


def wire_one(port, data):
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    out = b""
    t_end = time.time() + WIRE_CASE_SECONDS
    try:
        try:
            s.sendall(data + END)
        except OSError:
            pass
        while True:
            left = t_end - time.time()
            if left <= 0:
                return "TIMEOUT"
            s.settimeout(left)
            try:
                c = s.recv(1 << 16)
            except socket.timeout:
                return "TIMEOUT"
            except ConnectionResetError:
                break
            if not c:
                break
            out += c
    finally:
        s.close()
    return normalize_response(out)


class ServerProc:
    def __init__(self, binary, port, workdir, preexec=None, env=None):
        self.binary, self.port, self.workdir, self.preexec, self.env = binary, port, workdir, preexec, env
        self.p = None

    def start(self):
        self.stop()
        self.p = subprocess.Popen([self.binary, str(self.port), self.workdir], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, preexec_fn=self.preexec,
                                  env=self.env, cwd=self.workdir, start_new_session=self.preexec is None)
        r, _, _ = select.select([self.p.stdout], [], [], 20)
        ok = bool(r) and self.p.stdout.readline().strip() == b"ready"
        if ok:   # the listen loop starts right after "ready"
            for _ in range(100):
                try:
                    socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                    return True
                except OSError:
                    time.sleep(0.05)
        return False

    def alive(self):
        return self.p is not None and self.p.poll() is None

    def stop(self):
        if self.p is not None:
            _kill(self.p)
            self.p = None


def run_wire_shard(binary, port, workdir, cases, preexec=None, env=None, deadline=None):
    res = {}
    deadline = deadline or time.time() + 3600
    srv = ServerProc(binary, port, workdir, preexec, env)
    up = srv.start()
    for c in cases:
        if time.time() > deadline:
            res[c["id"]] = "DEADLINE"
            continue
        if not up or not srv.alive():
            up = srv.start()
            if not up:
                res[c["id"]] = "NOSERVER"
                continue
        try:
            r = wire_one(port, c["send"])
        except OSError as e:
            r = "CONNFAIL"
        if not srv.alive():          # the case killed the server
            r = "SERVERDIED"
        res[c["id"]] = r
    srv.stop()
    return res


AREAS = ["H", "B", "Q", "M", "R", "N"]


def credit(cases, results):
    """Per-case credit with the family rule: a case whose expected result is a rejection (err) counts only when
    some non-rejection case of the same family also passes (a family with no such case is exempt).
    Returns {id: 0 or 1}."""
    passed = {c["id"]: results.get(c["id"]) == c["expect"] for c in cases}
    fam_ok, fam_has_ok = {}, {}
    for c in cases:
        if not c["err"]:
            fam_has_ok[c["fam"]] = True
            if passed[c["id"]]:
                fam_ok[c["fam"]] = True
    out = {}
    for c in cases:
        p = passed[c["id"]]
        if p and c["err"] and fam_has_ok.get(c["fam"]) and not fam_ok.get(c["fam"]):
            p = False
        out[c["id"]] = int(p)
    return out


def area_scores(cases, cred):
    tot = {a: 0 for a in AREAS}
    got = {a: 0 for a in AREAS}
    for c in cases:
        tot[c["area"]] += 1
        got[c["area"]] += cred[c["id"]]
    return {a: (got[a], tot[a]) for a in AREAS}
