"""Self-check for the modify-filter work: runs the visible sample cases through your build.

usage: python3 /app/check/selfcheck.py [--build] [--upstream] [--bucket NAME] [--show N] [--cases FILE]
  --build      run /app/tools/build.sh first (incremental)
  --upstream   also run the upstream suites (flb-rt-filter_modify, flb-it-record_accessor), as the grader does
  --show N     print the first N failing cases with input, expected and actual bodies
It compiles check/harness/modify_harness.c against /app/fluent-bit/build (the same harness the grader uses)
and reports, per bucket, how many sample cases pass, plus the score the grading formula gives on the samples.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_cases  # noqa: E402
from score_cases import case_passes  # noqa: E402
from mpcodec import unpackb, to_json  # noqa: E402

SRC = Path("/app/fluent-bit")
BUILD = SRC / "build"
WEIGHTS = json.loads((HERE / "weights.json").read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--upstream", action="store_true")
    ap.add_argument("--bucket")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--cases", default=str(HERE / "samples.jsonl"))
    a = ap.parse_args()

    if a.build and subprocess.run(["bash", "/app/tools/build.sh"]).returncode != 0:
        print("BUILD FAILED (the grader scores a failed build 0)")
        return 1
    hb = Path("/tmp/selfcheck-harness")
    r = subprocess.run([sys.executable, "-I", str(HERE / "harness" / "build_harness.py"), str(SRC), str(BUILD),
                        str(HERE / "harness" / "modify_harness.c"), str(hb)])
    if r.returncode != 0:
        print("harness does not compile against the build")
        return 1

    if a.upstream:
        for t in ("flb-rt-filter_modify", "flb-it-record_accessor"):
            rc = subprocess.run([str(BUILD / "bin" / t)], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL).returncode
            print("upstream %-24s %s" % (t, "PASS" if rc == 0 else "FAIL (the grader scores this 0)"))

    cases = [json.loads(l) for l in open(a.cases)]
    if a.bucket:
        cases = [c for c in cases if c["bucket"] == a.bucket]
    res = run_cases.run(str(hb), cases)
    tot, ok = {}, {}
    shown = 0
    for c in cases:
        b = c["bucket"]
        tot[b] = tot.get(b, 0) + 1
        rr = res.get(c["id"], ("missing", None))
        if case_passes(c, rr):
            ok[b] = ok.get(b, 0) + 1
        elif shown < a.show:
            shown += 1
            print("FAIL %s  %s" % (c["id"], json.dumps(c["props"])))
            if c["status"] == "init_fail":
                print("  expected: the filter refuses this configuration; got:", rr[0])
                continue
            if rr[0] != "ok":
                print("  expected: accepted; got:", rr[0])
                continue
            for i, (rin, rexp) in enumerate(zip(c["records"], c["outputs"])):
                got = rr[1][i] if i < len(rr[1]) else None
                print("  in  ", json.dumps(to_json(unpackb(bytes.fromhex(rin)))))
                print("  want", json.dumps(to_json(unpackb(bytes.fromhex(rexp)))))
                print("  got ", json.dumps(to_json(unpackb(got))) if got is not None else None)
    feature = 0.0
    for b in sorted(tot):
        print("%-14s %4d / %4d" % (b, ok.get(b, 0), tot[b]))
        if b in WEIGHTS:
            feature += WEIGHTS[b] * ok.get(b, 0) / tot[b]
    if not a.bucket:
        legacy = ok.get("legacy", 0) / tot["legacy"] if tot.get("legacy") else 1.0
        print("sample score: %.4f (feature %.4f x legacy %.4f)" % (feature * legacy, feature, legacy))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
