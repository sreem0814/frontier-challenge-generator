"""Run a case file through a harness binary and report pass counts per bucket.

usage: python3 -I check.py <harness binary> <cases.jsonl> [--show N] [--bucket B] [--write-pass FILE]
"""
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harbor" / "tests"))
import run_cases  # noqa: E402
from score_cases import case_passes  # noqa: E402
from mpcodec import unpackb, to_json  # noqa: E402


def main():
    binary, path = sys.argv[1], sys.argv[2]
    show = int(sys.argv[sys.argv.index("--show") + 1]) if "--show" in sys.argv else 0
    only = sys.argv[sys.argv.index("--bucket") + 1] if "--bucket" in sys.argv else None
    wp = sys.argv[sys.argv.index("--write-pass") + 1] if "--write-pass" in sys.argv else None
    cases = [json.loads(l) for l in open(path)]
    if only:
        cases = [c for c in cases if c["bucket"] == only]
    res = run_cases.run(binary, cases)
    tot = collections.Counter()
    ok = collections.Counter()
    shown = 0
    passed = []
    for c in cases:
        tot[c["bucket"]] += 1
        r = res.get(c["id"], ("missing", None))
        if case_passes(c, r):
            ok[c["bucket"]] += 1
            passed.append(c["id"])
        elif shown < show:
            shown += 1
            print("FAIL", c["id"], c["props"])
            print("  expected", c["status"])
            if c["outputs"]:
                for i, (rin, o) in enumerate(zip(c["records"], c["outputs"])):
                    got = r[1][i] if r[1] and i < len(r[1]) else None
                    print("   in ", json.dumps(to_json(unpackb(bytes.fromhex(rin)))))
                    print("   exp", json.dumps(to_json(unpackb(bytes.fromhex(o)))))
                    print("   got", json.dumps(to_json(unpackb(got))) if got else r[0])
            else:
                print("   got", r[0])
    for b in tot:
        print("%-14s %5d / %5d" % (b, ok[b], tot[b]))
    print("TOTAL", sum(ok.values()), "/", sum(tot.values()))
    if wp:
        Path(wp).write_text("\n".join(passed) + "\n")


if __name__ == "__main__":
    main()
