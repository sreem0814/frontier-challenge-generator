"""Author-side check: run a candidate package over a generated set and report per-bucket results.

python3 -I devcheck.py <pkg parent> <set dir> [--py python3] [--jobs 4] [--detail] [--only 0003]
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(HERE, "..", "harbor", "tests")
sys.path.insert(0, TESTS)
import compare  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("pkg")
ap.add_argument("setdir")
ap.add_argument("--py", default="python3")
ap.add_argument("--jobs", type=int, default=4)
ap.add_argument("--detail", action="store_true")
ap.add_argument("--only", default="")
args = ap.parse_args()

names = sorted(f[:-4] for f in os.listdir(os.path.join(args.setdir, "models")) if f.endswith(".xml"))
if args.only:
    names = [n for n in names if n in args.only.split(",")]
tmp = tempfile.mkdtemp()


def run(n):
    out = os.path.join(tmp, n + ".json")
    p = subprocess.run([args.py, "-I", os.path.join(TESTS, "driver.py"), os.path.abspath(args.pkg),
                        os.path.join(args.setdir, "models", n + ".xml"),
                        os.path.join(args.setdir, "states", n + ".json"), out],
                       capture_output=True, text=True, timeout=600)
    got = json.load(open(out)) if os.path.exists(out) else None
    return n, got, p.stderr


def maxerr(g, e):
    if not isinstance(g, list) or len(g) != len(e):
        return "shape"
    scale = max((abs(x) for x in e), default=0.0)
    w = 0.0
    for x, y in zip(g, e):
        tol = compare.RTOL * abs(y) + compare.ATOL_REL * scale + compare.ATOL
        w = max(w, abs(x - y) / tol)
    return w


tot, ok = {}, {}
worst = {}
with ThreadPoolExecutor(args.jobs) as ex:
    for n, got, stderr in ex.map(run, names):
        exp = json.load(open(os.path.join(args.setdir, "expected", n + ".json")))
        res = compare.grade_model(exp, got)
        bad = sorted({b for b, p in res if not p})
        for b, p in res:
            tot[b] = tot.get(b, 0) + 1
            ok[b] = ok.get(b, 0) + int(p)
        if got and got.get("compile"):
            for k in ("body_pos", "jnt_pos", "jnt_axis", "body_mass", "body_ipos", "dof_armature", "dof_damping"):
                r = maxerr(got["compile"].get(k), exp["compile"][k])
                if r != "shape":
                    worst[k] = max(worst.get(k, 0), r)
            for s, es in enumerate(exp["states"]):
                if s < len(got["states"]):
                    for k, v in es.items():
                        if k in ("step_qpos",):
                            continue
                        r = maxerr(got["states"][s].get(k), v)
                        if r != "shape":
                            worst[k] = max(worst.get(k, 0), r)
        if bad:
            print(n, "FAIL", bad, (got or {}).get("compile_error", "")[-300:])
            if args.detail and got and got.get("compile"):
                for k in ("body_pos", "body_quat", "jnt_pos", "jnt_axis", "body_mass", "body_ipos", "qpos0",
                          "qpos_spring", "dof_armature", "dof_damping", "jnt_stiffness"):
                    r = maxerr(got["compile"].get(k), exp["compile"][k])
                    if r == "shape" or r > 1:
                        print("   compile", k, r)
                for s, es in enumerate(exp["states"][:1]):
                    gs = got["states"][s] if s < len(got["states"]) else {}
                    if gs.get("errors"):
                        print("   errors", gs["errors"][0][-400:])
                    for k, v in es.items():
                        r = maxerr(gs.get(k), v)
                        if r == "shape" or r > 1:
                            print("   state0", k, r)
            if stderr.strip() and args.detail:
                print("   stderr:", stderr.strip()[-300:])
w = sum(compare.WEIGHTS[b] for b in tot)
score = sum(compare.WEIGHTS[b] * ok[b] / tot[b] for b in tot) / w
for b in compare.WEIGHTS:
    if b in tot:
        print(f"  {b:13s} {ok[b]:5d}/{tot[b]:5d}")
print(f"score {score:.4f}")
print("worst error/tol:", {k: round(v, 4) for k, v in sorted(worst.items(), key=lambda x: -x[1])[:12]})
