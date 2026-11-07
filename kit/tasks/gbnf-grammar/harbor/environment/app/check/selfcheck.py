#!/usr/bin/env python3
"""selfcheck.py: estimate the score on the visible sample cases with the case runner built by ./build.sh.

  python3 check/selfcheck.py                 per-bucket pass counts and the weighted estimate
  python3 check/selfcheck.py --fails 20      also list up to 20 failing case ids per bucket
  python3 check/selfcheck.py --case ID       show the expected and the actual transcript of one case
  python3 check/selfcheck.py --bucket NAME   run only one bucket

The grader runs the same case_runner.cpp (its own copy) over a larger hidden set built the same way, with the
same weights. One difference: schema_lang grammars are checked here with your own grammar engine; the grader
checks them with the original engine, so a wrong engine can hide or add schema_lang failures here.
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
WEIGHTS = {"gbnf_parse": 0.09, "gbnf_match": 0.11, "gbnf_stacks": 0.06, "gbnf_tokens": 0.12,
           "schema_doc": 0.12, "schema_text": 0.24, "schema_lang": 0.26}


def parse_frames(data):
    res, pos, n = {}, 0, len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split(b" ")
        pos = nl + 1
        if len(head) == 4 and head[0] == b"C" and head[3].isdigit():
            ln = int(head[3])
            res.setdefault(head[1].decode(), data[pos:pos + ln])
            pos += ln
        elif len(head) >= 3 and head[0] == b"X":
            res.setdefault(head[1].decode(), None)
        else:
            break
    return res


def blocks(path):
    out, cur = {}, []
    with open(path) as f:
        for line in f:
            cur.append(line)
            if line == "END\n":
                h = cur[0].split()
                out[h[1]] = (h[2], h[3], "".join(cur))
                cur = []
    return out


def verdicts(frame):
    v = []
    for line in frame.decode("utf-8", "replace").splitlines()[1:]:
        w = line.split()
        v.append(w[1] if len(w) >= 2 else "?")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner", default=os.path.join(APP, "build", "case_runner"))
    ap.add_argument("--samples", default=os.path.join(HERE, "samples"))
    ap.add_argument("--fails", type=int, default=0)
    ap.add_argument("--case", default="")
    ap.add_argument("--bucket", default="")
    ap.add_argument("--timeout", type=int, default=10)
    a = ap.parse_args()
    if not os.path.isfile(a.runner):
        sys.exit(f"{a.runner} not found: run ./build.sh first")
    cases = blocks(os.path.join(a.samples, "cases.txt"))
    if a.case:
        cases = {k: v for k, v in cases.items() if k == a.case}
    elif a.bucket:
        cases = {k: v for k, v in cases.items() if v[0] == a.bucket}
    models = os.path.join(APP, "models")
    with tempfile.TemporaryDirectory() as td:
        cf = os.path.join(td, "cases.txt")
        with open(cf, "w") as f:
            f.write("".join(b for _, _, b in cases.values()))
        out = subprocess.run([a.runner, cf, "--models", models, "--timeout", str(a.timeout)],
                             stdout=subprocess.PIPE).stdout
        got = parse_frames(out)
        # schema_lang: match the converted grammars against the sample strings with the case runner's M kind
        lexp, lblocks = {}, []
        for cid, (bucket, kind, _) in cases.items():
            if kind != "L":
                continue
            rows = [ln.split() for ln in open(os.path.join(a.samples, "expected", cid + ".txt"))]
            lexp[cid] = rows
            fr = got.get(cid)
            if fr is not None and fr.startswith(b"OK\n"):
                lblocks.append(f"CASE {cid} schema_lang M\nG {fr[3:].hex()}\n" +
                               "".join(f"S {r[1] if len(r) > 1 else ''}\n" for r in rows) + "END\n")
        lgot = {}
        if lblocks:
            lf = os.path.join(td, "lmatch.txt")
            with open(lf, "w") as f:
                f.write("".join(lblocks))
            lgot = parse_frames(subprocess.run([a.runner, lf, "--timeout", str(a.timeout)],
                                               stdout=subprocess.PIPE).stdout)
    stats = {b: [0, 0] for b in WEIGHTS}
    fails = {b: [] for b in WEIGHTS}
    for cid, (bucket, kind, _) in sorted(cases.items()):
        if kind == "L":
            exp_v = [r[0] for r in lexp[cid]]
            fr = lgot.get(cid)
            ok = fr is not None and verdicts(fr) == exp_v
            if a.case:
                print("expected verdicts:", " ".join(exp_v))
                print("your grammar:\n" + (got.get(cid) or b"(crash or timeout)").decode("utf-8", "replace"))
                print("your verdicts:", " ".join(verdicts(fr)) if fr is not None else "(none)")
        else:
            with open(os.path.join(a.samples, "expected", cid + ".txt"), "rb") as f:
                exp = f.read()
            ok = got.get(cid) == exp
            if a.case:
                print("---- expected\n" + exp.decode("utf-8", "replace"))
                print("---- got\n" + (got.get(cid) or b"(crash or timeout)").decode("utf-8", "replace"))
        stats[bucket][1] += 1
        stats[bucket][0] += int(ok)
        if not ok:
            fails[bucket].append(cid)
    score, wsum = 0.0, 0.0
    for b, (p, t) in stats.items():
        if t:
            score += WEIGHTS[b] * p / t
            wsum += WEIGHTS[b]
            print(f"{b:12s} {p:4d}/{t:<4d} weight {WEIGHTS[b]:.2f}")
            if a.fails and fails[b]:
                print("    failing:", " ".join(fails[b][:a.fails]))
    if wsum:
        print(f"estimate {score / wsum:.4f}" + ("" if abs(wsum - 1) < 1e-9 else " (over the buckets run)"))


if __name__ == "__main__":
    main()
