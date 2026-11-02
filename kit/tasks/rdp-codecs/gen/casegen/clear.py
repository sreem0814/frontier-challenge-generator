"""ClearCodec bitmaps (MS-RDPEGFX 2.2.4.1): residual layer, bands of V-bars with the V-bar and short
V-bar caches, subcodec layer (raw BGR, NSCodec, RLEX), glyph cache. Several calls share one context."""
import struct

import nsc
from common import (BGRA32, BGRX32, RGBA32, RGBX32, Seq, Step, bytes_per_pixel, choose_weighted,
                    synth_plane)

GLYPH_INDEX, GLYPH_HIT, CACHE_RESET = 0x01, 0x02, 0x04
VBAR_SIZE, SHORT_SIZE = 32768, 16384


def rlf(n):
    """Run-length factor encoding: u8, or 0xFF + u16, or 0xFF 0xFFFF + u32."""
    if n < 0xFF:
        return bytes([n])
    if n < 0xFFFF:
        return b"\xff" + struct.pack("<H", n)
    return b"\xff\xff\xff" + struct.pack("<I", n)


def color(r, pal):
    return r.choice(pal) if r.random() < 0.85 else (r.randrange(256), r.randrange(256), r.randrange(256))


def residual(r, w, h, pal):
    out = bytearray()
    left = w * h
    while left:
        n = min(left, choose_weighted(r, [(r.randint(1, 20), 3), (r.randint(21, 400), 2), (r.randint(401, 70000), 1)]))
        b, g, rr = color(r, pal)
        out += bytes([b, g, rr]) + rlf(n)
        left -= n
    return bytes(out)


class Caches:
    def __init__(self):
        self.vbar = {}              # index -> height
        self.short = {}             # index -> pixel count
        self.vcur = 0
        self.scur = 0


def bands(r, w, h, pal, caches):
    out = bytearray()
    for _ in range(r.randint(1, 4)):
        bh = r.randint(1, min(52, h))
        y0 = r.randint(0, h - bh)
        bw = r.randint(1, min(w, 48))
        x0 = r.randint(0, w - bw)
        bkg = color(r, pal)
        out += struct.pack("<HHHH", x0, x0 + bw - 1, y0, y0 + bh - 1) + bytes(bkg)
        for _ in range(bw):
            hits = [i for i, hh in caches.vbar.items() if hh == bh]
            shorts = [(i, c) for i, c in caches.short.items() if c <= bh]
            kind = choose_weighted(r, [("miss", 3), ("shorthit", 2 if shorts else 0), ("vbarhit", 3 if hits else 0)])
            if kind == "vbarhit":
                out += struct.pack("<H", 0x8000 | r.choice(hits))
                continue
            if kind == "shorthit":
                idx, cnt = r.choice(shorts)
                yon = r.randint(0, bh - cnt)
                out += struct.pack("<H", 0x4000 | idx) + bytes([yon])
            else:
                cnt = r.randint(0, min(bh, 52))
                yon = r.randint(0, bh - cnt)
                out += struct.pack("<H", yon | ((yon + cnt) << 8))
                for _ in range(cnt):
                    out += bytes(color(r, pal))
                caches.short[caches.scur] = cnt
                caches.scur = (caches.scur + 1) % SHORT_SIZE
            caches.vbar[caches.vcur] = bh
            caches.vcur = (caches.vcur + 1) % VBAR_SIZE
    return bytes(out)


def rlex(r, w, h):
    n = r.randint(1, 127)
    pal = [(r.randrange(256), r.randrange(256), r.randrange(256)) for _ in range(n)]
    bits = (n - 1).bit_length() if n > 1 else 1
    out = bytearray([n]) + b"".join(bytes(c) for c in pal)
    left = w * h
    while left:
        depth_max = min(n - 1, left - 1, (1 << (8 - bits)) - 1)
        depth = r.randint(0, depth_max) if r.random() < 0.6 else 0
        stop = r.randint(depth, n - 1)
        run = min(left - depth - 1, choose_weighted(r, [(r.randint(0, 10), 3), (r.randint(11, 300), 2), (r.randint(301, 70000), 1)]))
        out += bytes([stop | (depth << bits)]) + rlf(run)
        left -= run + depth + 1
    return bytes(out)


def subcodecs(r, w, h):
    out = bytearray()
    for _ in range(r.randint(1, 3)):
        sw, sh = r.randint(1, min(w, 96)), r.randint(1, min(h, 64))
        x0, y0 = r.randint(0, w - sw), r.randint(0, h - sh)
        sid = choose_weighted(r, [(0, 2), (1, 2), (2, 3)])
        if sid == 0:
            planes = [synth_plane(r, sw, sh) for _ in range(3)]
            data = bytes(planes[k][y][x] for y in range(sh) for x in range(sw) for k in range(3))
        elif sid == 1:
            modes = [choose_weighted(r, [("rle", 3), ("raw", 1)]) for _ in range(4)]
            data = nsc.make_stream(r, sw, sh, r.randint(1, 7), r.random() < 0.5,
                                   choose_weighted(r, [("opaque", 2), ("plane", 1), ("absent", 2)]), modes)
        else:
            data = rlex(r, sw, sh)
        out += struct.pack("<HHHHIB", x0, y0, sw, sh, len(data), sid) + data
    return bytes(out)


def make_sequences(r, count, seed_base):
    seqs = []
    for i in range(count):
        W = choose_weighted(r, [(r.randint(16, 128), 2), (r.randint(129, 400), 2)])
        H = choose_weighted(r, [(r.randint(16, 96), 2), (r.randint(97, 260), 1)])
        fmt = choose_weighted(r, [(BGRX32, 4), (BGRA32, 3), (RGBX32, 1), (RGBA32, 1)])
        pad = r.choice([0, 0, 0, 16])
        seq = Seq("clear", W, H, fmt, stride=W * bytes_per_pixel(fmt) + pad, fill_seed=seed_base + i,
                  tags=["clear"])
        caches = Caches()
        glyphs = {}
        seqn = r.randrange(256)
        pal = [(r.randrange(256), r.randrange(256), r.randrange(256)) for _ in range(r.randint(2, 8))]
        for m in range(choose_weighted(r, [(1, 1), (3, 2), (6, 2), (10, 1)])):
            tags = []
            if glyphs and r.random() < 0.25:
                gi = r.choice(sorted(glyphs))
                w, h = glyphs[gi]
                x, y = r.randint(0, W - w), r.randint(0, H - h)
                data = bytes([GLYPH_INDEX | GLYPH_HIT, seqn]) + struct.pack("<H", gi)
                tags.append("glyph-hit")
            else:
                glyph = r.random() < 0.25
                if glyph:
                    w, h = r.randint(1, min(W, 32)), r.randint(1, min(H, 32))
                    while w * h > 1024:
                        h -= 1
                else:
                    w = r.randint(1, min(W, choose_weighted(r, [(64, 2), (400, 1)])))
                    h = r.randint(1, min(H, choose_weighted(r, [(64, 2), (260, 1)])))
                x, y = r.randint(0, W - w), r.randint(0, H - h)
                flags = 0
                if r.random() < 0.1:
                    flags |= CACHE_RESET
                    caches.vcur = caches.scur = 0
                    tags.append("cache-reset")
                gi = None
                if glyph:
                    flags |= GLYPH_INDEX
                    gi = r.randrange(4000)
                    tags.append("glyph-index")
                layers = []
                while not layers:
                    layers = [k for k, p in (("residual", 0.75), ("bands", 0.6), ("subcodec", 0.5)) if r.random() < p]
                res = residual(r, w, h, pal) if "residual" in layers else b""
                bnd = bands(r, w, h, pal, caches) if "bands" in layers else b""
                sub = subcodecs(r, w, h) if "subcodec" in layers else b""
                data = bytes([flags, seqn]) + (struct.pack("<H", gi) if glyph else b"")
                data += struct.pack("<III", len(res), len(bnd), len(sub)) + res + bnd + sub
                if glyph:
                    glyphs[gi] = (w, h)
                tags += layers
            seqn = (seqn + 1) % 256
            seq.add(Step([w, h, x, y], data, tags=tags))
        seqs.append(seq)
    return seqs
