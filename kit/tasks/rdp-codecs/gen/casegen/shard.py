"""Split a cases.bin into N shards of whole SEQ1 records: shard.py cases.bin N prefix"""
import struct
import sys

path, n, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3]
data = open(path, "rb").read()
recs, pos = [], 0
while pos < len(data):
    start = pos
    assert data[pos:pos + 4] == b"SEQ1"
    nsteps = struct.unpack_from("<I", data, pos + 40)[0]
    pos += 44
    for _ in range(nsteps):
        pos += 4 + 32
        pf = struct.unpack_from("<I", data, pos)[0]
        pos += 4 + (1024 if pf else 0)
        ln = struct.unpack_from("<I", data, pos)[0]
        pos += 4 + ln
    recs.append(data[start:pos])
# balance by size
order = sorted(range(len(recs)), key=lambda i: -len(recs[i]))
bins = [[] for _ in range(n)]
sizes = [0] * n
for i in order:
    k = sizes.index(min(sizes))
    bins[k].append(i)
    sizes[k] += len(recs[i])
for k in range(n):
    with open(f"{prefix}.{k:02d}.bin", "wb") as f:
        for i in sorted(bins[k]):
            f.write(recs[i])
