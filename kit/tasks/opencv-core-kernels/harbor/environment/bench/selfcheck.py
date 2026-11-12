#!/usr/bin/env python3
"""selfcheck.py: correctness and speed of your opencv_core against the shipped build.

    python3 /app/bench/selfcheck.py                 build, check, time every case, estimate the score
    python3 /app/bench/selfcheck.py --no-build      reuse /app/bench/bin/cvbench
    python3 /app/bench/selfcheck.py --only add_8uC1,sum_8uC1 --reps 5
    python3 /app/bench/selfcheck.py --check-only    correctness only (seconds)

The shipped build is /app/bench/bin/cvbench-base (the untouched sources, built when the image was made).
Correctness: the randomized check suite with a fresh seed, compared record by record within each record's
tolerance. Timing: the same interleaved, externally timed batches as the real measurement, with the shipped
build as the baseline. The reachable speedups S_k come from targets.json (measured on another machine with an
optimized build of the same sources); the real run measures them again on its own CPU, so treat the estimate
as a guide, not a promise.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import perf  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--no-build", action="store_true")
ap.add_argument("--check-only", action="store_true")
ap.add_argument("--skip-check", action="store_true")
ap.add_argument("--only", default="", help="comma-separated case ids to time")
ap.add_argument("--reps", type=int, default=9)
ap.add_argument("--seed", type=int, default=None)
a = ap.parse_args()

base = os.path.join(HERE, "bin", "cvbench-base")
cand = os.path.join(HERE, "bin", "cvbench")
targets = json.load(open(os.path.join(HERE, "targets.json")))
cfg_cases = {c["id"]: c for c in targets["cases"]}
d = float(targets["noise_margin"])

if not a.no_build:
    r = subprocess.run(["bash", os.path.join(HERE, "build.sh")])
    if r.returncode:
        print("BUILD FAILED: the score would be 0")
        sys.exit(1)

rng = random.Random(a.seed if a.seed is not None else int.from_bytes(os.urandom(8), "little"))
work = os.path.join(HERE, "work")
os.makedirs(work, exist_ok=True)

if not a.skip_check:
    seed = rng.getrandbits(63)
    pb, pc = os.path.join(work, "base.bin"), os.path.join(work, "cand.bin")
    subprocess.run([base, "check", str(seed), pb], check=True, stderr=subprocess.DEVNULL)
    r = subprocess.run([cand, "check", str(seed), pc], stderr=subprocess.DEVNULL)
    if r.returncode:
        print(f"CHECK RUN FAILED (exit {r.returncode}): the score would be 0")
        sys.exit(1)
    out = subprocess.run([base, "cmp", pb, pc], capture_output=True, text=True).stdout.splitlines()
    tot = [ln for ln in out if ln.startswith("TOTAL ")][0].split()
    bad = [ln for ln in out if len(ln.split()) == 5 and ln.split()[1] == "0"]
    print(f"check: {int(tot[1]) - int(tot[2])}/{tot[1]} records match (seed {seed})")
    for ln in bad[:30]:
        p = ln.split()
        print(f"  DIFFERS {p[0]}  n={p[2]} max_abs={p[3]} max_rel={p[4]}")
    for p in (pb, pc):
        os.unlink(p)
    if bad:
        print("CORRECTNESS GATE FAILS: the score would be 0")
    if a.check_only:
        sys.exit(1 if bad else 0)

servers = {"base": perf.Server("base", base, work), "cand": perf.Server("cand", cand, work)}
cases = [c for c in perf.list_cases(base) if c["id"] in cfg_cases]
only = set(x for x in a.only.split(",") if x)


def log(r):
    s = r["ratio"].get("cand", 0.0)
    S = cfg_cases[r["id"]]["S"]
    flag = "" if r["ok"] else "  FAIL: " + r["why"]
    print(f"{r['id']:24s} {r['family']:10s} speedup {s:6.2f}x   reachable ~{S:5.2f}x{flag}", flush=True)


try:
    res = perf.measure(servers, cases, a.reps, targets["batch_seconds"], rng, base,
                       {"base": work, "cand": work}, log=log, case_filter=only, ref="base", cand="cand")
finally:
    for s in servers.values():
        s.close()

if only:
    sys.exit(0)
fams = {}
for c in cfg_cases.values():
    fams.setdefault(c["family"], []).append(c["id"])
w = {cid: 1.0 / (len(fams) * len(ids)) for ids in fams.values() for cid in ids}
got = {r["id"]: r for r in res}
if any(not r["ok"] for r in res) or set(got) != set(w):
    print("TIMING GATE FAILS: the score would be 0")
    sys.exit(1)
ln_s = sum(w[k] * math.log(min(got[k]["ratio"]["cand"], max(cfg_cases[k]["S"], 1.0))) for k in w)
ln_S = sum(w[k] * math.log(cfg_cases[k]["S"]) for k in w)
s, S = math.exp(ln_s), math.exp(ln_S)
u = min(1.0, max(0.0, (s - 1 - d) / (S - 1 - d)))
print(f"\nweighted speedup {s:.3f}x of ~{S:.3f}x  ->  u = {u:.3f}, estimated score 2^u - 1 = {2 ** u - 1:.3f}")
