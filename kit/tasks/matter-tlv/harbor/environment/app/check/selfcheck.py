#!/usr/bin/env python3
"""Self-check: build the library and check/case_runner from /app, run the sample cases, compare transcripts.

  check/selfcheck.py                 build, run every sample case, print per-bucket results and the weighted score
  check/selfcheck.py --bucket json_tlv --show 3     also print the first 3 differing transcripts of a bucket
  check/selfcheck.py --case s00042   print expected and actual transcript of one case
  check/selfcheck.py --cases my.txt  run your own case file and print the transcripts (no comparison)

The grader runs the same case_runner (its own copy) on a larger set of cases you cannot see, built from a clean
copy of the starting tree plus your files, and weights the buckets as WEIGHTS below.
"""
import argparse
import difflib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
WEIGHTS = {"tlv_write": 0.14, "tlv_read": 0.16, "tlv_tools": 0.18, "msg_header": 0.10, "json_tlv": 0.18,
           "onboarding": 0.24}


def parse(data):
    res, pos, n = {}, 0, len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split(b" ")
        pos = nl + 1
        if len(head) == 4 and head[0] == b"C" and head[3].isdigit():
            ln = int(head[3])
            res.setdefault(head[1].decode(), (head[2].decode(), "C", data[pos:pos + ln]))
            pos += ln
        elif len(head) >= 3 and head[0] == b"X":
            res.setdefault(head[1].decode(), (head[2].decode(), "X", b" ".join(head[3:])))
        else:
            break
    return res


def build():
    bdir = os.path.join(HERE, "build")
    if not os.path.isfile(os.path.join(bdir, "build.ninja")):
        r = subprocess.run(["cmake", "-S", HERE, "-B", bdir, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                            f"-DTREE={APP}"], capture_output=True, text=True)
        if r.returncode:
            sys.exit("configure failed:\n" + r.stdout[-3000:] + r.stderr[-3000:])
    r = subprocess.run(["ninja", "-C", bdir, "case_runner"], capture_output=True, text=True)
    if r.returncode:
        sys.exit("build failed:\n" + r.stdout[-6000:])
    return os.path.join(bdir, "case_runner")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--case")
    ap.add_argument("--cases")
    a = ap.parse_args()
    runner = build()
    if a.cases:
        out = subprocess.run([runner, a.cases], capture_output=True).stdout
        sys.stdout.write(out.decode("utf-8", "replace"))
        return
    cases = os.path.join(HERE, "samples", "cases.txt")
    cmd = [runner, cases] + (["--only", a.case] if a.case else [])
    got = parse(subprocess.run(cmd, capture_output=True).stdout)
    exp = parse(open(os.path.join(HERE, "samples", "expected.txt"), "rb").read())
    if a.case:
        e, g = exp.get(a.case), got.get(a.case)
        print("--- expected"), print(e[2].decode("utf-8", "replace") if e else "(no such case)")
        print("--- actual"), print(g[2].decode("utf-8", "replace") if g and g[1] == "C" else g)
        return
    per = {b: [0, 0] for b in WEIGHTS}
    shown = 0
    for cid, (b, _, t) in sorted(exp.items()):
        g = got.get(cid)
        ok = g is not None and g[1] == "C" and g[2] == t
        per[b][1] += 1
        per[b][0] += ok
        if not ok and a.bucket == b and shown < a.show:
            shown += 1
            print(f"=== {cid} ({b})")
            if g is None or g[1] != "C":
                print("crashed or missing:", g[2].decode() if g else "")
            else:
                for ln in difflib.unified_diff(t.decode("utf-8", "replace").splitlines(),
                                               g[2].decode("utf-8", "replace").splitlines(), "expected", "actual",
                                               lineterm="", n=1):
                    print(ln[:400])
    score = sum(WEIGHTS[b] * p / t for b, (p, t) in per.items() if t)
    for b, (p, t) in per.items():
        print(f"{b:12s} {p:4d}/{t:<4d} weight {WEIGHTS[b]:.2f}")
    print(f"estimated score {score:.4f}")


if __name__ == "__main__":
    main()
