"""tests/collect.py: evidence only. Rebuilds the renderer from a clean copy of /app, runs it on the frozen
case set as an unprivileged user, compares every output with the frozen expected image and writes
evidence.json. compute_reward.py makes every scoring decision.

Every path writes evidence.json: a failed build is evidence too. Candidate code (the cargo build and every
render) runs as --uid in its own session with a timeout; its processes are killed by uid afterwards.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # imgcmp lives beside this file (never imported from /app)
import imgcmp  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app")
ap.add_argument("--jobs", type=int, default=4)
args = ap.parse_args()

BUILD_TIMEOUT = 1800          # seconds for `cargo build --release --offline`
CASE_TIMEOUT = 30             # seconds per render
CASE_MEM = 4 << 30            # address-space limit per render
OUT_MAX = 64 << 20            # largest accepted output file
APP_MAX = 2 << 30             # largest workspace copied for the build
SKIP_TOP = {"target", ".git", ".timer"}

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "build_seconds": 0.0, "build_log_tail": "",
    "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "cases_rendered": 0, "buckets": {},
    "leftover_processes": 0, "failures": [], "render_seconds": 0.0,
}


def write():
    with open(args.out, "w") as f:
        json.dump(ev, f)


def kill_uid(uid):
    """Kill every process of the candidate uid; return how many were alive."""
    pids = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            st = os.stat(f"/proc/{d}")
        except OSError:
            continue
        if st.st_uid == uid:
            pids.append(int(d))
    for p in pids:
        try:
            os.kill(p, signal.SIGKILL)
        except OSError:
            pass
    return len(pids)


LIMITS = f"ulimit -c 0; ulimit -v {CASE_MEM // 1024} 2>/dev/null; ulimit -f {OUT_MAX // 1024} 2>/dev/null; "


def run_candidate(cmd, cwd, env, timeout, limit_mem=False):
    """Run cmd as the candidate uid in a new session (no preexec_fn: the grader is multi-threaded)."""
    wrapped = ["/bin/bash", "-c", (LIMITS if limit_mem else "ulimit -c 0; ") + 'exec "$0" "$@"'] + list(cmd)
    p = subprocess.Popen(wrapped, cwd=cwd, env=env, user=args.uid, group=args.uid, extra_groups=[],
                         start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        return None, out


def copy_workspace(src, dst):
    total = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        if rel == ".":
            dirs[:] = [d for d in dirs if d not in SKIP_TOP]
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
        if total > APP_MAX:
            raise ValueError("workspace larger than 2 GiB")
    shutil.copytree(src, dst, symlinks=True, ignore=lambda d, names: SKIP_TOP if os.path.samefile(d, src) else [])


def chown_tree(path, uid):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            os.lchown(os.path.join(root, n), uid, uid)
    os.lchown(path, uid, uid)


def load_cases():
    rows = []
    with open(os.path.join(HERE, "data", "cases.tsv")) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cid, bucket, width, source = line.rstrip("\n").split("\t")
            rows.append((cid, bucket, int(width), source))
    return rows


def main():
    cases = load_cases()
    ev["cases_total"] = len(cases)
    buckets = {}
    for _, b, _, _ in cases:
        buckets.setdefault(b, {"passed": 0, "total": 0})["total"] += 1
    ev["buckets"] = buckets

    # Work area: root-owned and private, with candidate-owned subdirectories.
    work = tempfile.mkdtemp(prefix="svgr-grade-", dir="/tmp")
    os.chmod(work, 0o711)
    try:
        # 1. Build gate: clean copy of the workspace, rebuilt offline as the candidate uid.
        build_root = os.path.join(work, "build")
        os.mkdir(build_root)
        src = os.path.join(build_root, "src")
        try:
            copy_workspace(args.app, src)
        except Exception as e:
            ev["gate_reason"] = f"build failed: cannot copy {args.app}: {type(e).__name__}: {e}"
            return
        home = os.path.join(build_root, "home")
        os.mkdir(home)
        os.mkdir(os.path.join(home, ".cargo"))
        chown_tree(build_root, args.uid)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "CARGO_HOME": os.path.join(home, ".cargo"),
            "CARGO_TARGET_DIR": os.path.join(src, "target"), "CARGO_NET_OFFLINE": "true", "LANG": "C.UTF-8",
            "TMPDIR": home,
        }
        t0 = time.monotonic()
        rc, out = run_candidate(["cargo", "build", "--release", "--offline"], src, env, BUILD_TIMEOUT)
        ev["build_seconds"] = round(time.monotonic() - t0, 1)
        ev["build_log_tail"] = out.decode("utf-8", "replace")[-3000:]
        kill_uid(args.uid)
        binary = os.path.join(src, "target", "release", "svgrender")
        if rc is None:
            ev["gate_reason"] = f"build failed: cargo build did not finish within {BUILD_TIMEOUT} s"
            return
        if rc != 0:
            ev["gate_reason"] = f"build failed: cargo build exited with status {rc}"
            return
        if not os.path.isfile(binary) or os.path.islink(binary):
            ev["gate_reason"] = "build failed: target/release/svgrender was not produced"
            return
        bindir = os.path.join(work, "bin")
        os.mkdir(bindir, 0o755)
        exe = os.path.join(bindir, "svgrender")
        shutil.copyfile(binary, exe)
        os.chmod(exe, 0o755)
        ev["build_ok"] = True

        # 2. Cases: fixed denominator; a crash, timeout, missing or unreadable output fails the case.
        runs = os.path.join(work, "runs")
        os.mkdir(runs, 0o755)

        def one(case):
            cid, bucket, width, source = case
            d = os.path.join(runs, cid)
            os.mkdir(d)
            shutil.copyfile(os.path.join(HERE, "data", "svg", cid + ".svg"), os.path.join(d, "in.svg"))
            chown_tree(d, args.uid)
            run_env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": d, "TMPDIR": d, "LANG": "C.UTF-8"}
            rc, out = run_candidate([exe, "--width", str(width), "in.svg", "out.png"], d, run_env,
                                    CASE_TIMEOUT, limit_mem=True)
            res = {"id": cid, "source": source, "bucket": bucket, "passed": False}
            outp = os.path.join(d, "out.png")
            if rc is None:
                res["why"] = f"timeout after {CASE_TIMEOUT} s"
            elif rc != 0:
                res["why"] = f"exit status {rc}"
            elif os.path.islink(outp) or not os.path.isfile(outp):
                res["why"] = "no out.png"
            elif os.stat(outp).st_uid != args.uid or os.stat(outp).st_nlink != 1:
                res["why"] = "out.png is not a file the renderer wrote"
            elif os.path.getsize(outp) > OUT_MAX:
                res["why"] = "out.png too large"
            else:
                with open(outp, "rb") as f:
                    cand = f.read()
                with open(os.path.join(HERE, "data", "expected", cid + ".png"), "rb") as f:
                    exp = f.read()
                res["rendered"] = True
                ok, off, msg = imgcmp.compare_png_bytes(exp, cand)
                res["passed"], res["why"] = ok, msg
            shutil.rmtree(d, ignore_errors=True)
            return res

        t0 = time.monotonic()
        with ThreadPoolExecutor(max(1, args.jobs)) as pool:
            results = list(pool.map(one, cases))
        ev["render_seconds"] = round(time.monotonic() - t0, 1)
        ev["leftover_processes"] = kill_uid(args.uid)
        for r in results:
            if r.get("rendered"):
                ev["cases_rendered"] += 1
            if r["passed"]:
                ev["cases_passed"] += 1
                buckets[r["bucket"]]["passed"] += 1
            else:
                ev["failures"].append(f'{r["id"]} {r["source"]}: {r["why"]}')
        # 3. Anti-cheat: the renderer must not leave processes behind.
        if ev["leftover_processes"]:
            ev["cheat_detected"] = True
            ev["gate_reason"] = (f"{ev['leftover_processes']} renderer process(es) still running after the renders "
                                 "finished")
    finally:
        kill_uid(args.uid)
        shutil.rmtree(work, ignore_errors=True)


try:
    if os.geteuid() != 0:
        raise RuntimeError("the grader must run as root")
    main()
except Exception as e:  # an exception in our own code is a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    ev["failures"] = ev["failures"][:200]
    write()
sys.exit(0)
