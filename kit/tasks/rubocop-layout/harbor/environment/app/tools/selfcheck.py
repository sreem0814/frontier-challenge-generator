#!/usr/bin/env python3
"""selfcheck.py: score /app/rubocop on the sample cases with the same driver and formula as the final grading.

  python3 /app/tools/selfcheck.py                 # all samples, 8 processes
  python3 /app/tools/selfcheck.py --cop Layout/HashAlignment --show 3
  python3 /app/tools/selfcheck.py --kind dept --show 1

Cop unit: 0.5 for the exact offense ranges of that cop, +0.5 when the autocorrected source is also exact.
Dept unit: 1 when the source after all default-enabled Layout cops autocorrect together is exact.
Estimate = 0.9 * cop points / cop units + 0.1 * dept passes / dept units.
Unlike the final grading this runs your working tree directly (not a clean copy of lib/) as your own user.
"""
import argparse
import difflib
import gzip
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--tree", default="/app/rubocop")
ap.add_argument("--cases", default=os.path.join(HERE, "..", "samples", "cases.jsonl.gz"))
ap.add_argument("--cop", action="append", help="only cases for this cop (repeatable)")
ap.add_argument("--kind", choices=["spec", "vary", "corpus", "dept"])
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--show", type=int, default=0, help="print this many failing cases per cop")
ap.add_argument("--json", help="write per-case results here")
a = ap.parse_args()

cases = [json.loads(l) for l in gzip.open(a.cases)]
if a.cop:
    cases = [c for c in cases if c["kind"] != "dept" and c["cops"][0] in a.cop]
if a.kind:
    cases = [c for c in cases if c["kind"] == a.kind]
if not cases:
    sys.exit("no cases selected")
KEYS = ("id", "cops", "config", "source", "path", "ruby", "engine", "defaults")


def run(shard):
    inp = "".join(json.dumps({k: c[k] for k in KEYS}) + "\n" for c in shard)
    p = subprocess.run(["bundle", "exec", "ruby", os.path.join(HERE, "layout_probe.rb")], input=inp,
                       capture_output=True, text=True, cwd=a.tree)
    out = {}
    for l in p.stdout.splitlines():
        try:
            r = json.loads(l)
            out[r["id"]] = r
        except ValueError:
            pass
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-2000:])
    return out


shards = [cases[i::a.jobs] for i in range(a.jobs)]
res = {}
with ThreadPoolExecutor(a.jobs) as ex:
    for part in ex.map(run, shards):
        res.update(part)


def score(c, r):
    if not r or r.get("error"):
        return 0.0
    if c["kind"] == "dept":
        return 1.0 if r.get("corrected") == c["expected"]["corrected"] else 0.0
    if (r.get("offenses") or {}).get(c["cops"][0], []) != c["expected"]["offenses"]:
        return 0.0
    return 1.0 if r.get("corrected") == c["expected"]["corrected"] else 0.5


per, shown = {}, {}
cop_pts = cop_n = dept_ok = dept_n = 0
for c in cases:
    r = res.get(c["id"])
    s = score(c, r)
    key = "(dept)" if c["kind"] == "dept" else c["cops"][0]
    p = per.setdefault(key, [0.0, 0])
    p[0] += s
    p[1] += 1
    if c["kind"] == "dept":
        dept_n += 1
        dept_ok += s == 1.0
    else:
        cop_n += 1
        cop_pts += s
    if s < 1.0 and shown.get(key, 0) < a.show:
        shown[key] = shown.get(key, 0) + 1
        print(f"=== {c['id']} {key} score {s}")
        print("config:", json.dumps({k: v for k, v in c["config"].items() if k != "AllCops"})[:600])
        if r and r.get("error"):
            print("error:", r["error"])
        if c["kind"] != "dept":
            got = ((r or {}).get("offenses") or {}).get(c["cops"][0], [])
            print("expected offenses [line, col, last_line, last_col]:", c["expected"]["offenses"])
            print("your offenses:                                     ", got)
        exp, got = c["expected"]["corrected"], (r or {}).get("corrected") or ""
        if exp != got:
            print("".join(difflib.unified_diff(got.splitlines(True), exp.splitlines(True), "yours", "expected", n=2))[:3000])
for k in sorted(per):
    print(f"{per[k][0] / per[k][1]:6.3f}  {per[k][0]:7.1f}/{per[k][1]:<5d} {k}")
est = 0.9 * (cop_pts / cop_n if cop_n else 0) + 0.1 * (dept_ok / dept_n if dept_n else 0)
print(f"cop units {cop_pts:.1f}/{cop_n}  dept {dept_ok}/{dept_n}  estimate {est:.4f}")
if a.json:
    json.dump(res, open(a.json, "w"))
