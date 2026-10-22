"""tests/collect.py: evidence only. Snapshots the package, runs the gates and the hidden cases, writes evidence.json.

Every path writes evidence.json. Candidate code runs as an unprivileged uid in its own process group, one
process per hidden model, with a wall-clock limit per model. Case pass/fail is decided by compare.py on
outputs the candidate wrote; compute_reward.py turns the evidence into the reward.
"""
import argparse
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

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app")
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--timeout", type=float, default=240.0)
ap.add_argument("--tamper", default="", help="file with dpkg --verify findings for the interpreter packages")
ap.add_argument("--sweep", default="{}", help="JSON line from sweep.py: session leftovers that were stopped")
args = ap.parse_args()

PKG = os.path.join(args.app, "mjlite")
DATA = os.path.join(HERE, "data")
NATIVE = (".so", ".pyd", ".dll", ".dylib", ".o", ".a")

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
    "models_total": 0, "models_loaded": 0, "models_timed_out": 0,
    "expected_sealed": None, "tamper": [], "wall_s": 0.0, "leftovers_stopped": [],
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


def as_candidate(cmd, timeout, env):
    p = subprocess.Popen(cmd, preexec_fn=drop_privileges, stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE, env=env, cwd="/tmp")
    try:
        _, err = p.communicate(timeout=timeout)
        return p.returncode, err[-4000:]
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.communicate()
        return None, b"timeout"


try:
    try:
        ev["leftovers_stopped"] = json.loads(args.sweep).get("stopped", [])
    except ValueError:
        ev["leftovers_stopped"] = []

    # 1. tamper evidence: the verifier's own interpreter must be the packaged one (test.sh ran dpkg --verify)
    if args.tamper and os.path.isfile(args.tamper):
        with open(args.tamper) as f:
            ev["tamper"] = [ln.strip() for ln in f if ln.strip()][:10]
    if ev["tamper"]:
        gate("system Python files were modified: " + "; ".join(ev["tamper"][:3]), cheat=True)

    # 2. build gate: the package exists, is plain Python source, and has no links out of it
    if not os.path.isfile(os.path.join(PKG, "__init__.py")) or os.path.islink(PKG):
        gate("no package at /app/mjlite (missing __init__.py)")
    work = tempfile.mkdtemp(prefix="grade-")
    os.chmod(work, 0o711)
    for root, dirs, files in os.walk(PKG):
        for n in dirs + files:
            p = os.path.join(root, n)
            if os.path.islink(p):
                gate(f"symbolic link inside the package: {os.path.relpath(p, args.app)}", cheat=True)
            if n.endswith(NATIVE):
                gate(f"compiled or native file inside the package: {os.path.relpath(p, args.app)}", cheat=True)
    dst = os.path.join(work, "pkg", "mjlite")
    shutil.copytree(PKG, dst, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for root, dirs, files in os.walk(os.path.join(work, "pkg")):
        os.chmod(root, 0o755)
        for n in files:
            os.chmod(os.path.join(root, n), 0o644)
    ev["build_ok"] = True

    # 3. inputs for the candidate (models and states only), outputs dir owned by the candidate
    inp = os.path.join(work, "inputs")
    shutil.copytree(os.path.join(DATA, "models"), os.path.join(inp, "models"))
    shutil.copytree(os.path.join(DATA, "states"), os.path.join(inp, "states"))
    for root, dirs, files in os.walk(inp):
        os.chmod(root, 0o755)
        for n in files:
            os.chmod(os.path.join(root, n), 0o644)
    shutil.copy(os.path.join(HERE, "driver.py"), os.path.join(work, "driver.py"))
    os.chmod(os.path.join(work, "driver.py"), 0o644)
    outdir = os.path.join(work, "out")
    os.mkdir(outdir)
    os.chown(outdir, args.uid, args.uid)
    home = os.path.join(work, "home")
    os.mkdir(home)
    os.chown(home, args.uid, args.uid)

    # 4. sealing evidence: the candidate uid must not be able to read the reference outputs
    probe = subprocess.run(["setpriv", f"--reuid={args.uid}", f"--regid={args.uid}", "--clear-groups",
                            "test", "-r", os.path.join(DATA, "expected", "0000.json")])
    ev["expected_sealed"] = probe.returncode != 0

    names = sorted(f[:-4] for f in os.listdir(os.path.join(DATA, "models")) if f.endswith(".xml"))
    ev["models_total"] = len(names)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8",
           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}

    def run(name):
        out = os.path.join(outdir, name + ".json")
        rc, err = as_candidate([sys.executable, "-I", os.path.join(work, "driver.py"), os.path.join(work, "pkg"),
                                os.path.join(inp, "models", name + ".xml"),
                                os.path.join(inp, "states", name + ".json"), out], args.timeout, env)
        return name, rc

    timed_out = 0
    with ThreadPoolExecutor(args.jobs) as ex:
        for name, rc in ex.map(run, names):
            timed_out += rc is None
    ev["models_timed_out"] = timed_out
    subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], capture_output=True)

    # 5. score every case against the frozen reference outputs (fixed denominator)
    import compare
    buckets = {}
    loaded = 0
    for name in names:
        with open(os.path.join(DATA, "expected", name + ".json")) as f:
            exp = json.load(f)
        got = None
        p = os.path.join(outdir, name + ".json")
        if os.path.isfile(p) and not os.path.islink(p) and os.path.getsize(p) < 64 * 2**20:
            try:
                with open(p) as f:
                    got = json.load(f)
            except (ValueError, UnicodeDecodeError, RecursionError, MemoryError):
                got = None
        if not isinstance(got, dict):
            got = None
        if got and isinstance(got.get("compile"), dict):
            loaded += 1
        for bucket, ok in compare.grade_model(exp, got):
            b = buckets.setdefault(bucket, {"passed": 0, "total": 0, "weight": compare.WEIGHTS[bucket]})
            b["total"] += 1
            b["passed"] += int(bool(ok))
    ev["models_loaded"] = loaded
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
