"""score_local.py <flatc> <frozen dir>: score a flatc binary on a frozen split exactly as collect.py does
(without the uid drop and the build), for author checks such as core_share."""
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.environ.get("FBTESTS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                                               "harbor", "tests"))
import fbcase  # noqa: E402

WEIGHTS = {"schema_model": 0.06, "schema_bfbs": 0.08, "codegen": 0.14, "json_binary": 0.18, "json_text": 0.08,
           "diag": 0.20, "proto": 0.10, "bfbs_input": 0.08, "conform": 0.08}
flatc, fz = os.path.abspath(sys.argv[1]), sys.argv[2]
cases = json.load(open(os.path.join(fz, "cases.json")))
expected = json.load(open(os.path.join(fz, "expected.json")))


def run(case):
    d = tempfile.mkdtemp(prefix="sc-")
    try:
        fbcase.materialize(case["files"], d)
        rc, out, err = fbcase.run(flatc, case["argv"], d)
        t, outs = fbcase.transcript(case["b"], rc, out, err, d)
        m = fbcase.model_digest(rc, outs) if case["b"] == "schema_bfbs" else None
        return case["id"], fbcase.digest(t), m
    finally:
        shutil.rmtree(d, ignore_errors=True)


res = {}
with ThreadPoolExecutor(int(os.environ.get("JOBS", "4"))) as ex:
    for cid, h, m in ex.map(run, cases):
        res[cid] = (h, m)
b = {k: [0, 0] for k in WEIGHTS}
for cid, e in expected.items():
    g = res.get(cid)
    b[e["b"]][1] += 1
    b[e["b"]][0] += int(bool(g and g[0] == e["h"]))
    if "m" in e:
        b["schema_model"][1] += 1
        b["schema_model"][0] += int(bool(g and g[1] == e["m"]))
score = sum(WEIGHTS[k] * p / n for k, (p, n) in b.items() if n)
print(json.dumps({"score": round(score, 4), "buckets": {k: "%d/%d" % tuple(v) for k, v in b.items()}}))
