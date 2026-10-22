#!/usr/bin/env python3
"""Score /app/mjlite on the visible examples the same way the hidden set is scored.

    python3 /app/tools/selfcheck.py                 # all examples, 4 parallel jobs
    python3 /app/tools/selfcheck.py -j 8 -v         # more jobs, list every failing case
    python3 /app/tools/selfcheck.py --only 0003     # one example

Each example runs in its own `python3 -I` process through tools/run_model.py (the same harness the
grader uses), with a 240 s limit per model. The printed score uses the same buckets, weights and
tolerances as the final grading, so it estimates the hidden-set score; the hidden models are
different random models drawn from the same feature mix.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cases  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--pkg", default="/app/mjlite", help="package directory to test")
ap.add_argument("--examples", default="/app/examples")
ap.add_argument("-j", "--jobs", type=int, default=4)
ap.add_argument("-v", "--verbose", action="store_true")
ap.add_argument("--only", default="")
args = ap.parse_args()

# Hard gates (any failure scores 0 in grading): plain-source package, unmodified system Python.
gate_problems = []
if not os.path.isfile(os.path.join(args.pkg, "__init__.py")):
    gate_problems.append(f"{args.pkg}/__init__.py is missing")
for root, dirs, files in os.walk(args.pkg):
    for n in dirs + files:
        p = os.path.join(root, n)
        if os.path.islink(p):
            gate_problems.append(f"symbolic link in the package: {p}")
        if n.endswith((".so", ".pyd", ".dll", ".dylib", ".o", ".a")):
            gate_problems.append(f"compiled or native file in the package: {p}")
for deb in ("python3.11-minimal", "libpython3.11-minimal", "libpython3.11-stdlib"):
    try:
        r = subprocess.run(["dpkg", "--verify", deb], capture_output=True, text=True)
        for ln in r.stdout.splitlines():
            if ln.strip() and " c " not in ln[:12] and not re.search(r" /usr/share/(doc|man|lintian|locale|info)/", ln):
                gate_problems.append(f"system Python file modified ({deb}): {ln.strip()}")
    except OSError:
        pass
print("gates: " + ("ok" if not gate_problems else "FAIL"))
for g in gate_problems:
    print("   " + g)

work = tempfile.mkdtemp(prefix="selfcheck-")
shutil.copytree(args.pkg, os.path.join(work, "pkg", "mjlite"), symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
names = sorted(f[:-4] for f in os.listdir(os.path.join(args.examples, "models")) if f.endswith(".xml"))
if args.only:
    names = [n for n in names if n in args.only.split(",")]


def run(name):
    out = os.path.join(work, name + ".json")
    cmd = [sys.executable, "-I", os.path.join(HERE, "run_model.py"), os.path.join(work, "pkg"),
           os.path.join(args.examples, "models", name + ".xml"),
           os.path.join(args.examples, "states", name + ".json"), out]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        log = p.stderr
    except subprocess.TimeoutExpired:
        log = "timeout after 240 s"
    got = None
    if os.path.exists(out):
        try:
            with open(out) as f:
                got = json.load(f)
        except ValueError:
            got = None
    return name, got, log


total, passed = {}, {}
with ThreadPoolExecutor(args.jobs) as ex:
    for name, got, log in ex.map(run, names):
        with open(os.path.join(args.examples, "expected", name + ".json")) as f:
            exp = json.load(f)
        res = cases.grade_model(exp, got)
        bad = []
        for bucket, ok in res:
            total[bucket] = total.get(bucket, 0) + 1
            passed[bucket] = passed.get(bucket, 0) + int(ok)
            if not ok:
                bad.append(bucket)
        status = "ok" if not bad else "FAIL " + ",".join(sorted(set(bad)))
        print(f"{name}: {sum(ok for _, ok in res)}/{len(res)} cases  {status}")
        if args.verbose and bad:
            err = (got or {}).get("compile_error") or ""
            errs = [e for s in (got or {}).get("states", []) for e in s.get("errors", [])]
            msg = (err or (errs[0] if errs else "") or log).strip()
            if msg:
                print("    " + msg.splitlines()[-1][:300])

print()
wsum = sum(cases.WEIGHTS[b] for b in total)
score = sum(cases.WEIGHTS[b] * passed[b] / total[b] for b in total) / wsum if wsum else 0.0
for b in cases.WEIGHTS:
    if b in total:
        print(f"  {b:13s} {passed[b]:4d}/{total[b]:4d}   weight {cases.WEIGHTS[b]}")
if gate_problems:
    print(f"estimated score 0.0000 (a hard gate fails; the cases alone would give {score:.4f})")
else:
    print(f"estimated score {score:.4f}")
shutil.rmtree(work, ignore_errors=True)
