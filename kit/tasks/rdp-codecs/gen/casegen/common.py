"""Shared pieces of the case generator: pixel formats, the SEQ1 record writer, small helpers."""
import random
import struct


def pixfmt(bpp, typ, a, r, g, b):
    return (bpp << 24) | (typ << 16) | (a << 12) | (r << 8) | (g << 4) | b


ARGB, ABGR, RGBA, BGRA = 1, 2, 3, 4
BGRA32 = pixfmt(32, BGRA, 8, 8, 8, 8)
BGRX32 = pixfmt(32, BGRA, 0, 8, 8, 8)
RGBA32 = pixfmt(32, RGBA, 8, 8, 8, 8)
RGBX32 = pixfmt(32, RGBA, 0, 8, 8, 8)
XRGB32 = pixfmt(32, ARGB, 0, 8, 8, 8)
ARGB32 = pixfmt(32, ARGB, 8, 8, 8, 8)
RGB24 = pixfmt(24, ARGB, 0, 8, 8, 8)
BGR24 = pixfmt(24, ABGR, 0, 8, 8, 8)
RGB16 = pixfmt(16, ARGB, 0, 5, 6, 5)
BGR16 = pixfmt(16, ABGR, 0, 5, 6, 5)
RGB15 = pixfmt(15, ARGB, 0, 5, 5, 5)

FORMAT_NAMES = {BGRA32: "BGRA32", BGRX32: "BGRX32", RGBA32: "RGBA32", RGBX32: "RGBX32", XRGB32: "XRGB32",
                ARGB32: "ARGB32", RGB24: "RGB24", BGR24: "BGR24", RGB16: "RGB16", BGR16: "BGR16",
                RGB15: "RGB15"}

CODECS = {1: "interleaved", 2: "planar", 3: "nsc", 4: "rfx", 5: "progressive", 6: "clear", 7: "zgfx"}
CODEC_IDS = {v: k for k, v in CODECS.items()}


def bytes_per_pixel(fmt):
    return ((fmt >> 24) + 7) // 8


class Step:
    def __init__(self, params, data, palette=None, kind="valid", tags=()):
        self.params = list(params) + [0] * (8 - len(params))
        self.data = bytes(data)
        self.palette = palette            # (format, [256 x u32]) or None
        self.kind = kind                  # "valid" or "trunc"
        self.tags = list(tags)


class Seq:
    def __init__(self, codec, dst_w, dst_h, dst_format, stride=0, fill_seed=0, ctx0=0, ctx1=0, tags=()):
        self.codec = CODEC_IDS[codec] if isinstance(codec, str) else codec
        self.dst_w, self.dst_h, self.dst_format = dst_w, dst_h, dst_format
        self.stride = stride or dst_w * bytes_per_pixel(dst_format)
        self.fill_seed = fill_seed
        self.ctx0, self.ctx1 = ctx0, ctx1
        self.steps = []
        self.tags = list(tags)
        self.seq_id = None
        self.parent = None                # for truncated variants: (seq_id, step index) of the clean parent

    def add(self, step):
        self.steps.append(step)
        return step

    def encode(self):
        out = bytearray()
        out += b"SEQ1"
        out += struct.pack("<IIIIIIIIII", self.seq_id, self.codec, self.dst_w, self.dst_h, self.dst_format,
                           self.stride, self.fill_seed & 0xFFFFFFFF, self.ctx0, self.ctx1, len(self.steps))
        for i, st in enumerate(self.steps):
            out += struct.pack("<I", i)
            out += struct.pack("<8I", *[p & 0xFFFFFFFF for p in st.params])
            if st.palette:
                pf, pal = st.palette
                out += struct.pack("<I", pf)
                out += struct.pack("<256I", *pal)
            else:
                out += struct.pack("<I", 0)
            out += struct.pack("<I", len(st.data))
            out += st.data
        return bytes(out)

    def meta(self):
        return {"seq": self.seq_id, "codec": CODECS[self.codec], "dst": [self.dst_w, self.dst_h],
                "format": FORMAT_NAMES.get(self.dst_format, hex(self.dst_format)), "stride": self.stride,
                "tags": self.tags, "parent": self.parent,
                "steps": [{"kind": s.kind, "len": len(s.data), "tags": s.tags} for s in self.steps]}


class BitWriter:
    """MSB-first bit writer (the order every bitstream in these formats uses)."""

    def __init__(self):
        self.buf = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, value, nbits):
        for i in range(nbits - 1, -1, -1):
            self.acc = (self.acc << 1) | ((value >> i) & 1)
            self.n += 1
            if self.n == 8:
                self.buf.append(self.acc)
                self.acc = 0
                self.n = 0

    def bits(self, bit, count):
        for _ in range(count):
            self.put(bit, 1)

    def getvalue(self):
        out = bytearray(self.buf)
        if self.n:
            out.append(self.acc << (8 - self.n))
        return bytes(out)

    def bitlen(self):
        return len(self.buf) * 8 + self.n


class BitReader:
    """MSB-first reader that returns zeros past the end (like winpr's wBitStream)."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def remaining(self):
        return len(self.data) * 8 - self.pos

    def get(self, nbits):
        v = 0
        for _ in range(nbits):
            byte = self.pos >> 3
            bit = 0
            if byte < len(self.data):
                bit = (self.data[byte] >> (7 - (self.pos & 7))) & 1
            v = (v << 1) | bit
            self.pos += 1
        return v


def rng(seed):
    return random.Random(seed)


def choose_weighted(r, items):
    total = sum(w for _, w in items)
    x = r.random() * total
    for v, w in items:
        x -= w
        if x <= 0:
            return v
    return items[-1][0]


def synth_plane(r, w, h, kind=None):
    """A byte plane with screen-like content: flat areas, gradients, text-like strokes, noise."""
    kind = kind or choose_weighted(r, [("flat", 2), ("gradient", 3), ("blocks", 3), ("noise", 1), ("strokes", 3)])
    base = r.randrange(256)
    p = [[base] * w for _ in range(h)]
    if kind == "gradient":
        dx, dy = r.uniform(-4, 4), r.uniform(-4, 4)
        for y in range(h):
            for x in range(w):
                p[y][x] = int(base + dx * x + dy * y) & 0xFF
    elif kind == "blocks":
        for _ in range(r.randrange(1, 8)):
            x0, y0 = r.randrange(w), r.randrange(h)
            x1, y1 = r.randrange(x0, w) + 1, r.randrange(y0, h) + 1
            v = r.randrange(256)
            for y in range(y0, y1):
                for x in range(x0, x1):
                    p[y][x] = v
    elif kind == "noise":
        for y in range(h):
            for x in range(w):
                p[y][x] = r.randrange(256)
    elif kind == "strokes":
        fg = r.randrange(256)
        for _ in range(r.randrange(1, 12)):
            if r.random() < 0.5:
                y = r.randrange(h)
                x0 = r.randrange(w)
                for x in range(x0, min(w, x0 + r.randrange(1, 20))):
                    p[y][x] = fg
            else:
                x = r.randrange(w)
                y0 = r.randrange(h)
                for y in range(y0, min(h, y0 + r.randrange(1, 20))):
                    p[y][x] = fg
    if kind != "noise" and r.random() < 0.3:
        for _ in range(r.randrange(1, max(2, w * h // 16))):
            p[r.randrange(h)][r.randrange(w)] = r.randrange(256)
    return p
