"""tests/collect.py: evidence only. Builds the deliverable, runs the gates and the cases, writes evidence.json.

Every path writes evidence.json: a failed build is evidence too. No scoring decisions here; compute_reward.py
makes them. Candidate code runs as an unprivileged uid in its own process group, with a timeout per case.
"""
import argparse
import json
import os
import signal
import subprocess
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
args = ap.parse_args()

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
}


def write():
    with open(args.out, "w") as f:
        json.dump(ev, f)


def drop_privileges():
    os.setsid()
    os.setgid(args.uid)
    os.setuid(args.uid)


def run_candidate(cmd, timeout, **kw):
    """Run one candidate command as args.uid; kill its whole process group on timeout."""
    p = subprocess.Popen(cmd, preexec_fn=drop_privileges, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        return None, b"", b"timeout"


try:
    # 1. Runtime check: set runtime_ok False only when the harness itself failed (not for a wrong answer).
    # 2. Build gate: rebuild the deliverable from source, offline, in a clean copy: a pristine snapshot of the base
    #    plus the agent's diff (git diff --binary <base> HEAD), so edited tests, fixtures or caches cannot help.
    #    Set build_ok.
    # 3. Anti-cheat: set cheat_detected and gate_reason (e.g. embedded binaries, forbidden symbols, tampered inputs).
    #    Record tamper signals (edited test infrastructure, vendored deps, a new TestMain or test hook) as evidence.
    # 3b. Regression gate: the project's existing test suite must still pass (pass-to-pass); record its pass rate.
    # 4. Cases: fixed denominator. A crash, timeout or missing output counts as a failure.
    #    Fill cases_total, cases_passed and buckets = {"name": {"passed": n, "total": m, "weight": w}}.
    raise NotImplementedError("fill in collect.py for this task")
except NotImplementedError:
    raise
except Exception as e:  # an exception in our own code is a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    write()
sys.exit(0)
