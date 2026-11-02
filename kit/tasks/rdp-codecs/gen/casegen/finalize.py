"""Freeze a case set from the oracle run.

finalize.py SRC_DIR OUT_DIR [--dump DUMP_DIR | --sha256 DUMP_DIR]
Keeps every sequence whose steps all decoded cleanly with the oracle (success, nothing logged) and every
truncated variant the oracle rejected whose parent was kept. Writes OUT_DIR/cases.bin (kept records only)
and OUT_DIR/expected.json. With --dump (raw buffers from codec_runner --dump) also writes
OUT_DIR/expected.pack.xz: for every valid step, u32 seq, u32 step, u32 len, bytes. With --sha256 the
expected entries carry the SHA-256 and size of the oracle's buffer instead of the runner's FNV hash."""
import hashlib
import json
import lzma
import os
import struct
import sys

src, out = sys.argv[1], sys.argv[2]
dump = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--dump" else None
sha_from = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--sha256" else None
meta = {m["seq"]: m for m in json.load(open(f"{src}/meta.json"))}
res, crash = {}, set()
for ln in open(f"{src}/oracle.txt"):
    p = ln.split()
    if p[0] == "R":
        res[(int(p[1]), int(p[2]))] = (int(p[3]), p[4], int(p[5]))
    elif p[0] == "X":
        crash.add(int(p[1]))

keep = {}
for sid, m in meta.items():
    if m["parent"] is not None or sid in crash:
        continue
    steps = []
    good = True
    for i, st in enumerate(m["steps"]):
        r = res.get((sid, i))
        if not r or r[0] != 1 or r[2] != 0:
            good = False
            break
        steps.append({"k": "v", "h": r[1]})
        if sha_from:
            raw = open(os.path.join(sha_from, f"{sid:08d}-{i:04d}.raw"), "rb").read()
            steps[-1] = {"k": "v", "s": hashlib.sha256(raw).hexdigest(), "n": len(raw)}
    if good:
        keep[sid] = {"codec": m["codec"], "steps": steps, "tags": m["tags"], "step_tags": [s["tags"] for s in m["steps"]]}
for sid, m in meta.items():
    if m["parent"] is None or sid in crash:
        continue
    psid, pstep = m["parent"]
    r = res.get((sid, 0))
    if psid in keep and r and r[0] == 0:
        keep[sid] = {"codec": m["codec"], "steps": [{"k": "t", "p": [psid, pstep]}], "tags": m["tags"],
                     "step_tags": [s["tags"] for s in m["steps"]]}

os.makedirs(out, exist_ok=True)
data = open(f"{src}/cases.bin", "rb").read()
pos = 0
with open(f"{out}/cases.bin", "wb") as f:
    while pos < len(data):
        start = pos
        sid = struct.unpack_from("<I", data, pos + 4)[0]
        nsteps = struct.unpack_from("<I", data, pos + 40)[0]
        pos += 44
        for _ in range(nsteps):
            pos += 36
            pf = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + (1024 if pf else 0)
            ln = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + ln
        if sid in keep:
            f.write(data[start:pos])
with open(f"{out}/expected.json", "w") as f:
    json.dump({str(k): v for k, v in sorted(keep.items())}, f, separators=(",", ":"))
if dump:
    with lzma.open(f"{out}/expected.pack.xz", "wb", preset=9) as f:
        for sid, v in sorted(keep.items()):
            for i, st in enumerate(v["steps"]):
                if st["k"] != "v":
                    continue
                raw = open(os.path.join(dump, f"{sid:08d}-{i:04d}.raw"), "rb").read()
                f.write(struct.pack("<III", sid, i, len(raw)) + raw)
stats = {}
for v in keep.values():
    c = stats.setdefault(v["codec"], [0, 0])
    for st in v["steps"]:
        c[0 if st["k"] == "v" else 1] += 1
print("kept", len(keep), "sequences;", {k: {"valid": a, "trunc": b} for k, (a, b) in sorted(stats.items())})
