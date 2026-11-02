"""NSCodec bitmap streams (MS-RDPNSC 2.2.2): AYCoCg planes, color loss, chroma subsampling, plane RLE."""
import struct

from common import (BGR24, BGRA32, BGRX32, RGB16, RGBA32, RGBX32, Seq, Step, bytes_per_pixel,
                    choose_weighted, synth_plane)


def rle_encode(r, data):
    """NSCodec plane RLE: literal bytes, runs as value,value,len-2 (or 0xFF + u32 len); last 4 bytes raw."""
    n = len(data)
    out = bytearray()
    i = 0
    while n - i > 4:
        if n - i == 5:
            out.append(data[i])
            i += 1
            continue
        j = i
        while j < n - 4 and data[j] == data[i]:
            j += 1
        run = j - i
        if run >= 2:
            if run > 3 and r.random() < 0.15:          # split a long run in two
                run = r.randint(2, run - 2)
            if run - 2 < 0xFF and r.random() < 0.9:
                out += bytes([data[i], data[i], run - 2])
            else:
                out += bytes([data[i], data[i], 0xFF]) + struct.pack("<I", run)
            i += run
        else:
            out.append(data[i])
            i += 1
    out += bytes(data[n - 4:])
    return bytes(out)


def flatten(p):
    return bytes(v for row in p for v in row)


def make_stream(r, w, h, cll, cs, alpha_mode, plane_modes):
    tw = (w + 7) // 8 * 8
    th = (h + 1) // 2 * 2
    if cs:
        y = synth_plane(r, tw, h)
        co = synth_plane(r, tw // 2, th // 2, r.choice(["flat", "gradient", "blocks", "noise"]))
        cg = synth_plane(r, tw // 2, th // 2, r.choice(["flat", "gradient", "blocks", "noise"]))
    else:
        y = synth_plane(r, w, h)
        co = synth_plane(r, w, h, r.choice(["flat", "gradient", "blocks", "noise"]))
        cg = synth_plane(r, w, h, r.choice(["flat", "gradient", "blocks", "noise"]))
    if alpha_mode == "opaque":
        a = [[255] * w for _ in range(h)]
    else:
        a = synth_plane(r, w, h, r.choice(["flat", "blocks", "gradient", "noise"]))
    planes = [flatten(y), flatten(co), flatten(cg), flatten(a)]
    counts, body = [], bytearray()
    for idx, (pl, mode) in enumerate(zip(planes, plane_modes)):
        if idx == 3 and alpha_mode == "absent":
            counts.append(0)                            # no alpha plane: decoder fills 0xFF
            continue
        enc = rle_encode(r, pl) if len(pl) > 4 else pl
        if mode == "rle" and len(enc) < len(pl):
            counts.append(len(enc))
            body += enc
        else:
            counts.append(len(pl))                      # raw plane
            body += pl
    hdr = struct.pack("<4IBBH", *counts, cll, 1 if cs else 0, 0)
    return hdr + bytes(body)


def make_sequences(r, count, seed_base):
    """Surface-bits style calls (gdi.c / graphics.c / clear.c): bpp 32, flip vertical or none."""
    seqs = []
    for i in range(count):
        fmt = choose_weighted(r, [(BGRX32, 4), (BGRA32, 3), (RGBX32, 1), (RGBA32, 1), (BGR24, 1), (RGB16, 1)])
        nsteps = 1 if r.random() < 0.7 else r.randint(2, 4)
        calls = []
        for _ in range(nsteps):
            w = choose_weighted(r, [(r.randint(1, 16), 1), (r.randint(17, 64), 3), (r.randint(65, 192), 2)])
            h = choose_weighted(r, [(r.randint(1, 16), 1), (r.randint(17, 64), 3), (r.randint(65, 128), 1)])
            calls.append((w, h))
        sw = max(c[0] for c in calls) + r.choice([0, 0, r.randint(1, 64)])
        sh = max(c[1] for c in calls) + r.choice([0, 0, r.randint(1, 48)])
        pad = r.choice([0, 0, 0, 8, 32])
        seq = Seq("nsc", sw, sh, fmt, stride=sw * bytes_per_pixel(fmt) + pad, fill_seed=seed_base + i,
                  tags=["nsc"])
        for w, h in calls:
            cll = r.randint(1, 7)
            cs = r.random() < 0.5
            alpha_mode = choose_weighted(r, [("opaque", 2), ("plane", 2), ("absent", 1)])
            modes = [choose_weighted(r, [("rle", 3), ("raw", 1)]) for _ in range(4)]
            data = make_stream(r, w, h, cll, cs, alpha_mode, modes)
            # destination origin. Only unflipped bitmaps may run past the bottom edge (clipped rows); the
            # oracle's copy is not well defined for right-edge clipping or for flipped clipped bitmaps.
            flip = 1 if r.random() < 0.7 else 0
            x = r.randint(0, sw - w)
            if not flip and r.random() < 0.3:
                y = r.randint(0, sh - 1)
            else:
                y = r.randint(0, sh - h)
            tags = [f"cll{cll}", "cs" if cs else "nocs", "alpha-" + alpha_mode, "flip" if flip else "noflip"]
            seq.add(Step([w, h, x, y, flip], data, tags=tags))
        seqs.append(seq)
    return seqs
