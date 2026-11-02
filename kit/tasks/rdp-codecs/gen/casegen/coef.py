"""Coefficient sources for RemoteFX / progressive tiles.

natural(): a 64x64 screen-like RGB tile pushed through YCbCr (11.5 fixed point) and the RemoteFX
forward 5/3 DWT (port of the reference encoder), giving realistic coefficients in the RemoteFX band
layout. synthetic(): sparse random coefficients with bounded magnitudes, for either band layout.
Values are in the "pre-quantization" domain (the decoder multiplies by 2^(q-1))."""
import math

# band layouts: (offset, count) in buffer order
RFX_BANDS = [(0, 1024), (1024, 1024), (2048, 1024), (3072, 256), (3328, 256), (3584, 256),
             (3840, 64), (3904, 64), (3968, 64), (4032, 64)]
EXT_BANDS = [(0, 1023), (1023, 1023), (2046, 961), (3007, 272), (3279, 272), (3551, 256),
             (3807, 72), (3879, 72), (3951, 64), (4015, 81)]
# level of each band (1 = finest), LL3 last
BAND_LEVEL = [1, 1, 1, 2, 2, 2, 3, 3, 3, 3]


def _i16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def _encode_block(buf, base, sw):
    """Port of rfx_dwt_2d_encode_block (one level, in place in buf[base:base+4*sw*sw])."""
    tw = sw << 1
    src = buf[base:base + tw * tw]
    dwt = [0] * (tw * tw)
    for x in range(tw):
        for n in range(sw):
            y = n << 1
            s0 = src[y * tw + x]
            s1 = src[(y + 1) * tw + x]
            s2 = src[(y + 2) * tw + x] if n < sw - 1 else s0
            h = (s1 - ((s0 + s2) >> 1)) >> 1
            dwt[(n + sw) * tw + x] = h
            hp = dwt[(n - 1 + sw) * tw + x] if n > 0 else h
            dwt[n * tw + x] = s0 + (h if n == 0 else (hp + h) >> 1)
    hl, lh, hh, ll = [], [], [], []
    for y in range(sw):
        lrow = dwt[y * tw:(y + 1) * tw]
        hrow = dwt[(y + sw) * tw:(y + sw + 1) * tw]
        hlr, llr, hhr, lhr = [], [], [], []
        for n in range(sw):
            x = n << 1
            a = (lrow[x + 1] - ((lrow[x] + lrow[x + 2 if n < sw - 1 else x]) >> 1)) >> 1
            hlr.append(a)
            llr.append(lrow[x] + (a if n == 0 else (hlr[n - 1] + a) >> 1))
            b = (hrow[x + 1] - ((hrow[x] + hrow[x + 2 if n < sw - 1 else x]) >> 1)) >> 1
            hhr.append(b)
            lhr.append(hrow[x] + (b if n == 0 else (hhr[n - 1] + b) >> 1))
        hl += hlr
        ll += llr
        hh += hhr
        lh += lhr
    q = sw * sw
    buf[base:base + q] = hl
    buf[base + q:base + 2 * q] = lh
    buf[base + 2 * q:base + 3 * q] = hh
    buf[base + 3 * q:base + 4 * q] = ll


def forward_dwt(plane):
    """plane: 4096 ints (64x64, row major) -> 4096 coefficients in the RemoteFX band order."""
    buf = list(plane)
    _encode_block(buf, 0, 32)
    _encode_block(buf, 3072, 16)
    _encode_block(buf, 3840, 8)
    return buf


def rgb_tile(r):
    """64x64 RGB tile with screen-like content."""
    kind = r.choice(["flat", "gradient", "window", "text", "photo"])
    c0 = [r.randrange(256) for _ in range(3)]
    px = [[list(c0) for _ in range(64)] for _ in range(64)]
    if kind == "gradient":
        d = [(r.uniform(-3, 3), r.uniform(-3, 3)) for _ in range(3)]
        for y in range(64):
            for x in range(64):
                px[y][x] = [max(0, min(255, int(c0[k] + d[k][0] * x + d[k][1] * y))) for k in range(3)]
    elif kind in ("window", "text"):
        for _ in range(r.randrange(2, 10)):
            x0, y0 = r.randrange(64), r.randrange(64)
            x1, y1 = min(64, x0 + r.randrange(2, 40)), min(64, y0 + r.randrange(2, 40))
            c = [r.randrange(256) for _ in range(3)]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    px[y][x] = list(c)
        if kind == "text":
            fg = [r.randrange(80) for _ in range(3)]
            for _ in range(r.randrange(20, 120)):
                x, y = r.randrange(64), r.randrange(64)
                for k in range(r.randrange(1, 6)):
                    if x + k < 64:
                        px[y][x + k] = list(fg)
    elif kind == "photo":
        fx = [r.uniform(0.05, 0.4) for _ in range(6)]
        for y in range(64):
            for x in range(64):
                px[y][x] = [max(0, min(255, int(128 + 60 * math.sin(fx[k] * x + fx[k + 3] * y) +
                                                r.gauss(0, 8)))) for k in range(3)]
    return px


def ycbcr(px):
    """RGB -> Y, Cb, Cr in 11.5 fixed point (Y centred on zero), like the reference encoder."""
    Y, Cb, Cr = [], [], []
    for row in px:
        for (R, G, B) in row:
            Y.append(int(round((0.299 * R + 0.587 * G + 0.114 * B - 128) * 32)))
            Cb.append(int(round((-0.168935 * R - 0.331665 * G + 0.500590 * B) * 32)))
            Cr.append(int(round((0.499813 * R - 0.418531 * G - 0.081282 * B) * 32)))
    return Y, Cb, Cr


def quantize(coefs, shifts, bands=RFX_BANDS):
    """Divide each band by 2^shift with rounding (shift = q - 1 for the decoder's << (q - 1))."""
    out = list(coefs)
    for (off, cnt), s in zip(bands, shifts):
        for i in range(off, off + cnt):
            v = out[i]
            if s > 0:
                v = (v + (1 << (s - 1))) >> s if v >= 0 else -((-v + (1 << (s - 1))) >> s)
            out[i] = v
    return out


def natural(r, shifts_y, shifts_cb, shifts_cr):
    """Three quantized coefficient arrays (RemoteFX layout) for one realistic tile."""
    Y, Cb, Cr = ycbcr(rgb_tile(r))
    return [quantize(forward_dwt(p), s) for p, s in ((Y, shifts_y), (Cb, shifts_cb), (Cr, shifts_cr))]


def synthetic(r, shifts, layout="rfx", density=None):
    """Sparse random coefficients whose dequantized magnitude stays well inside int16."""
    bands = RFX_BANDS if layout == "rfx" else EXT_BANDS
    density = density if density is not None else r.choice([0.02, 0.1, 0.3, 0.6])
    out = [0] * 4096
    for bi, ((off, cnt), s) in enumerate(zip(bands, shifts)):
        last = bi == 9
        limit = (1 << 11) if last else (1 << 9)
        mx = max(1, limit >> s)
        for i in range(off, off + cnt):
            if last:
                out[i] = r.randint(-mx, mx) if r.random() < 0.9 else 0
            elif r.random() < density * (1.5 if BAND_LEVEL[bi] == 3 else 1.0):
                v = max(1, min(mx, int(abs(r.gauss(0, mx / 4)) + 1)))
                out[i] = v if r.random() < 0.5 else -v
    return out
