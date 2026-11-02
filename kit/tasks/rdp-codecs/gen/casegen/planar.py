"""Planar bitmap streams (MS-RDPEGDI 2.2.2.5.1): raw or RLE planes, optional alpha, RGB or YCoCg with
color loss and chroma subsampling."""
from common import (BGR24, BGRA32, BGRX32, RGB16, RGBA32, RGBX32, Seq, Step, bytes_per_pixel,
                    choose_weighted, synth_plane)


def delta_code(v):
    """Signed delta -> planar delta byte (LSB is the sign)."""
    if v >= 0:
        return (v << 1) & 0xFF
    return ((-v - 1) << 1 | 1) & 0xFF


def rle_plane(r, plane, w, h):
    """Encode one plane with planar RLE: control byte = raw count (high nibble) / run length (low)."""
    out = bytearray()
    prev = None
    for y in range(h):
        row = plane[y]
        if prev is None:
            codes = list(row)                       # absolute values
            vals = list(row)
        else:
            vals = []
            for x in range(w):
                d = row[x] - prev[x]
                if d > 127:
                    d -= 256
                elif d < -128:
                    d += 256
                vals.append(d)                      # signed deltas (wrap to a byte)
            codes = [delta_code(d) for d in vals]
        x = 0
        last = 0                                    # the decoder's running "pixel" (value or delta)
        min_run = r.choice([3, 3, 4, 6])
        while x < w:
            # take raw values until a run of >= min_run equal values starts
            raw = []
            while x < w and len(raw) < 15:
                j = x
                while j < w and vals[j] == vals[x]:
                    j += 1
                runlen = j - x
                cur = vals[raw[-1]] if raw else last
                if runlen >= min_run:
                    if vals[x] != cur:              # one raw value, then the run repeats it
                        raw.append(x)
                        x += 1
                    break
                raw.append(x)
                x += 1
            # run that repeats the last emitted value
            v = vals[raw[-1]] if raw else last
            run = 0
            while x + run < w and vals[x + run] == v:
                run += 1
            if raw:
                last = vals[raw[-1]]
            # first control byte carries the raw bytes and a short run (0 or 3..15)
            first_run = run if 3 <= run <= 15 else (15 if run > 15 else 0)
            if first_run and r.random() < 0.15 and raw:
                first_run = 0
            out.append((len(raw) << 4) | first_run)
            out += bytes(codes[i] for i in raw)
            done = first_run
            x += first_run
            rest = run - done
            while rest >= 3:
                if rest >= 16 and r.random() < 0.8:
                    n = min(rest, 47)
                    if n >= 32:
                        out.append(((n - 32) << 4) | 2)
                    else:
                        out.append(((n - 16) << 4) | 1)
                else:
                    n = min(rest, 15)
                    out.append(n)                   # zero raw bytes, run n
                rest -= n
                x += n
                done += n
            # 1 or 2 leftover equal values are picked up as raw values by the next control byte
        prev = row
    return bytes(out)


def ycocg_planes(r, w, h):
    y = synth_plane(r, w, h)
    co = synth_plane(r, w, h, r.choice(["flat", "gradient", "blocks", "noise"]))
    cg = synth_plane(r, w, h, r.choice(["flat", "gradient", "blocks", "noise"]))
    return y, co, cg


def subsample(p, w, h):
    sw, sh = (w + 1) // 2, (h + 1) // 2
    return [[p[min(h - 1, 2 * yy)][min(w - 1, 2 * xx)] for xx in range(sw)] for yy in range(sh)], sw, sh


def make_stream(r, w, h, rle, alpha, cll, cs):
    header = (cll & 7) | (8 if cs else 0) | (0x10 if rle else 0) | (0 if alpha else 0x20)
    if cll:
        p0, p1, p2 = ycocg_planes(r, w, h)
    else:
        p0, p1, p2 = synth_plane(r, w, h), synth_plane(r, w, h), synth_plane(r, w, h)
    planes = []
    if alpha:
        a = synth_plane(r, w, h, r.choice(["flat", "flat", "blocks", "gradient", "noise"]))
        if r.random() < 0.4:
            a = [[255] * w for _ in range(h)]
        planes.append((a, w, h))
    planes.append((p0, w, h))
    if cs:
        s1, sw, sh = subsample(p1, w, h)
        s2, _, _ = subsample(p2, w, h)
        planes.append((s1, sw, sh))
        planes.append((s2, sw, sh))
    else:
        planes.append((p1, w, h))
        planes.append((p2, w, h))
    out = bytearray([header])
    for p, pw, ph in planes:
        if rle:
            out += rle_plane(r, p, pw, ph)
        else:
            for row in p:
                out += bytes(row)
    if not rle and r.random() < 0.5:
        out.append(0)                               # trailing pad byte
    return bytes(out)


def make_sequences(r, count, seed_base):
    seqs = []
    for i in range(count):
        profile = choose_weighted(r, [("bitmap", 3), ("gfx", 2)])
        fmt = choose_weighted(r, [(BGRX32, 4), (BGRA32, 3), (RGBX32, 1), (RGBA32, 1), (BGR24, 1), (RGB16, 1)])
        nsteps = 1 if r.random() < 0.75 else r.randint(2, 3)
        calls = []
        for _ in range(nsteps):
            rle = r.random() < 0.7
            alpha = r.random() < 0.4
            if profile == "bitmap":
                w = choose_weighted(r, [(r.randint(1, 16), 1), (r.choice([32, 64]), 2), (r.randint(17, 64), 3)])
                h = choose_weighted(r, [(r.randint(1, 16), 1), (r.choice([32, 64]), 2), (r.randint(17, 64), 3)])
                cll = r.randint(1, 7) if r.random() < 0.45 else 0
                cs = cll and r.random() < 0.5
            else:
                w = choose_weighted(r, [(r.randint(1, 64), 2), (r.randint(65, 200), 2)])
                h = choose_weighted(r, [(r.randint(1, 64), 2), (r.randint(65, 160), 1)])
                cll, cs = 0, False
            calls.append((w, h, rle, alpha, cll, cs))
        if profile == "bitmap":
            sw = max(c[0] for c in calls)
            sh = max(c[1] for c in calls)
        else:
            sw = max(c[0] for c in calls) + r.randint(0, 80)
            sh = max(c[1] for c in calls) + r.randint(0, 60)
        pad = r.choice([0, 0, 0, 8, 32])
        seq = Seq("planar", sw, sh, fmt, stride=sw * bytes_per_pixel(fmt) + pad, fill_seed=seed_base + i,
                  ctx0=sw, ctx1=sh, tags=["planar", profile])
        for w, h, rle, alpha, cll, cs in calls:
            data = make_stream(r, w, h, rle, alpha, cll, cs)
            if profile == "bitmap":
                params = [w, h, 0, 0, w, h, 1]
            else:
                params = [w, h, r.randint(0, sw - w), r.randint(0, sh - h), w, h, 0]
            tags = ["rle" if rle else "raw", "alpha" if alpha else "noalpha", f"cll{cll}"] + (["cs"] if cs else [])
            seq.add(Step(params, data, tags=tags))
        seqs.append(seq)
    return seqs
