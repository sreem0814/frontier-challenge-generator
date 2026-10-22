"""Greedy pick of visible examples covering every feature of the hidden set: select_visible.py <pool> <hidden> <out> <n>"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.argv, args = sys.argv[:1], sys.argv[1:]
import importlib.util
spec = importlib.util.spec_from_file_location("cov", os.path.join(os.path.dirname(os.path.abspath(__file__)), "coverage.py"))
pool, hidden, out, n = args[0], args[1], args[2], int(args[3])
src = open(spec.origin).read().split("\nsets = sys.argv")[0]
ns = {}
exec(compile(src, spec.origin, "exec"), ns)
features = ns["features"]
names = sorted(f[:-4] for f in os.listdir(os.path.join(pool, "models")))
feats = {k: set(features(os.path.join(pool, "models", k + ".xml"))) for k in names}
want = set()
for f in os.listdir(os.path.join(hidden, "models")):
    want |= set(features(os.path.join(hidden, "models", f)))
need = {k: 2 for k in want}
chosen = []
while len(chosen) < n:
    best = max((k for k in names if k not in chosen),
               key=lambda k: (sum(1 for f in feats[k] if need.get(f, 0) > 0), len(feats[k])))
    chosen.append(best)
    for f in feats[best]:
        if f in need:
            need[f] -= 1
missing = sorted(f for f, c in need.items() if c > 0)
print("chosen", chosen)
print("features still under-covered (fewer than 2 models):", missing)
for sub in ("models", "states", "expected"):
    os.makedirs(os.path.join(out, sub), exist_ok=True)
for i, k in enumerate(sorted(chosen)):
    for sub, ext in (("models", ".xml"), ("states", ".json"), ("expected", ".json")):
        shutil.copy(os.path.join(pool, sub, k + ext), os.path.join(out, sub, f"{i:04d}{ext}"))
