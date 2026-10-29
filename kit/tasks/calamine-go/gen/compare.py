"""compare.py: run a candidate xlsdump over workbooks and compare with expected JSON dumps.

usage: python3 -I compare.py <xlsdump> <workbook dir> <expected dir> [--show N] [--only substr] [-j N]
"""
import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import units as U  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("bin")
ap.add_argument("wbdir")
ap.add_argument("expdir")
ap.add_argument("--show", type=int, default=30)
ap.add_argument("--only", default="")
ap.add_argument("-j", type=int, default=4)
ap.add_argument("--timeout", type=float, default=60)
a = ap.parse_args()

files = sorted(f[:-5] for f in os.listdir(a.expdir) if f.endswith(".json") and a.only in f)


def run(name):
    exp = json.load(open(os.path.join(a.expdir, name + ".json")))
    us = U.units(exp)
    if not us:
        return name, exp.get("format") or name.rsplit(".", 1)[-1], [], None
    try:
        p = subprocess.run([a.bin, os.path.join(a.wbdir, name)], capture_output=True, timeout=a.timeout)
        cand = json.loads(p.stdout.decode("utf-8", "replace"))
    except Exception as e:
        cand = {"_err": str(e)[:200]}
    res = [(U.bucket(uid, exp.get("format")), uid, U.unit_ok(uid, pl, cand, exp)) for uid, pl in us]
    return name, exp.get("format"), res, cand


stats = {}
fails = []
with ThreadPoolExecutor(a.j) as ex:
    for name, fmt, res, cand in ex.map(run, files):
        if not res:
            continue
        for b in sorted(set(b for b, _, _ in res)):
            rb = [r for bb, _, r in res if bb == b]
            st = stats.setdefault(b, [0, 0, 0, 0.0])
            ok = sum(1 for r in rb if r)
            st[0] += ok
            st[1] += len(rb)
            st[2] += 1
            st[3] += ok / len(rb)
        for _, uid, r in res:
            if not r:
                fails.append((name, uid, (cand or {}).get("_err") or (cand or {}).get("detail", "")))

for fmt, (ok, tot, nf, fs) in sorted(stats.items()):
    print(f"{fmt:8s} units {ok}/{tot}  files {nf}  mean file score {fs / nf:.4f}")
print(f"failing units: {len(fails)}")
for f in fails[: a.show]:
    print("  FAIL", *f)
