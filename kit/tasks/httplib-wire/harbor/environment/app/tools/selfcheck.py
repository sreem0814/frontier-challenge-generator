#!/usr/bin/env python3
"""Self-check: build the two case programs against /app/httplib.h and run the sample cases.

usage: python3 /app/tools/selfcheck.py [--header PATH] [--area H|B|Q|M|R|N] [--op OP|wire] [--show N] [--jobs 8]

Prints, per area, the credited sample cases (same rule as the graded run, including the family rule for
rejections) and an estimate of the 0.7-weighted case part of the reward. The upstream test suite part is not
included: it is not in this image. --show N prints N failing cases with their input, expected and actual result.
"""
import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wire  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--header", default="/app/httplib.h")
ap.add_argument("--cases", default=os.path.join(os.path.dirname(HERE), "samples", "cases.jsonl.gz"))
ap.add_argument("--area")
ap.add_argument("--op")
ap.add_argument("--show", type=int, default=0)
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--keep", action="store_true", help="keep the build directory")
a = ap.parse_args()

work = tempfile.mkdtemp(prefix="selfcheck-")
inc = os.path.join(work, "inc")
os.makedirs(inc)
shutil.copyfile(a.header, os.path.join(inc, "httplib.h"))
t0 = time.time()
procs = []
for name in ("probe", "server"):
    cmd = ["g++", "-std=c++17", "-O1", "-I" + inc, "-DCPPHTTPLIB_ZLIB_SUPPORT", "-DCPPHTTPLIB_BROTLI_SUPPORT",
           "-DCPPHTTPLIB_ZSTD_SUPPORT", os.path.join(HERE, name + ".cc"), "-o", os.path.join(work, name),
           "-lz", "-lbrotlicommon", "-lbrotlienc", "-lbrotlidec", "-lzstd", "-lpthread"]
    procs.append((name, subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)))
failed = False
for name, p in procs:
    out, _ = p.communicate()
    if p.returncode:
        failed = True
        print(f"BUILD FAILED ({name}.cc): this is the hard gate, the graded run would score 0")
        print(out.decode("utf-8", "replace")[-3000:])
if failed:
    sys.exit(1)
print(f"build ok ({time.time() - t0:.0f} s)")

cases = []
for l in gzip.open(a.cases):
    c = json.loads(l)
    if c["kind"] == "probe":
        c["args"] = [bytes.fromhex(x) for x in c["args"]]
    else:
        c["send"] = bytes.fromhex(c["send"])
    cases.append(c)
pc = [c for c in cases if c["kind"] == "probe"]
wc = [c for c in cases if c["kind"] == "wire"]
res = {}
with ThreadPoolExecutor(a.jobs) as ex:
    for r in ex.map(lambda k: wire.run_probe_shard(os.path.join(work, "probe"), pc[k::a.jobs], cwd=work),
                    range(a.jobs)):
        res.update(r)
with ThreadPoolExecutor(a.jobs) as ex:
    for r in ex.map(lambda k: wire.run_wire_shard(os.path.join(work, "server"), 24100 + k,
                                                  tempfile.mkdtemp(dir=work), wc[k::a.jobs]), range(a.jobs)):
        res.update(r)

cred = wire.credit(cases, res)
areas = wire.area_scores(cases, cred)
names = {"H": "messages", "B": "bodies", "Q": "urls", "M": "multipart", "R": "ranges", "N": "negotiation"}
for k, (g, t) in areas.items():
    print(f"  {k} {names[k]:12s} {g:5d}/{t:<5d} {g / t if t else 0:.3f}")
part = sum(g / t for g, t in areas.values() if t) / len(areas)
print(f"case part {part:.4f}  ->  reward estimate 0.3 * upstream + 0.7 * {part:.4f} = {0.7 * part:.4f} + 0.3 * upstream"
      f"  ({time.time() - t0:.0f} s)")

if a.show:
    shown = 0
    for c in cases:
        if cred[c["id"]]:
            continue
        if a.area and c["area"] != a.area:
            continue
        if a.op and c.get("op", "wire") != a.op:
            continue
        print("-" * 100)
        print(f"{c['id']} area {c['area']} family {c['fam']} {'(rejection)' if c['err'] else ''}")
        if c["kind"] == "probe":
            print(f"op {c['op']} args " + " | ".join(wire.esc(x) for x in c["args"]))
        else:
            print("sent " + wire.esc(c["send"]))
        print("expected " + c["expect"])
        print("actual   " + str(res.get(c["id"])))
        if res.get(c["id"]) == c["expect"]:
            print("(matches, but its family has no passing non-rejection case yet)")
        shown += 1
        if shown >= a.show:
            break
if not a.keep:
    shutil.rmtree(work, ignore_errors=True)
else:
    print("build dir:", work)
