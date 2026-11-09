"""gen/run_variant.py: run candidate cases against one build (probe + server binaries) in 8 shards.

usage: python3 -I run_variant.py <tests dir> <cases.jsonl.gz> <probe bin> <server bin> <out.json> [--port 20000]
"""
import gzip
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, sys.argv[1])
import wire  # noqa: E402

cases_f, probe, server, out = sys.argv[2:6]
port0 = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 20000
JOBS = 8
cases = []
for l in gzip.open(cases_f):
    c = json.loads(l)
    if c["kind"] == "probe":
        c["args"] = [bytes.fromhex(a) for a in c["args"]]
    else:
        c["send"] = bytes.fromhex(c["send"])
    cases.append(c)
pc = [c for c in cases if c["kind"] == "probe"]
wc = [c for c in cases if c["kind"] == "wire"]
t0 = time.time()
res = {}


def pshard(k):
    return wire.run_probe_shard(probe, pc[k::JOBS], cwd=tempfile.mkdtemp())


def wshard(k):
    return wire.run_wire_shard(server, port0 + k, tempfile.mkdtemp(), wc[k::JOBS])


with ThreadPoolExecutor(JOBS) as ex:
    for r in ex.map(pshard, range(JOBS)):
        res.update(r)
with ThreadPoolExecutor(JOBS) as ex:
    for r in ex.map(wshard, range(JOBS)):
        res.update(r)
json.dump(res, open(out, "w"))
print(f"{len(res)} results ({len(pc)} probe, {len(wc)} wire) in {time.time() - t0:.0f} s")
