"""freeze.py <setdir> <out_cases> <out_expected> [--samples DIR]: turns one generated set into frozen data.

Keeps a case when the reference produced the same transcript in all three runs, did not crash or time out, and
the stub's transcript differs (so the untouched tree fails it). Non-L cases are frozen as the SHA-256 and length
of the reference transcript. L cases are frozen as their strings and the reference grammar's verdict per string
(ACCEPT, PREFIX or REJECT), kept only when the reference converts the schema and at least two strings exist.
With --samples, also writes the visible sample files (case file, expected transcripts, string verdicts).
"""
import collections
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from casegen import read_frames  # noqa: E402


def verdicts(frame):
    out = []
    for line in frame.decode("utf-8", "replace").splitlines()[1:]:
        w = line.split()
        out.append(w[1] if len(w) >= 2 else "?")
    return out


def main():
    d, out_cases, out_exp = sys.argv[1:4]
    samples = sys.argv[sys.argv.index("--samples") + 1] if "--samples" in sys.argv else None
    refs = [read_frames(os.path.join(d, f"ref{i}.out")) for i in (1, 2, 3)]
    stub = read_frames(os.path.join(d, "stub.out"))
    lmatch = read_frames(os.path.join(d, "lmatch.out"))
    lstrings = json.load(open(os.path.join(d, "lstrings.json")))
    blocks = {}
    cur = []
    for line in open(os.path.join(d, "cases.txt")):
        cur.append(line)
        if line == "END\n":
            cid = cur[0].split()[1]
            blocks[cid] = "".join(cur)
            cur = []
    expected, kept = {}, []
    why = collections.Counter()
    per_bucket = collections.Counter()
    for cid, block in blocks.items():
        head = block.split("\n", 1)[0].split()
        bucket, kind = head[2], head[3]
        r = [x.get(cid) for x in refs]
        if any(x is None for x in r):
            why["ref crash/timeout"] += 1
            continue
        if not (r[0] == r[1] == r[2]):
            why["ref nondeterministic"] += 1
            continue
        if kind == "L":
            if not r[0].startswith(b"OK\n"):
                why["L ref throws"] += 1
                continue
            strs = lstrings.get(cid, [])
            fr = lmatch.get(cid)
            if fr is None or len(strs) < 2:
                why["L too few strings"] += 1
                continue
            v = verdicts(fr)
            if len(v) != len(strs) or "?" in v or "INIT_FAIL" in v:
                why["L matcher mismatch"] += 1
                continue
            expected[cid] = {"b": bucket, "k": "L", "strings": strs, "v": v}
        else:
            if stub.get(cid) == r[0]:
                why["stub passes"] += 1
                continue
            expected[cid] = {"b": bucket, "k": kind, "s": hashlib.sha256(r[0]).hexdigest(), "n": len(r[0])}
        kept.append(block)
        per_bucket[bucket] += 1
    with open(out_cases, "w") as f:
        f.write("".join(kept))
    with open(out_exp, "w") as f:
        json.dump(expected, f, separators=(",", ":"), sort_keys=True)
    if samples:
        os.makedirs(os.path.join(samples, "expected"), exist_ok=True)
        for cid, e in expected.items():
            p = os.path.join(samples, "expected", cid + ".txt")
            if e["k"] == "L":
                with open(p, "w") as f:
                    for h, v in zip(e["strings"], e["v"]):
                        f.write(f"{v} {h}\n")
            else:
                with open(p, "wb") as f:
                    f.write(refs[0][cid])
    print(json.dumps({"kept": len(kept), "per_bucket": dict(sorted(per_bucket.items())), "dropped": dict(why)}))


if __name__ == "__main__":
    main()
