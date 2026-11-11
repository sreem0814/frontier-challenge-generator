"""finalize.py <frozen hidden dir> <frozen sample dir> <task harbor dir>: drop hidden cases whose input files
also appear in a visible sample, then install the hidden set under tests/data and the samples (plus copies of
the transcript code) under environment/app/check."""
import hashlib
import json
import os
import shutil
import sys

hid, sam, harbor = sys.argv[1:4]


def fkey(c):
    return hashlib.sha256(json.dumps(sorted(c["files"].items())).encode()).hexdigest()


hc = json.load(open(os.path.join(hid, "cases.json")))
he = json.load(open(os.path.join(hid, "expected.json")))
sc = json.load(open(os.path.join(sam, "cases.json")))
BAD = {"tests", "solution", "test.sh", "compute_reward.py"}   # path parts the bundle leak check refuses


def bad_sample(cid):
    for root, dirs, files in os.walk(os.path.join(sam, "samples", cid)):
        if BAD & set(dirs + files):
            return True
    return False


drop = {c["id"] for c in sc if bad_sample(c["id"])}
sc = [c for c in sc if c["id"] not in drop]
seen = {fkey(c) for c in sc}
keep = [c for c in hc if fkey(c) not in seen]
exp = {c["id"]: he[c["id"]] for c in keep}
data = os.path.join(harbor, "tests", "data")
os.makedirs(data, exist_ok=True)
with open(os.path.join(data, "cases.json"), "w") as f:
    json.dump(keep, f, separators=(",", ":"))
with open(os.path.join(data, "expected.json"), "w") as f:
    json.dump(exp, f, separators=(",", ":"), sort_keys=True)
chk = os.path.join(harbor, "environment", "app", "check")
shutil.rmtree(os.path.join(chk, "samples"), ignore_errors=True)
shutil.copytree(os.path.join(sam, "samples"), os.path.join(chk, "samples"),
                ignore=lambda d, names: [n for n in names if n in drop])
for n in ("fbcase.py", "bfbsdec.py"):
    shutil.copy(os.path.join(harbor, "tests", n), os.path.join(chk, n))
counts = {}
for e in exp.values():
    counts[e["b"]] = counts.get(e["b"], 0) + 1
print(json.dumps({"hidden": len(keep), "dropped_overlap": len(hc) - len(keep), "buckets": counts,
                  "samples": len(sc), "samples_dropped": sorted(drop)}))
