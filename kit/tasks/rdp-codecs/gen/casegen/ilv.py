"""Interleaved RLE (RLE_BITMAP_STREAM) streams: random but well-formed order sequences."""
import struct

from common import (BGR24, BGRA32, BGRX32, RGB16, RGBA32, RGBX32, XRGB32, Seq, Step, bytes_per_pixel,
                    choose_weighted)

PIXEL_BYTES = {8: 1, 15: 2, 16: 2, 24: 3}


def pix(bpp, v):
    n = PIXEL_BYTES[bpp]
    if bpp == 15:
        v &= 0x7FFF
    return (v & ((1 << (8 * n)) - 1)).to_bytes(n, "little")


class RleWriter:
    def __init__(self, r, bpp, total, style):
        self.r, self.bpp, self.total, self.style = r, bpp, total, style
        self.out = bytearray()
        self.pos = 0
        self.colors = [r.getrandbits(24) for _ in range(r.randrange(2, 9))]
        self.counts = {}

    def color(self):
        if self.r.random() < 0.8:
            return self.r.choice(self.colors)
        return self.r.getrandbits(24)

    def remaining(self):
        return self.total - self.pos

    def length(self, lo, hi, big=False):
        """Pick a run length in [lo, hi] (hi already capped by the remaining pixels)."""
        if hi < lo:
            return None
        r = self.r
        if big and r.random() < 0.5:
            return r.randint(lo, hi)
        cap = min(hi, choose_weighted(r, [(8, 4), (31, 4), (287, 2), (4000, 1)]))
        if cap < lo:
            cap = hi
        return r.randint(lo, max(lo, cap))

    # -- length encodings ---------------------------------------------------------------------------------
    def regular(self, code, n, mega_code):
        """BG/FG/COLOR runs and COLOR_IMAGE: 5-bit length, extended (+32) or MEGA_MEGA 16-bit."""
        r = self.r
        forms = []
        if 1 <= n <= 31:
            forms.append("short")
        if 32 <= n <= 287:
            forms.append("ext")
        if 1 <= n <= 0xFFFF:
            forms.append("mega")
        f = r.choice(forms) if r.random() < 0.3 else forms[0]
        if f == "short":
            self.out.append((code << 5) | n)
        elif f == "ext":
            self.out += bytes([code << 5, n - 32])
        else:
            self.out.append(mega_code)
            self.out += struct.pack("<H", n)

    def lite(self, code, n, mega_code):
        """SET_FG_FG_RUN and DITHERED_RUN: 4-bit length, extended (+16) or MEGA_MEGA."""
        r = self.r
        forms = []
        if 1 <= n <= 15:
            forms.append("short")
        if 16 <= n <= 271:
            forms.append("ext")
        if 1 <= n <= 0xFFFF:
            forms.append("mega")
        f = r.choice(forms) if r.random() < 0.3 else forms[0]
        if f == "short":
            self.out.append((code << 4) | n)
        elif f == "ext":
            self.out += bytes([code << 4, n - 16])
        else:
            self.out.append(mega_code)
            self.out += struct.pack("<H", n)

    def fgbg_len(self, n, regular, mega_code):
        """FGBG image lengths: header units of 8 pixels, extended (+1) or MEGA_MEGA."""
        r = self.r
        unit_max = 31 if regular else 15
        forms = []
        if n % 8 == 0 and 1 <= n // 8 <= unit_max:
            forms.append("units")
        if 1 <= n <= 256:
            forms.append("ext")
        forms.append("mega")
        f = r.choice(forms) if r.random() < 0.3 else forms[0]
        code = 0x2 if regular else 0xD
        if f == "units":
            self.out.append(((code << 5) if regular else (code << 4)) | (n // 8))
        elif f == "ext":
            self.out += bytes([(code << 5) if regular else (code << 4), n - 1])
        else:
            self.out.append(mega_code)
            self.out += struct.pack("<H", n)

    # -- orders ---------------------------------------------------------------------------------------------
    def emit(self):
        r = self.r
        rem = self.remaining()
        weights = {
            "mixed": [("bg", 3), ("fg", 2), ("setfg", 2), ("dither", 1), ("color", 3), ("image", 3),
                      ("fgbg", 3), ("setfgbg", 2), ("special", 1), ("wb", 1)],
            "runs": [("bg", 4), ("fg", 3), ("setfg", 2), ("color", 4), ("dither", 1), ("wb", 1)],
            "image": [("image", 6), ("color", 2), ("bg", 1), ("wb", 1)],
            "fgbg": [("fgbg", 5), ("setfgbg", 3), ("special", 2), ("bg", 2), ("fg", 1), ("setfg", 1)],
        }[self.style]
        kind = choose_weighted(r, weights)
        if kind in ("special",) and rem < 8:
            kind = "wb"
        if kind == "dither" and rem < 2:
            kind = "wb"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        bpp = self.bpp
        if kind == "bg":
            n = self.length(1, rem)
            self.regular(0x0, n, 0xF0)
        elif kind == "fg":
            n = self.length(1, rem)
            self.regular(0x1, n, 0xF1)
        elif kind == "color":
            n = self.length(1, rem)
            self.regular(0x3, n, 0xF3)
            self.out += pix(bpp, self.color())
        elif kind == "image":
            n = self.length(1, min(rem, 300))
            self.regular(0x4, n, 0xF4)
            for _ in range(n):
                self.out += pix(bpp, self.color())
        elif kind == "setfg":
            n = self.length(1, rem)
            self.lite(0xC, n, 0xF6)
            self.out += pix(bpp, self.color())
        elif kind == "dither":
            n = self.length(1, rem // 2)
            self.lite(0xE, n, 0xF8)
            self.out += pix(bpp, self.color()) + pix(bpp, self.color())
            n *= 2
        elif kind in ("fgbg", "setfgbg"):
            n = self.length(1, min(rem, 400))
            if kind == "fgbg":
                self.fgbg_len(n, True, 0xF2)
            else:
                self.fgbg_len(n, False, 0xF7)
                self.out += pix(bpp, self.color())
            for _ in range((n + 7) // 8):
                self.out.append(r.getrandbits(8))
        elif kind == "special":
            self.out.append(r.choice([0xF9, 0xFA]))
            n = 8
        else:
            self.out.append(r.choice([0xFD, 0xFE]))
            n = 1
        self.pos += n

    def run(self):
        while self.remaining() > 0:
            self.emit()
        return bytes(self.out)


def palette(r):
    fmt = r.choice([BGRX32, XRGB32])
    return fmt, [r.getrandbits(24) | 0xFF000000 for _ in range(256)]


def make_sequences(r, count, seed_base):
    """Bitmap-update style calls (gdi/graphics.c): one bitmap per call, decoded bottom-up."""
    seqs = []
    for i in range(count):
        nsteps = 1 if r.random() < 0.8 else r.randint(2, 4)
        fmt = choose_weighted(r, [(BGRX32, 4), (BGRA32, 2), (RGBX32, 1), (RGBA32, 1), (BGR24, 1), (RGB16, 1)])
        steps = []
        surf_w = surf_h = 0
        for _ in range(nsteps):
            bpp = choose_weighted(r, [(24, 3), (16, 3), (15, 2), (8, 2)])
            w = choose_weighted(r, [(r.randint(1, 16), 1), (r.choice([16, 32, 48, 64]), 3), (r.randint(17, 64), 3)])
            h = choose_weighted(r, [(r.randint(1, 16), 1), (r.choice([16, 32, 48, 64]), 3), (r.randint(17, 64), 3)])
            style = choose_weighted(r, [("mixed", 5), ("runs", 2), ("image", 2), ("fgbg", 2)])
            rle = RleWriter(r, bpp, w * h, style)
            data = rle.run()
            dw = w - r.randint(1, 3) if (w > 4 and r.random() < 0.25) else w
            offset = r.random() < 0.3
            x = r.randint(0, 40) if offset else 0
            y = r.randint(0, 40) if offset else 0
            steps.append((bpp, w, h, dw, x, y, data, style, rle.counts))
            surf_w, surf_h = max(surf_w, x + dw), max(surf_h, y + h)
        pad = r.choice([0, 0, 0, 4, 16, 64])
        seq = Seq("interleaved", surf_w, surf_h, fmt, stride=surf_w * bytes_per_pixel(fmt) + pad,
                  fill_seed=seed_base + i, tags=["ilv"])
        for bpp, w, h, dw, x, y, data, style, counts in steps:
            pal = palette(r) if bpp == 8 else None
            seq.add(Step([w, h, bpp, x, y, dw, h], data, palette=pal,
                         tags=[f"bpp{bpp}", style] + sorted(counts)))
        seqs.append(seq)
    return seqs
