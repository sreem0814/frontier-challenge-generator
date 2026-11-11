"""tests/collect.py: evidence only. Rebuilds flatc from the pristine tree with src/idl_parser.cpp taken from
/app, runs every hidden case with it and writes evidence.json; compute_reward.py turns that into the reward.

Every path writes evidence.json. The build and every flatc run happen as an unprivileged uid, in their own
process groups, with time and memory limits; the hidden data stays readable by root only while candidate code
runs. A case is a set of input files and one flatc command line (see fbcase.py); it passes when the transcript
of the run (success or failure, the printed messages where the bucket checks them, every output file) hashes to
the frozen reference transcript. schema_bfbs cases also feed schema_model, which compares the decoded content
of the binary schema instead of its bytes.
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fbcase  # noqa: E402  (the verifier's own module, from /tests)

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app")
ap.add_argument("--base", default="/usr/src/flatbuffers-base")
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--tamper", default="", help="file with dpkg --verify findings for the verifier's packages")
ap.add_argument("--sweep", default="{}", help="JSON line from sweep.py: session leftovers that were stopped")
args = ap.parse_args()

DATA = os.path.join(HERE, "data")
WEIGHTS = {"schema_model": 0.06, "schema_bfbs": 0.08, "codegen": 0.14, "json_binary": 0.18, "json_text": 0.08,
           "diag": 0.20, "proto": 0.10, "bfbs_input": 0.08, "conform": 0.08}
TARGET = "src/idl_parser.cpp"
MAX_FILE = 8 << 20
CXX = "/usr/bin/x86_64-linux-gnu-g++-12"
LDSO_CONF_D = {"libc.conf", "x86_64-linux-gnu.conf"}

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
    "base_ok": None, "base_mismatch": [], "target_found": False, "tamper": [],
    "build_seconds": 0.0, "run_seconds": 0.0, "build_log_tail": "", "cases_failed_to_run": 0,
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


def as_candidate(cmd, timeout, env, cwd):
    p = subprocess.Popen(cmd, preexec_fn=drop_privileges, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=env, cwd=cwd)
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


def chown_tree(top):
    for root, dirs, files in os.walk(top):
        os.chown(root, args.uid, args.uid)
        for n in files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chown(p, args.uid, args.uid)


try:
    try:
        ev["leftovers_stopped"] = json.loads(args.sweep).get("stopped", [])
    except ValueError:
        ev["leftovers_stopped"] = []

    # 1. the verifier's own tools must be the packaged ones; no preloaded or redirected libraries
    if args.tamper and os.path.isfile(args.tamper):
        with open(args.tamper) as f:
            ev["tamper"] = [ln.strip() for ln in f if ln.strip()][:10]
    if os.path.lexists("/etc/ld.so.preload"):
        ev["tamper"].append("/etc/ld.so.preload exists")
    try:
        extra = sorted(set(os.listdir("/etc/ld.so.conf.d")) - LDSO_CONF_D)
    except OSError:
        extra = []
    if extra:
        ev["tamper"].append("/etc/ld.so.conf.d has extra entries: " + ", ".join(extra[:3]))
    if os.path.islink(CXX) or not os.path.isfile(CXX):
        ev["tamper"].append(CXX + " is not the packaged compiler")
    if ev["tamper"]:
        gate("system files used by the verifier were modified: " + "; ".join(ev["tamper"][:3]), cheat=True)

    # 2. the pristine tree in the image must match the shipped manifest (SHA-256 of the content, then SHA-256 of
    #    the relative path, one file per line)
    manifest = {}
    with open(os.path.join(DATA, "base.manifest")) as f:
        for ln in f:
            h, ph = ln.split()
            manifest[ph] = h
    seen, bad = set(), []
    for root, dirs, files in os.walk(args.base):
        for n in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, args.base)
            ph = hashlib.sha256(rel.encode("utf-8", "surrogateescape")).hexdigest()
            seen.add(ph)
            if ph not in manifest:
                bad.append("added " + rel)
            elif os.path.islink(p) or not os.path.isfile(p) or sha256_file(p) != manifest[ph]:
                bad.append("changed " + rel)
    missing = sum(1 for ph in manifest if ph not in seen)
    if missing:
        bad.append(f"{missing} files missing")
    ev["base_mismatch"] = bad[:20]
    ev["base_ok"] = not bad
    if bad:
        gate(f"the pristine tree {args.base} was modified ({len(bad)} files, e.g. {bad[0]})", cheat=True)

    # 3. work tree: pristine copy plus src/idl_parser.cpp from /app
    work = tempfile.mkdtemp(prefix="grade-")
    os.chmod(work, 0o755)
    src = os.path.join(work, "src")
    shutil.copytree(args.base, src, symlinks=True)
    try:
        content = read_regular(os.path.join(args.app, TARGET))
    except OSError:
        content = None
    if content is not None:
        ev["target_found"] = True
        dst = os.path.join(src, TARGET)
        os.unlink(dst)
        with open(dst, "wb") as f:
            f.write(content)
    chown_tree(work)
    home = os.path.join(work, "home")
    os.mkdir(home)
    os.chown(home, args.uid, args.uid)
    env = {"PATH": "/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8"}

    # 4. build gate: configure and build flatc as the candidate uid (the same CMake call as /app/build.sh)
    b0 = time.time()
    bdir = os.path.join(work, "build")
    rc, log = as_candidate(["cmake", "-S", src, "-B", bdir, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                            "-DFLATBUFFERS_BUILD_TESTS=OFF", "-DFLATBUFFERS_BUILD_FLATLIB=OFF",
                            "-DFLATBUFFERS_BUILD_FLATHASH=OFF", "-DCMAKE_CXX_COMPILER=" + CXX],
                           600, env, work)
    if rc == 0:
        rc, log2 = as_candidate(["ninja", "-C", bdir, f"-j{args.jobs}", "flatc"], 2400, env, work)
        log += log2
    ev["build_seconds"] = round(time.time() - b0, 1)
    ev["build_log_tail"] = log[-3000:].decode("utf-8", "replace")
    built = os.path.join(bdir, "flatc")
    if rc != 0 or not os.path.isfile(built):
        errs = [ln for ln in log.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
        gate("flatc build failed" + (": " + errs[0][:300] if errs else ""))
    # run a root-owned copy, so nothing the candidate uid left running can swap the binary
    flatc = os.path.join(work, "flatc-under-test")
    shutil.copyfile(built, flatc)
    os.chmod(flatc, 0o755)
    ev["build_ok"] = True

    # 5. sealing evidence: the candidate uid must not be able to read the expected results
    probe = subprocess.run(["setpriv", f"--reuid={args.uid}", f"--regid={args.uid}", "--clear-groups",
                            "test", "-r", os.path.join(DATA, "expected.json")])
    ev["expected_sealed"] = probe.returncode != 0

    # 6. run every hidden case (fixed denominator: a crash, a timeout or a missing output fails the case)
    with open(os.path.join(DATA, "cases.json")) as f:
        cases = json.load(f)
    with open(os.path.join(DATA, "expected.json")) as f:
        expected = json.load(f)
    cdir = os.path.join(work, "cases")
    os.mkdir(cdir)
    os.chmod(cdir, 0o755)
    cenv = {"PATH": "/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8"}

    def run_case(case):
        d = os.path.join(cdir, case["id"])
        try:
            os.mkdir(d)
            fbcase.materialize(case["files"], d)
            chown_tree(d)
            rc, out, err = fbcase.run(flatc, case["argv"], d, timeout=20, preexec=drop_privileges, env=cenv)
            t, outs = fbcase.transcript(case["b"], rc, out, err, d)
            m = fbcase.model_digest(rc, outs) if case["b"] == "schema_bfbs" else None
            return case["id"], fbcase.digest(t), m, rc is None
        except Exception as e:  # a case the candidate broke (e.g. an output tree we cannot walk) fails
            return case["id"], "error " + type(e).__name__, None, True
        finally:
            shutil.rmtree(d, ignore_errors=True)

    r0 = time.time()
    results = {}
    with ThreadPoolExecutor(max(1, args.jobs)) as ex:
        for cid, h, m, broke in ex.map(run_case, cases):
            results[cid] = (h, m, broke)
    subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], capture_output=True)
    ev["run_seconds"] = round(time.time() - r0, 1)
    ev["cases_failed_to_run"] = sum(1 for v in results.values() if v[2])

    # 7. verdicts against the frozen expectations
    buckets = {b: {"passed": 0, "total": 0, "weight": w} for b, w in WEIGHTS.items()}
    for cid, e in expected.items():
        got = results.get(cid)
        ok = bool(got and got[0] == e["h"])
        buckets[e["b"]]["total"] += 1
        buckets[e["b"]]["passed"] += int(ok)
        if "m" in e:
            buckets["schema_model"]["total"] += 1
            buckets["schema_model"]["passed"] += int(bool(got and got[1] == e["m"]))
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
