"""tests/collect.py: evidence only. Assembles a clean module tree, runs the gates, the behavioural cases and the
integration tests, and writes evidence.json on every path. compute_reward.py makes every scoring decision.

Clean tree: every file comes from the pristine snapshot under /tests/data, except the non-test .go files of the four
packages the agent rebuilds, which come from /app. The generated tg/ package is taken from /app only if it is
byte-identical to the base. Candidate code (the build, the case runner, the test binaries) runs as an unprivileged
uid in its own process group with timeouts, offline, with a fresh build cache.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time

TESTS = "/tests"
APP = "/app"
DATA = os.path.join(TESTS, "data")
GOROOT = "/usr/local/go"
GOMODCACHE = "/go/pkg/mod"
DELIVERABLES = ["proto/codec", "mtproxy/obfuscated2", "crypto", "exchange", "mtproto", "mtproto/salts", "rpc"]
FORBIDDEN_IMPORTS = {"unsafe", "C", "os/exec", "syscall", "plugin", "runtime/cgo"}
FORBIDDEN_PREFIXES = ("golang.org/x/sys",)
FORBIDDEN_DIRECTIVES = re.compile(rb"//\s*go:(linkname|cgo_)")

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
args = ap.parse_args()

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "build_packages_ok": 0, "build_packages_total": len(DELIVERABLES),
    "cheat_detected": False, "gate_failed": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
    "notes": [], "failed_cases": [], "timings": {},
}
T0 = time.time()


def write():
    ev["timings"]["total"] = round(time.time() - T0, 1)
    with open(args.out, "w") as f:
        json.dump(ev, f, indent=1)


def note(msg):
    ev["notes"].append(msg[:2000])


class Gate(Exception):
    """A hard gate failed: the run is measurable and scores 0."""

    def __init__(self, reason, cheat=False):
        super().__init__(reason)
        self.reason = reason
        self.cheat = cheat


def tree_digest(root, skip_top=()):
    """Digest of a directory tree: sorted relative paths, file contents and symlink targets."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d not in skip_top]
        dirnames.sort()
        entries = sorted(filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))])
        for name in entries:
            p = os.path.join(dirpath, name)
            rel = os.path.normpath(os.path.join(rel_dir, name))
            h.update(rel.encode() + b"\0")
            if os.path.islink(p):
                h.update(b"L" + os.readlink(p).encode() + b"\0")
            elif os.path.isfile(p):
                fh = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        fh.update(chunk)
                h.update(b"F" + fh.digest())
            else:
                h.update(b"O")
    return h.hexdigest()


def demote():
    os.setsid()
    os.setgroups([])
    os.setgid(args.uid)
    os.setuid(args.uid)


def kill_uid():
    subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_cand(cmd, timeout, cwd, env, out_path=None):
    """Run a candidate command as args.uid; kill its process group on timeout. Returns (rc or None, output)."""
    out_f = open(out_path, "wb") if out_path else subprocess.PIPE
    p = subprocess.Popen(cmd, cwd=cwd, env=env, preexec_fn=demote, stdout=out_f, stderr=subprocess.STDOUT)
    try:
        out, _ = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = p.communicate()
        rc = None
    if out_path:
        out_f.close()
        with open(out_path, "rb") as f:
            out = f.read()
    return rc, (out or b"").decode("utf-8", "replace")


def main():
    work = tempfile.mkdtemp(prefix="cg-grade-", dir="/tmp")
    os.chmod(work, 0o755)
    td = os.path.join(work, "td")
    cand_dirs = {k: os.path.join(work, k) for k in ("home", "tmp", "gocache", "gopath", "run", "bin")}
    for d in cand_dirs.values():
        os.makedirs(d)
        os.chown(d, args.uid, args.uid)
    env = {
        "PATH": GOROOT + "/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": cand_dirs["home"], "TMPDIR": cand_dirs["tmp"], "GOTMPDIR": cand_dirs["tmp"],
        "GOCACHE": cand_dirs["gocache"], "GOPATH": cand_dirs["gopath"], "GOMODCACHE": GOMODCACHE,
        "GOFLAGS": "-mod=readonly -buildvcs=false", "GOPROXY": "off", "GOSUMDB": "off", "GOTOOLCHAIN": "local",
        "GOENV": "off", "GOTELEMETRY": "off", "CGO_ENABLED": "0", "LANG": "C.UTF-8",
    }

    # 1. Runtime: the toolchain must be present at all (missing data under /tests is a harness fault).
    for f in ("pristine.tar.xz", "digests.json", "expected.json", "integration.json"):
        if not os.path.isfile(os.path.join(DATA, f)):
            ev["runtime_ok"], ev["runtime_error"] = False, "missing /tests/data/" + f
            return
    digests = json.load(open(os.path.join(DATA, "digests.json")))
    if not os.path.isfile(os.path.join(GOROOT, "bin", "go")):
        raise Gate("the Go toolchain at /usr/local/go is missing", cheat=True)

    rc, _ = run_cand(["cat", os.path.join(DATA, "expected.json")], 30, cand_dirs["run"], env)
    ev["sealed_data_readable_by_candidate"] = rc == 0

    # 2. Integrity of the toolchain and the module cache.
    t = time.time()
    if tree_digest(GOROOT) != digests["goroot"]:
        raise Gate("the Go toolchain under /usr/local/go was modified", cheat=True)
    ev["timings"]["goroot"] = round(time.time() - t, 1)

    # 3. Clean tree: pristine snapshot + tg/ (if unchanged) + the agent's four packages.
    t = time.time()
    with tarfile.open(os.path.join(DATA, "pristine.tar.xz")) as tf:
        try:
            tf.extractall(work, filter="data")
        except TypeError:  # Python without extraction filters; the archive is ours
            tf.extractall(work)
    if not os.path.isdir(os.path.join(APP, "tg")) or tree_digest(os.path.join(APP, "tg")) != digests["tg"]:
        raise Gate("generated package /app/tg was modified or removed (it is outside the four packages)")
    shutil.copytree(os.path.join(APP, "tg"), os.path.join(td, "tg"), symlinks=False)
    copied = []
    for d in DELIVERABLES:
        dst = os.path.join(td, d)
        for name in os.listdir(dst):
            if name.endswith(".go"):
                os.remove(os.path.join(dst, name))
        src = os.path.join(APP, d)
        if not os.path.isdir(src) or os.path.islink(src):
            note(f"{d}: missing")
            continue
        for name in sorted(os.listdir(src)):
            p = os.path.join(src, name)
            if not name.endswith(".go") or name.endswith("_test.go"):
                continue
            if os.path.islink(p) or not os.path.isfile(p):
                note(f"{d}/{name}: not a regular file, ignored")
                continue
            with open(p, "rb") as f:
                body = f.read()
            if len(body) > 4 << 20:
                raise Gate(f"{d}/{name} is larger than 4 MiB")
            if FORBIDDEN_DIRECTIVES.search(body):
                raise Gate(f"{d}/{name} uses a forbidden //go: directive (linkname or cgo)", cheat=True)
            with open(os.path.join(dst, name), "wb") as f:
                f.write(body)
            copied.append(f"{d}/{name}")
    ev["copied_files"] = len(copied)
    for dirpath, dirnames, filenames in os.walk(td):
        os.chmod(dirpath, 0o755)
    ev["timings"]["assemble"] = round(time.time() - t, 1)

    # 4. Module cache integrity (as the candidate uid: read-only access is enough).
    t = time.time()
    rc, out = run_cand(["go", "mod", "verify"], 600, td, env)
    ev["timings"]["modverify"] = round(time.time() - t, 1)
    if rc != 0:
        note("go mod verify: " + out[-1500:])
        raise Gate("the module cache under /go/pkg/mod does not match go.sum (go mod verify failed)", cheat=True)

    # 5. Imports of the four packages.
    rc, out = run_cand(["go", "list", "-e", "-json=ImportPath,Imports,CgoFiles,EmbedPatterns,Error"]
                       + ["./" + d for d in DELIVERABLES], 600, td, env)
    if rc is None:
        raise Gate("go list timed out")
    dec = json.JSONDecoder()
    pos, pkgs = 0, []
    while pos < len(out):
        while pos < len(out) and out[pos].isspace():
            pos += 1
        if pos >= len(out):
            break
        try:
            obj, pos = dec.raw_decode(out, pos)
        except ValueError:
            break
        pkgs.append(obj)
    for pk in pkgs:
        for imp in pk.get("Imports") or []:
            if imp in FORBIDDEN_IMPORTS or imp.startswith(FORBIDDEN_PREFIXES):
                raise Gate(f"{pk.get('ImportPath')} imports forbidden package {imp}", cheat=True)
        if pk.get("CgoFiles"):
            raise Gate(f"{pk.get('ImportPath')} uses cgo", cheat=True)

    # 6. Build gate: every package of the module (the four, their dependents and selfcheck's API check).
    t = time.time()
    ok_pkgs = 0
    for d in DELIVERABLES:
        rc, out = run_cand(["go", "build", "./" + d], 900, td, env)
        if rc == 0:
            ok_pkgs += 1
    ev["build_packages_ok"] = ok_pkgs
    rc, out = run_cand(["go", "build", "./..."], 1800, td, env)
    ev["timings"]["build"] = round(time.time() - t, 1)
    if rc != 0:
        note("go build ./...: " + out[-3000:])
        raise Gate("go build ./... failed on the clean tree (see notes)")
    ev["build_ok"] = True

    # 7. Behavioural cases.
    t = time.time()
    expected = json.load(open(os.path.join(DATA, "expected.json")))  # [[id, out], ...] in run order
    os.makedirs(os.path.join(td, "internal"), exist_ok=True)
    shutil.copytree(os.path.join(TESTS, "harness"), os.path.join(td, "internal", "zgrade"))
    shutil.copytree(os.path.join(TESTS, "ref"), os.path.join(td, "internal", "zref"))
    for dirpath, dirnames, filenames in os.walk(os.path.join(td, "internal")):
        os.chmod(dirpath, 0o755)
        for fn in filenames:
            os.chmod(os.path.join(dirpath, fn), 0o644)
    runner = os.path.join(cand_dirs["bin"], "zgrade")
    rc, out = run_cand(["go", "build", "-o", runner, "./internal/zgrade"], 900, td, env)
    if rc != 0:
        note("case runner build: " + out[-3000:])
        raise Gate("the exported API of the four packages changed: the case runner does not compile (see notes)")
    results = {}
    out_file = os.path.join(cand_dirs["run"], "cases.jsonl")
    n_cases = len(expected)
    start, restarts = 0, 0
    while start < n_cases and restarts < 300:
        kill_uid()
        try:
            os.remove(out_file)
        except OSError:
            pass
        rc, out = run_cand([runner, "-out", out_file, "-from", str(start)], 1200, cand_dirs["run"], env)
        lines = []
        try:
            with open(out_file, "rb") as f:
                lines = f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            pass
        last = start - 1
        for line in lines:
            try:
                e = json.loads(line)
                i, cid, res = int(e["i"]), str(e["id"]), str(e["out"])
            except (ValueError, KeyError, TypeError):
                continue
            if start <= i < n_cases and expected[i][0] == cid and i not in results:
                results[i] = res
                last = max(last, i)
        restarts += 1
        if rc == 0 and last >= n_cases - 1:
            break
        if last < start:
            # No progress: the process died (or was killed) on the first case of this run.
            results.setdefault(start, "CRASH")
            start += 1
            continue
        start = last + 1
        if not (rc == 3 and results.get(last) == "TIMEOUT") and start < n_cases:
            # The process died on case `start` without reporting it.
            results.setdefault(start, "CRASH" if rc is not None else "TIMEOUT")
            start += 1
    kill_uid()
    buckets = {}
    failed = []
    for i, (cid, want) in enumerate(expected):
        b = cid.split("/")[0]
        bk = buckets.setdefault(b, {"passed": 0, "total": 0})
        bk["total"] += 1
        if results.get(i) == want:
            bk["passed"] += 1
        else:
            failed.append(cid)
    ev["timings"]["cases"] = round(time.time() - t, 1)
    ev["case_restarts"] = restarts

    # 8. Integration tests from the module's own suite (each test alone, fixed list).
    t = time.time()
    integ = json.load(open(os.path.join(DATA, "integration.json")))  # [[pkg, test], ...]
    ib = {"passed": 0, "total": len(integ)}
    binaries = {}
    for pkg in sorted({p for p, _ in integ}):
        name = pkg.replace("/", "_") + ".test"
        path = os.path.join(cand_dirs["bin"], name)
        rc, out = run_cand(["go", "test", "-c", "-o", path, "./" + pkg], 900, td, env)
        binaries[pkg] = path if rc == 0 and os.path.isfile(path) else None
        if binaries[pkg] is None:
            note(f"test build {pkg}: " + out[-800:])
    for pkg, test in integ:
        ok = False
        if binaries.get(pkg):
            kill_uid()
            rc, out = run_cand([binaries[pkg], "-test.run", "^" + test + "$", "-test.count=1", "-test.v",
                                "-test.timeout", "90s"], 150, os.path.join(td, pkg), env)
            ok = rc == 0 and re.search(r"^--- PASS: " + re.escape(test) + r" ", out, re.M) is not None
        if ok:
            ib["passed"] += 1
        else:
            failed.append(f"integration/{pkg}/{test}")
    kill_uid()
    buckets["integration"] = ib
    ev["timings"]["integration"] = round(time.time() - t, 1)

    ev["buckets"] = buckets
    ev["cases_total"] = sum(b["total"] for b in buckets.values())
    ev["cases_passed"] = sum(b["passed"] for b in buckets.values())
    ev["failed_cases"] = failed[:400]
    shutil.rmtree(work, ignore_errors=True)


try:
    main()
except Gate as g:
    ev["gate_failed"] = True
    ev["gate_reason"] = g.reason
    ev["cheat_detected"] = ev["cheat_detected"] or g.cheat
    ev["build_ok"] = ev["build_ok"] and not g.cheat
except Exception as e:  # an exception in our own code is a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    kill_uid()
    write()
sys.exit(0)
