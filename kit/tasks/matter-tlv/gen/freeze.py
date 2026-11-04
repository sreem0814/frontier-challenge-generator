"""Freeze the hidden set and the visible samples from reference runs (authoring only).

usage: python3 -I freeze.py <workdir> <bundle harbor dir>
<workdir> holds hidden_cases.txt / sample_cases.txt and the outputs of: three reference runs (ref1..3),
one sanitizer run (san) and one stub run (stub) for each set: <set>.<run>.out
A case is kept when the three reference runs agree, the sanitizer run (ASan + UBSan) reproduces it without a
report, the reference finished it, and the stubbed starting tree does not already produce the same transcript.
"""
import hashlib
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_out import parse  # noqa: E402

work, harbor = sys.argv[1], sys.argv[2]


def blocks(path):
    cases, cur = {}, None
    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith("CASE "):
            cur = [line]
            cid = line.split()[1]
        elif line == "END":
            cur.append(line)
            cases[cid] = "\n".join(cur) + "\n"
            cur = None
        elif cur is not None:
            cur.append(line)
    return cases


def select(name):
    src = blocks(os.path.join(work, f"{name}_cases.txt"))
    runs = {r: parse(open(os.path.join(work, f"{name}.{r}.out"), "rb").read())
            for r in ("ref1", "ref2", "ref3", "san", "stub")}
    keep, why = {}, Counter()
    for cid, text in src.items():
        r1 = runs["ref1"].get(cid)
        if not r1 or r1[1] != "C":
            why["reference crashed"] += 1
            continue
        if any(runs[r].get(cid) != r1 for r in ("ref2", "ref3")):
            why["reference not deterministic"] += 1
            continue
        if runs["san"].get(cid) != r1:
            why["sanitizer report or difference"] += 1
            continue
        if runs["stub"].get(cid) == r1:
            why["stub already passes"] += 1
            continue
        keep[cid] = (text, r1[0], r1[2])
    return keep, why


hidden, why_h = select("hidden")
samples, why_s = select("sample")
tests = os.path.join(harbor, "tests", "data")
os.makedirs(tests, exist_ok=True)
with open(os.path.join(tests, "cases.txt"), "w") as f:
    for cid in sorted(hidden):
        f.write(hidden[cid][0])
exp = {cid: {"b": b, "n": len(t), "s": hashlib.sha256(t).hexdigest()} for cid, (_, b, t) in sorted(hidden.items())}
with open(os.path.join(tests, "expected.json"), "w") as f:
    json.dump(exp, f, separators=(",", ":"))
sdir = os.path.join(harbor, "environment", "app", "check", "samples")
os.makedirs(sdir, exist_ok=True)
with open(os.path.join(sdir, "cases.txt"), "w") as f:
    for cid in sorted(samples):
        f.write(samples[cid][0])
with open(os.path.join(sdir, "expected.txt"), "wb") as f:
    for cid in sorted(samples):
        _, b, t = samples[cid]
        f.write(f"C {cid} {b} {len(t)}\n".encode() + t)
print("hidden", len(hidden), dict(Counter(v[1] for v in hidden.values())), "dropped", dict(why_h))
print("samples", len(samples), dict(Counter(v[1] for v in samples.values())), "dropped", dict(why_s))
