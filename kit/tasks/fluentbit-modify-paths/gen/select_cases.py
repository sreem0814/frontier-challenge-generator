"""Pick the frozen set from generated candidates.

usage: python3 -I select_cases.py <candidates.jsonl> <pristine-pass ids> <scale> <out.jsonl>
Scored buckets keep only cases the untouched tree fails (so the starting state scores exactly 0);
the legacy bucket keeps only cases the untouched tree passes (it is the regression set).
Prints the per-bucket counts and the narrow-model (core) pass rates.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "harbor" / "tests"))
from generate import BUCKETS  # noqa: E402
from mpcodec import unpackb, packb, canon  # noqa: E402
import core_model  # noqa: E402


def main():
    cand = [json.loads(l) for l in open(sys.argv[1])]
    passed = set(Path(sys.argv[2]).read_text().split())
    scale = float(sys.argv[3])
    out = Path(sys.argv[4])
    keep = {b: [] for b in BUCKETS}
    dropped = {b: 0 for b in BUCKETS}
    for c in cand:
        b = c["bucket"]
        want = int(BUCKETS[b] * scale)
        if len(keep[b]) >= want:
            continue
        if b == "legacy":
            if c["id"] in passed:
                keep[b].append(c)
            else:
                dropped[b] += 1
        else:
            if c["id"] in passed:
                dropped[b] += 1
            else:
                keep[b].append(c)
    core = {}
    with out.open("w") as f:
        for b, cs in keep.items():
            ok = 0
            for c in cs:
                recs = [unpackb(bytes.fromhex(r)) for r in c["records"]]
                st, outs = core_model.apply_case([tuple(p) for p in c["props"]], recs)
                if st == c["status"] and (st == "init_fail" or all(
                        canon(o) == canon(unpackb(bytes.fromhex(e))) for o, e in zip(outs, c["outputs"]))):
                    ok += 1
                f.write(json.dumps(c) + "\n")
            core[b] = (ok, len(cs))
    for b in BUCKETS:
        print("%-14s kept %4d dropped %4d core %4d/%4d" % (b, len(keep[b]), dropped[b], core[b][0], core[b][1]))


if __name__ == "__main__":
    main()
