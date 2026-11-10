"""Feed cases to modify_harness and collect its answers, surviving crashes and hangs.

run(binary, cases, batch=200, timeout=120, preexec=None) -> {case id: (status, [body bytes] or None)}
status is "ok", "init_fail", "error", "crash" or "timeout". A case whose result never arrives
(the harness died or hung on it) is recorded as "crash"/"timeout" and the harness restarts at the next case.
"""
import subprocess


def _encode(case):
    lines = ["C " + case["id"]]
    for k, v in case["props"]:
        lines.append("P " + k + "\t" + v)
    for r in case["records"]:
        lines.append("R " + r)
    lines.append("E")
    return "\n".join(lines) + "\n"


def _parse(out):
    res = {}
    cur = None
    outs = []
    want = 0
    for line in out.splitlines():
        if line.startswith("C "):
            parts = line[2:].rsplit(" ", 2)
            if len(parts) >= 2 and parts[-1] == "init_fail":
                cid = line[2:-len(" init_fail")]
                res[cid] = ("init_fail", None)
                cur = None
            elif len(parts) == 3 and parts[1] == "ok":
                cur = parts[0]
                want = int(parts[2])
                outs = []
            else:
                bits = line[2:].split(" ")
                if "error" in bits:
                    i = bits.index("error")
                    res[" ".join(bits[:i])] = ("error", None)
                cur = None
        elif line.startswith("O ") and cur is not None:
            try:
                outs.append(bytes.fromhex(line[2:].strip()))
            except ValueError:
                outs.append(b"")
        elif line == "E" and cur is not None:
            if len(outs) == want:
                res[cur] = ("ok", outs)
            else:
                res[cur] = ("error", None)
            cur = None
    return res


def run(binary, cases, batch=200, timeout=120, preexec=None, env=None):
    results = {}
    pending = list(cases)
    while pending:
        chunk = pending[:batch]
        data = "".join(_encode(c) for c in chunk)
        status = "crash"
        try:
            p = subprocess.run([binary], input=data, capture_output=True, text=True,
                               errors="replace", timeout=timeout, preexec_fn=preexec, env=env)
            out = p.stdout
            if p.returncode == 0:
                status = None
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            status = "timeout"
        got = _parse(out)
        done = 0
        for c in chunk:
            if c["id"] in got:
                results[c["id"]] = got[c["id"]]
                done += 1
            else:
                break
        if done == len(chunk):
            pending = pending[len(chunk):]
            continue
        # the case at position `done` killed or hung the harness
        bad = chunk[done]
        results[bad["id"]] = (status or "crash", None)
        pending = pending[done + 1:]
    return results
