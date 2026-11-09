"""gen/build_set.py: candidates + results of every build -> the frozen case set.

usage: python3 -I build_set.py <tests dir> <cand.jsonl.gz> <results dir> <out.jsonl.gz> [--report]
results dir holds ref1.json ref2.json ref3.json stub.json noH.json ... noN.json (run_variant.py output).

Kept: the three reference runs agree, the reference result is not a harness failure, the untouched (stub) result
differs, and the input is not a duplicate. Area = the generator's nominal area when stripping that area alone (noX: the upstream header
with only area X stripped) changes the result; otherwise the first of R, M, N, Q, B, H whose removal alone changes
it; the nominal area if none does.
err = the reference result is a rejection (failed parse, error status, client error).
"""
import gzip
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, sys.argv[1])
import wire  # noqa: E402

cand_f, rdir, out_f = sys.argv[2], sys.argv[3], sys.argv[4]
R = {n: json.load(open(os.path.join(rdir, n + ".json"))) for n in
     ["ref1", "ref2", "ref3", "stub", "stub2", "noH", "noB", "noQ", "noM", "noR", "noN"]}
BAD = ("CRASH", "TIMEOUT", "NOSERVER", "SERVERDIED", "CONNFAIL", "DEADLINE", "EXC", "PEERFAIL", "BADOP", "BADKIND")
ORDER = ["R", "M", "N", "Q", "B", "H"]


def is_err(c, r):
    if c["kind"] == "wire":
        m = re.match(r"HTTP/1\.[01] (\d\d\d)", r)
        return not m or int(m.group(1)) >= 400
    op = c["op"]
    if op == "cli":
        return not r.startswith("err=Success")
    if op == "chunk":
        return "err " in r or " tok=0" in r
    if op == "bodyreader":
        return "err=Success" not in r
    if r.startswith("ok=0"):
        return True
    return False


seen = set()
kept, drop = [], Counter()
for l in gzip.open(cand_f):
    c = json.loads(l)
    key = (c.get("op"), tuple(c.get("args", ())), c.get("send"))
    if key in seen:
        drop["dup"] += 1
        continue
    seen.add(key)
    i = c["id"]
    r1, r2, r3 = R["ref1"].get(i), R["ref2"].get(i), R["ref3"].get(i)
    if r1 is None or not (r1 == r2 == r3):
        drop["flaky"] += 1
        continue
    if r1.startswith(BAD) or "EXC" == r1:
        drop["harness"] += 1
        continue
    if R["stub"].get(i) == r1 or R["stub2"].get(i) == r1:
        drop["stub-equal"] += 1
        continue
    if R["no" + c["nom"]].get(i) != r1:      # the case depends on the area it was written for
        area = c["nom"]
    else:
        area = next((a for a in ORDER if R["no" + a].get(i) != r1), None)
        drop["retagged"] += 1
        if area is None:
            drop["no-single-area"] += 1
            area = c["nom"]
    c["area"] = area
    c["expect"] = r1
    c["err"] = int(is_err(c, r1))
    kept.append(c)

with gzip.open(out_f, "wt") as f:
    for c in kept:
        f.write(json.dumps(c, sort_keys=True) + "\n")
print("kept", len(kept), "dropped", dict(drop))
print("area", dict(Counter(c["area"] for c in kept)))
print("kind x area", dict(Counter((c["kind"] if c.get("op") != "cli" else "cli", c["area"]) for c in kept)))
print("err share", round(sum(c["err"] for c in kept) / max(1, len(kept)), 3))
