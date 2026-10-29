"""tests/collect.py: evidence only. Builds the candidate's xlsdump from a clean copy of /app/calamine-go,
runs the anti-cheat gates, runs every hidden workbook and records per-unit results in evidence.json.

Every path writes evidence.json; a failed build is evidence too. compute_reward.py makes all scoring
decisions. Candidate code (the Go build and the xlsdump runs) executes as an unprivileged uid in its own
session with resource limits and a timeout per case.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import units as U  # noqa: E402  (the verifier's own module, from /tests)

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
args = ap.parse_args()

TESTS = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(TESTS, "data")
APP_MODULE = "/app/calamine-go"
GOROOT = "/usr/local/go"
BUCKETS = ("xls", "xlsx", "xlsb", "ods", "vba", "pictures", "objects")
CASE_TIMEOUT = 20
BUILD_TIMEOUT = 900
MAX_OUT = 256 << 20
FORBIDDEN_IMPORTS = {"C", "os/exec", "plugin", "syscall", "runtime/cgo", "golang.org/x/sys/unix",
                     "golang.org/x/sys/execabs", "internal/syscall/unix", "internal/syscall/exec"}
FORBIDDEN_TOKENS = re.compile(r"go:linkname|go:cgo_|StartProcess|ForkExec|#cgo|import\s+\"C\"")
INTERPRETERS = ["/usr/bin/python3", "/usr/bin/perl", "/usr/bin/awk", "/usr/bin/mawk"]

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "build_log": "", "tamper": [],
    "cases_total": 0, "cases_passed": 0, "units_total": 0, "units_passed": 0,
    "buckets": {b: {"files": 0, "score_sum": 0.0, "units_total": 0, "units_passed": 0} for b in BUCKETS},
    "failures": [],
}


def write():
    with open(args.out, "w") as f:
        json.dump(ev, f)


def tree_digest(root):
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(root, followlinks=False):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rel = os.path.relpath(p, root)
            h.update(rel.encode() + b"\0")
            if os.path.islink(p):
                h.update(b"L" + os.readlink(p).encode() + b"\0")
                continue
            fh = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    fh.update(chunk)
            h.update(fh.digest())
    return h.hexdigest()


def limits(cpu, mem):
    def fn():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUT, MAX_OUT))
        os.setgroups([])
        os.setgid(args.uid)
        os.setuid(args.uid)
    return fn


def run_as_candidate(cmd, timeout, cwd, env, cpu=120, mem=4 << 30):
    """Run cmd as the candidate uid; stdout and stderr go to size-limited files. Returns (rc, out, err)."""
    with open(os.path.join(cwd, ".stdout"), "w+b") as fo, open(os.path.join(cwd, ".stderr"), "w+b") as fe:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, preexec_fn=limits(cpu, mem),
                             stdin=subprocess.DEVNULL, stdout=fo, stderr=fe)
        try:
            p.wait(timeout=timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            rc = None
        try:
            os.killpg(p.pid, signal.SIGKILL)  # the whole session, finished or not
        except (ProcessLookupError, PermissionError):
            pass
        p.wait()
        fo.seek(0)
        fe.seek(0)
        out = fo.read(MAX_OUT)
        err = fe.read(1 << 20)
    for f in (".stdout", ".stderr"):
        try:
            os.remove(os.path.join(cwd, f))
        except OSError:
            pass
    return rc, out, err


def go_env(home):
    return {
        "PATH": GOROOT + "/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": home, "GOPATH": home + "/gopath", "GOCACHE": home + "/gocache", "GOROOT": GOROOT,
        "GOFLAGS": "-mod=vendor", "GOTOOLCHAIN": "local", "GOPROXY": "off", "GONOSUMDB": "*",
        "GOSUMDB": "off", "CGO_ENABLED": "0", "GOENV": "off", "GOWORK": "off", "LANG": "C.UTF-8",
    }


saved_modes = {}
try:
    # 1. Harness sanity: the hidden data and the toolchain must be present.
    manifest = json.load(open(os.path.join(DATA, "manifest.json")))
    if not os.path.isfile(GOROOT + "/bin/go"):
        raise RuntimeError("Go toolchain missing at " + GOROOT)

    # 2. Gate: the Go toolchain must be the one shipped in the image.
    if tree_digest(GOROOT) != manifest["goroot_sha256"]:
        ev["cheat_detected"] = True
        ev["gate_reason"] = "the Go toolchain under /usr/local/go was modified"
        raise StopIteration

    # 3. Clean copy of the candidate module; go.mod, go.sum and vendor/ come from the pristine snapshot.
    WORK = tempfile.mkdtemp(prefix="cg-grade-")  # fresh, root-owned, never a pre-planted path
    os.chmod(WORK, 0o755)
    src = os.path.join(WORK, "src")
    if not os.path.isdir(APP_MODULE):
        ev["gate_reason"] = "/app/calamine-go is missing"
        raise StopIteration

    def ignore(d, names):
        out = []
        for n in names:
            p = os.path.join(d, n)
            if os.path.islink(p):
                out.append(n)  # symlinks are not followed or copied
            elif d == APP_MODULE and n in ("vendor", ".git", "go.mod", "go.sum", "go.work", "go.work.sum"):
                out.append(n)
        return out
    shutil.copytree(APP_MODULE, src, ignore=ignore)
    for f in ("go.mod", "go.sum"):
        shutil.copy(os.path.join(DATA, "pristine", f), os.path.join(src, f))
    with tarfile.open(os.path.join(DATA, "pristine", "vendor.tar.gz")) as t:
        try:
            t.extractall(src, filter="data")
        except TypeError:  # Python without extraction filters; the archive is our own
            t.extractall(src)
    for f in ("go.mod", "go.sum"):
        a = os.path.join(APP_MODULE, f)
        if os.path.isfile(a) and open(a, "rb").read() != open(os.path.join(src, f), "rb").read():
            ev["tamper"].append(f + " differs from the shipped file (restored before the build)")

    # 4. Gate: no process spawning, cgo or linker tricks in the candidate's own packages.
    offenders = []
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if not (dp == src and d == "vendor")]
        for fn in fns:
            if fn.endswith((".go", ".s", ".c", ".h", ".cc", ".cpp", ".syso")):
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, src)
                if not fn.endswith(".go"):
                    offenders.append(rel + ": non-Go source or object file")
                    continue
                text = open(p, encoding="utf-8", errors="replace").read()
                for m in FORBIDDEN_TOKENS.finditer(text):
                    offenders.append(rel + ": uses " + m.group(0))
                    break
    home = os.path.join(WORK, "home")
    os.makedirs(home)
    for d in (WORK, src, home):
        os.chown(d, args.uid, args.uid)
    for dp, dns, fns in os.walk(src):
        for n in dns + fns:
            try:
                os.lchown(os.path.join(dp, n), args.uid, args.uid)
            except OSError:
                pass
    env = go_env(home)
    rc, out, err = run_as_candidate([GOROOT + "/bin/go", "list", "-deps", "-f",
                                     "{{if not .Standard}}{{.ImportPath}}{{end}}|{{join .Imports \",\"}}|{{.Standard}}",
                                     "./cmd/xlsdump"], 300, src, env, cpu=600)
    if rc == 0:
        for line in out.decode(errors="replace").splitlines():
            name, imps, std = (line.split("|") + ["", "", ""])[:3]
            if std == "true" or not name or name.startswith("golang.org/x/text"):
                continue
            for imp in imps.split(","):
                if imp in FORBIDDEN_IMPORTS:
                    offenders.append(name + ": imports " + imp)
    if offenders:
        ev["cheat_detected"] = True
        ev["gate_reason"] = "forbidden construct: " + "; ".join(sorted(set(offenders))[:5])
        raise StopIteration

    # 5. Build gate.
    binp = os.path.join(WORK, "bin")
    os.makedirs(binp)
    os.chown(binp, args.uid, args.uid)
    exe = os.path.join(binp, "xlsdump")
    t0 = time.time()
    rc, out, err = run_as_candidate([GOROOT + "/bin/go", "build", "-trimpath", "-o", exe, "./cmd/xlsdump"],
                                    BUILD_TIMEOUT, src, env, cpu=BUILD_TIMEOUT * 8, mem=8 << 30)
    ev["build_seconds"] = round(time.time() - t0, 1)
    ev["build_log"] = (err or b"").decode(errors="replace")[-2000:]
    if rc != 0 or os.path.islink(exe) or not os.path.isfile(exe):
        ev["gate_reason"] = "go build ./cmd/xlsdump failed"
        raise StopIteration
    ev["build_ok"] = True
    for p in (exe, binp, WORK):  # nothing the cases can reach stays writable by the candidate uid
        os.chown(p, 0, 0)
    os.chmod(exe, 0o755)

    # 6. Interpreters are not executable for the candidate while it runs (no shelling out).
    for p in INTERPRETERS:
        rp = os.path.realpath(p)
        if os.path.isfile(rp) and rp not in saved_modes:
            saved_modes[rp] = stat.S_IMODE(os.stat(rp).st_mode)
            os.chmod(rp, saved_modes[rp] & ~0o007)

    ev["tests_private"] = (stat.S_IMODE(os.stat(TESTS).st_mode) & 0o077) == 0
    # 7. Cases: a fixed list of hidden workbooks, each copied alone into a fresh directory.
    inroot = os.path.join(WORK, "in")
    os.makedirs(inroot)
    os.chmod(inroot, 0o755)
    cases = manifest["cases"]
    ev["cases_total"] = len(cases)
    run_env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C.UTF-8"}

    def run_case(i_case):
        i, case = i_case
        name, fmt = case["file"], case["format"]
        d = os.path.join(inroot, "%04d" % i)
        os.makedirs(d)
        os.chmod(d, 0o755)
        p = os.path.join(d, name)
        shutil.copy(os.path.join(DATA, "workbooks", name), p)
        os.chmod(p, 0o644)
        expected = json.load(gzip.open(os.path.join(DATA, "expected", name + ".json.gz")))
        us = U.units(expected)
        rc, out, err = run_as_candidate([exe, p], CASE_TIMEOUT, d, run_env, cpu=CASE_TIMEOUT * 2, mem=4 << 30)
        cand = None
        if rc == 0 and out:
            try:
                cand = json.loads(out.decode("utf-8"))
            except Exception:
                cand = None
        res = [(U.bucket(uid, fmt), uid, cand is not None and U.unit_ok(uid, pl, cand, expected)) for uid, pl in us]
        shutil.rmtree(d, ignore_errors=True)
        why = "ok" if cand is not None else ("timeout" if rc is None else "exit %s / invalid JSON" % rc)
        return name, fmt, res, why

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(run_case, enumerate(cases)))
    for name, fmt, res, why in results:
        for bk in sorted(set(b for b, _, _ in res)):
            rb = [r for b, _, r in res if b == bk]
            okb = sum(1 for r in rb if r)
            b = ev["buckets"][bk]
            b["files"] += 1
            b["units_total"] += len(rb)
            b["units_passed"] += okb
            b["score_sum"] += okb / len(rb)
        ok = sum(1 for _, _, r in res if r)
        ev["units_total"] += len(res)
        ev["units_passed"] += ok
        if ok == len(res):
            ev["cases_passed"] += 1
        elif len(ev["failures"]) < 40:
            ev["failures"].append({"file": name, "why": why, "failed_units": [u for _, u, r in res if not r][:6]})
except StopIteration:
    pass
except Exception as e:  # an exception in our own code is a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    if "WORK" in globals():
        shutil.rmtree(WORK, ignore_errors=True)
    for p, m in saved_modes.items():
        try:
            os.chmod(p, m)
        except OSError:
            pass
    write()
sys.exit(0)
