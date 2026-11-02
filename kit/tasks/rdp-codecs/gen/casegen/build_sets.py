"""Generate a case set: python3 build_sets.py --seed S --out DIR --counts ilv=N,planar=N,nsc=N,rfx=N,prog=N
       [--trunc 0.3]
Writes DIR/cases.bin and DIR/meta.json (sequence metadata, truncated variants linked to parents)."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import clear  # noqa: E402
import ilv  # noqa: E402
import nsc  # noqa: E402
import planar  # noqa: E402
import prog  # noqa: E402
import rfx  # noqa: E402
import zgfx  # noqa: E402

GEN = {"ilv": ilv, "planar": planar, "nsc": nsc, "rfx": rfx, "prog": prog, "clear": clear, "zgfx": zgfx}

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--counts", required=True)
ap.add_argument("--trunc", type=float, default=0.35, help="share of sequences that get truncated variants")
args = ap.parse_args()

counts = dict((k, int(v)) for k, v in (kv.split("=") for kv in args.counts.split(",")))
os.makedirs(args.out, exist_ok=True)
seqs = []
for ci, (name, n) in enumerate(sorted(counts.items())):
    r = common.rng(args.seed * 1000 + ci)
    made = GEN[name].make_sequences(r, n, seed_base=args.seed * 100000 + ci * 10000)
    for s in made:
        s.tags.insert(0, "src:" + name)
    seqs += made

next_id = 1
for s in seqs:
    s.seq_id = next_id
    next_id += 1

r = common.rng(args.seed * 7 + 3)
variants = []
for s in seqs:
    if r.random() >= args.trunc or len(s.steps[0].data) < 8:
        continue
    if s.codec == common.CODEC_IDS["zgfx"] and not any(t.startswith("multipart") for t in s.steps[0].tags):
        continue    # a cut single segment is just another segment; only declared lengths are checkable
    st0 = s.steps[0]
    for _ in range(r.randint(1, 2)):
        frac = r.uniform(0.1, 0.9)
        cut = max(1, min(len(st0.data) - 1, int(len(st0.data) * frac)))
        v = common.Seq(s.codec, s.dst_w, s.dst_h, s.dst_format, s.stride, s.fill_seed, s.ctx0, s.ctx1,
                       tags=s.tags + ["truncated"])
        v.add(common.Step(st0.params, st0.data[:cut], palette=st0.palette, kind="trunc",
                          tags=st0.tags + [f"cut{cut}/{len(st0.data)}"]))
        v.seq_id = next_id
        next_id += 1
        v.parent = [s.seq_id, 0]
        variants.append(v)
seqs += variants

with open(os.path.join(args.out, "cases.bin"), "wb") as f:
    for s in seqs:
        f.write(s.encode())
with open(os.path.join(args.out, "meta.json"), "w") as f:
    json.dump([s.meta() for s in seqs], f)
print(f"{len(seqs)} sequences ({len(variants)} truncated variants), "
      f"{os.path.getsize(os.path.join(args.out, 'cases.bin')) / 1e6:.1f} MB")
