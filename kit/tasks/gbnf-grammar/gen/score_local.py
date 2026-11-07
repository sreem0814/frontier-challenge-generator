"""score_local.py <expected.json> <runner.out> [<lmatch.out>]: weighted score of one runner's transcripts
(authoring check; same rules as tests/collect.py). Writes the L match requests to stdout's sibling file
when no lmatch.out is given: <runner.out>.lmatch.txt"""
import hashlib, json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casegen import read_frames
W = {"gbnf_parse": 0.09, "gbnf_match": 0.11, "gbnf_stacks": 0.06, "gbnf_tokens": 0.12,
     "schema_doc": 0.12, "schema_text": 0.24, "schema_lang": 0.26}
exp = json.load(open(sys.argv[1]))
got = read_frames(sys.argv[2])
if len(sys.argv) < 4:
    with open(sys.argv[2] + ".lmatch.txt", "w") as f:
        for cid, e in exp.items():
            g = got.get(cid)
            if e["k"] == "L" and g is not None and g.startswith(b"OK\n"):
                f.write(f"CASE {cid} schema_lang M\nG {g[3:].hex()}\n" + "".join(f"S {h}\n" for h in e["strings"]) + "END\n")
    sys.exit(0)
lm = read_frames(sys.argv[3])
st = {b: [0, 0] for b in W}
for cid, e in exp.items():
    if e["k"] == "L":
        fr = lm.get(cid)
        v = [l.split()[1] if len(l.split()) > 1 else "?" for l in fr.decode().splitlines()[1:]] if fr is not None else None
        ok = v == e["v"]
    else:
        g = got.get(cid)
        ok = g is not None and len(g) == e["n"] and hashlib.sha256(g).hexdigest() == e["s"]
    st[e["b"]][1] += 1; st[e["b"]][0] += ok
score = sum(W[b] * p / t for b, (p, t) in st.items() if t)
print(json.dumps({"score": round(score, 4), **{b: f"{p}/{t}" for b, (p, t) in st.items()}}))
