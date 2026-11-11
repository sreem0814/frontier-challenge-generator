#!/usr/bin/env python3
"""selfcheck.py: estimate the score on the visible sample cases with the flatc built by ./build.sh.

  python3 check/selfcheck.py                 per-bucket pass counts and the weighted estimate
  python3 check/selfcheck.py --fails 20      also list up to 20 failing case ids per bucket
  python3 check/selfcheck.py --case ID       run one case and show where it differs from the expected result
  python3 check/selfcheck.py --bucket NAME   run only one bucket
  python3 check/selfcheck.py --flatc PATH    use another flatc binary

Each sample is check/samples/<id>/: cmd.json (bucket and flatc arguments), in/ (the input files, copied into an
empty directory where flatc runs) and expected/ (status, stdout and stderr where the bucket checks them, and
out/ with every file the reference wrote). The grader runs the same transcript comparison (fbcase.py, its own
copy) over a larger hidden set generated the same way, with the same weights.
"""
import argparse
import base64
import difflib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fbcase  # noqa: E402

WEIGHTS = {"schema_model": 0.06, "schema_bfbs": 0.08, "codegen": 0.14, "json_binary": 0.18, "json_text": 0.08,
           "diag": 0.20, "proto": 0.10, "bfbs_input": 0.08, "conform": 0.08}


def load_tree(d):
    files = {}
    for root, _dirs, names in os.walk(d):
        for n in names:
            p = os.path.join(root, n)
            with open(p, "rb") as f:
                files[os.path.relpath(p, d)] = base64.b64encode(f.read()).decode()
    return files


def expected_transcript(sd, bucket):
    ed = os.path.join(sd, "expected")
    status = open(os.path.join(ed, "status")).read().strip()
    rc = 0 if status == "ok" else 1
    tmp = tempfile.mkdtemp(prefix="exp-")
    try:
        if os.path.isdir(os.path.join(ed, "out")):
            shutil.copytree(os.path.join(ed, "out"), os.path.join(tmp, "out"))
        out = err = b""
        if bucket in fbcase.PRINTS:
            out = open(os.path.join(ed, "stdout"), "rb").read().replace(b"@", tmp.encode())
            err = open(os.path.join(ed, "stderr"), "rb").read().replace(b"@", tmp.encode())
        t, outs = fbcase.transcript(bucket, rc, out, err, tmp)
        m = fbcase.model_digest(rc, outs) if bucket == "schema_bfbs" else None
        return t, m
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_case(flatc, sd, keep=False):
    cmd = json.load(open(os.path.join(sd, "cmd.json")))
    d = tempfile.mkdtemp(prefix="case-")
    fbcase.materialize(load_tree(os.path.join(sd, "in")), d)
    rc, out, err = fbcase.run(flatc, cmd["argv"], d)
    t, outs = fbcase.transcript(cmd["bucket"], rc, out, err, d)
    m = fbcase.model_digest(rc, outs) if cmd["bucket"] == "schema_bfbs" else None
    if not keep:
        shutil.rmtree(d, ignore_errors=True)
    return cmd, t, m, d, out, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flatc", default=os.path.join(APP, "build", "flatc"))
    ap.add_argument("--samples", default=os.path.join(HERE, "samples"))
    ap.add_argument("--fails", type=int, default=0)
    ap.add_argument("--case")
    ap.add_argument("--bucket")
    a = ap.parse_args()
    if not os.path.isfile(a.flatc):
        sys.exit("no flatc at %s: run ./build.sh first" % a.flatc)
    flatc = os.path.abspath(a.flatc)
    if a.case:
        sd = os.path.join(a.samples, a.case)
        cmd, t, m, d, out, err = run_case(flatc, sd, keep=True)
        et, em = expected_transcript(sd, cmd["bucket"])
        print("bucket:", cmd["bucket"], " argv: flatc", " ".join(cmd["argv"]))
        print("ran in:", d)
        print("stdout:", out.decode("utf-8", "replace"))
        print("stderr:", err.decode("utf-8", "replace"))
        print("transcript:", "MATCH" if t == et else "DIFFERS")
        if t != et:
            sys.stdout.writelines(difflib.unified_diff(et.splitlines(True), t.replace(d, "@").splitlines(True),
                                                       "expected", "actual"))
            print("expected files are in", os.path.join(sd, "expected"), "; yours are in", os.path.join(d, "out"))
        if cmd["bucket"] == "schema_bfbs":
            print("decoded schema:", "MATCH" if m == em else "DIFFERS")
        return
    stats = {b: [0, 0] for b in WEIGHTS}
    fails = {b: [] for b in WEIGHTS}
    for cid in sorted(os.listdir(a.samples)):
        sd = os.path.join(a.samples, cid)
        bucket = json.load(open(os.path.join(sd, "cmd.json")))["bucket"]
        if a.bucket and a.bucket not in (bucket, "schema_model" if bucket == "schema_bfbs" else None):
            continue
        cmd, t, m, d, _o, _e = run_case(flatc, sd)
        et, em = expected_transcript(sd, bucket)
        stats[bucket][1] += 1
        if t == et:
            stats[bucket][0] += 1
        else:
            fails[bucket].append(cid)
        if bucket == "schema_bfbs":
            stats["schema_model"][1] += 1
            if m is not None and m == em:
                stats["schema_model"][0] += 1
            else:
                fails["schema_model"].append(cid)
    est = 0.0
    for b, (p, n) in stats.items():
        if n:
            est += WEIGHTS[b] * p / n
            print("%-13s %4d / %-4d  weight %.2f" % (b, p, n, WEIGHTS[b]))
            if a.fails and fails[b]:
                print("    failing:", " ".join(fails[b][:a.fails]))
    print("weighted estimate: %.4f" % est)


if __name__ == "__main__":
    main()
