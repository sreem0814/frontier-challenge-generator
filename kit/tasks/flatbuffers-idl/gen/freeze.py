"""Freeze a split: run every generated case with the reference flatc (three times, from directories of
different path lengths) and with the stub, keep the deterministic cases the stub fails, and write the case
inputs and the expected transcripts.

    python3 -I freeze.py <cases.json> <ref flatc> <stub flatc> <outdir> [--samples]

outdir/cases.json:    [{"id","b","argv","files":{rel: b64}}]
outdir/expected.json: {id: {"b", "h"[, "m"]}}
--samples also writes outdir/samples/<id>/{cmd.json,in/...,expected/{status,stdout,stderr,out/...}} for the
visible self-check.
"""
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.environ.get("FBTESTS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "harbor", "tests"))
import fbcase  # noqa: E402

REF, STUB = sys.argv[2], sys.argv[3]
OUTBUCKETS = {"schema_bfbs", "codegen", "json_binary", "json_text", "bfbs_input"}


def b64(s):
    return base64.b64encode(s if isinstance(s, bytes) else s.encode("utf-8")).decode()


def prepare(case):
    """Resolve pre steps: returns final {rel: b64} or None."""
    files = {}
    pre_files = {}
    for k, v in case["files"].items():
        if k.endswith("@pre"):
            pre_files[k[:-4]] = v
        else:
            files[k] = v
            pre_files[k] = v
    for step in case.get("pre", []):
        d = tempfile.mkdtemp(prefix="pre-")
        try:
            fbcase.materialize({k: b64(v) for k, v in pre_files.items()}, d)
            rc, out, err = fbcase.run(REF, step["argv"], d)
            if rc != 0:
                return None
            for src, dst in step["take"].items():
                p = os.path.join(d, src)
                if not os.path.isfile(p):
                    return None
                with open(p, "rb") as f:
                    files[dst] = f.read()
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return {k: b64(v) for k, v in files.items()}


def run_in(flatc, files, argv, bucket, prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    try:
        fbcase.materialize(files, d)
        rc, out, err = fbcase.run(flatc, argv, d)
        t, outs = fbcase.transcript(bucket, rc, out, err, d)
        m = fbcase.model_digest(rc, outs) if bucket == "schema_bfbs" else None
        return rc, t, m, out.replace(d.encode(), b"@"), err.replace(d.encode(), b"@"), outs
    finally:
        shutil.rmtree(d, ignore_errors=True)


def freeze_one(case):
    try:
        files = prepare(case)
    except Exception as e:  # generator bug: drop
        return None, "prepare " + str(e)
    if files is None:
        return None, "pre failed"
    b = case["b"]
    res = [run_in(REF, files, case["argv"], b, p) for p in ("r-", "ref-run-", "reference-run-xx-")]
    if b in OUTBUCKETS and res[0][0] != 0:
        b = "diag"
        res = [run_in(REF, files, case["argv"], b, p) for p in ("r-", "ref-run-", "reference-run-xx-")]
    if len({(x[1], x[2]) for x in res}) != 1:
        return None, "nondeterministic"
    rc, t, m, out, err, outs = res[0]
    if rc is None:
        return None, "reference timeout"
    st = run_in(STUB, files, case["argv"], b, "s-")
    if st[1] == t:
        return None, "stub passes"
    rec = {"id": case["id"], "b": b, "argv": case["argv"], "files": files}
    exp = {"b": b, "h": fbcase.digest(t)}
    if b == "schema_bfbs":
        if m is None:
            return None, "no model"
        exp["m"] = m
    sample = {"status": "ok" if rc == 0 else "fail", "stdout": b64(out), "stderr": b64(err),
              "out": {rel: b64(d) for rel, d in outs}}
    return (rec, exp, sample), ""


def main():
    cases = json.load(open(sys.argv[1]))
    outdir = sys.argv[4]
    samples = "--samples" in sys.argv
    os.makedirs(outdir, exist_ok=True)
    kept, expected, why = [], {}, {}
    seen = set()
    with ProcessPoolExecutor(int(os.environ.get("JOBS", "4"))) as ex:
        for case, (res, reason) in zip(cases, ex.map(freeze_one, cases, chunksize=8)):
            if res is None:
                why[reason] = why.get(reason, 0) + 1
                continue
            rec, exp, sample = res
            key = hashlib.sha256(json.dumps([rec["argv"], sorted(rec["files"].items())]).encode()).hexdigest()
            if key in seen:
                why["duplicate"] = why.get("duplicate", 0) + 1
                continue
            seen.add(key)
            kept.append(rec)
            expected[rec["id"]] = exp
            if samples:
                sd = os.path.join(outdir, "samples", rec["id"])
                os.makedirs(sd, exist_ok=True)
                with open(os.path.join(sd, "cmd.json"), "w") as f:
                    json.dump({"bucket": rec["b"], "argv": rec["argv"]}, f, indent=1)
                    f.write("\n")
                fbcase.materialize(rec["files"], os.path.join(sd, "in"))
                ed = os.path.join(sd, "expected")
                os.makedirs(ed, exist_ok=True)
                with open(os.path.join(ed, "status"), "w") as f:
                    f.write(sample["status"] + "\n")
                if rec["b"] in fbcase.PRINTS:
                    with open(os.path.join(ed, "stdout"), "wb") as f:
                        f.write(base64.b64decode(sample["stdout"]))
                    with open(os.path.join(ed, "stderr"), "wb") as f:
                        f.write(base64.b64decode(sample["stderr"]))
                fbcase.materialize(sample["out"], os.path.join(ed, "out"))
    with open(os.path.join(outdir, "cases.json"), "w") as f:
        json.dump(kept, f, separators=(",", ":"))
    with open(os.path.join(outdir, "expected.json"), "w") as f:
        json.dump(expected, f, separators=(",", ":"), sort_keys=True)
    counts = {}
    for e in expected.values():
        counts[e["b"]] = counts.get(e["b"], 0) + 1
    print(json.dumps({"kept": len(kept), "buckets": counts, "dropped": why}))


if __name__ == "__main__":
    main()
