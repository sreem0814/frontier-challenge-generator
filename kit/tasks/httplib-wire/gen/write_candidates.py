"""gen/write_candidates.py <out.jsonl.gz> <seed> <prefix> [scale]: candidate cases, bytes as hex."""
import gzip, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cases_gen
cs = cases_gen.generate(int(sys.argv[2]), sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 1)
with gzip.open(sys.argv[1], "wt") as f:
    for c in cs:
        c = dict(c)
        if c["kind"] == "probe":
            c["args"] = [a.hex() for a in c["args"]]
        else:
            c["send"] = c["send"].hex()
        f.write(json.dumps(c) + "\n")
from collections import Counter
print(len(cs), Counter((c["kind"], c["nom"]) for c in cs))
