"""imgcmp: decode 8-bit PNGs and compare two renderings with an anti-aliasing allowance.

Pure Python standard library (zlib only). Used by selfcheck.py; the grader applies the same rule.

Rule for one case (both images converted to premultiplied RGBA, 0-255 per channel):
  * the sizes must be equal;
  * a pixel is "off" when some channel differs by more than TOL from the expected pixel AND the
    difference is not explained by an edge moving by up to one pixel: the candidate value must lie
    within [min - TOL, max + TOL] of the expected 3x3 neighbourhood, and the expected value within
    the same band around the candidate's 3x3 neighbourhood, for every channel;
  * the case passes when the number of off pixels is at most max_off(width, height).
"""
import struct
import zlib

TOL = 10                # per-channel slack, premultiplied 0-255 scale
EDGE_TOL = 96           # larger slack on pixels that sit on an edge in both images ...
EDGE_CONTRAST = 64      # ... where an edge means a 3x3 neighbourhood spanning at least this much
OFF_FRACTION = 0.0005   # off pixels allowed: 0.05 % of the image ...
OFF_MIN = 4             # ... but never fewer than this many


def max_off(width, height):
    return max(OFF_MIN, int(width * height * OFF_FRACTION))


class PngError(ValueError):
    pass


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_png(data):
    """Return (width, height, straight-alpha RGBA bytes) for any non-interlaced PNG.

    Bit depths 1, 2, 4, 8 and 16 and all five colour types are accepted (16-bit samples keep their
    high byte; tRNS is honoured). Interlaced (Adam7) images are rejected.
    """
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError("not a PNG file")
    pos, idat, plte, trns, ihdr = 8, [], None, None, None
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if len(body) != n:
            raise PngError("truncated chunk")
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + n
    if ihdr is None or not idat:
        raise PngError("missing IHDR or IDAT")
    w, h, depth, ctype, comp, filt, interlace = ihdr
    ok_depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if ctype not in ok_depths or depth not in ok_depths[ctype] or comp or filt:
        raise PngError(f"invalid PNG header (depth {depth}, colour type {ctype})")
    if interlace:
        raise PngError("interlaced PNG is not supported")
    if not (0 < w <= 16384 and 0 < h <= 16384):
        raise PngError("bad image size")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bits = channels * depth
    bpp = max(1, bits // 8)
    stride = (w * bits + 7) // 8
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as e:
        raise PngError(f"bad zlib stream: {e}")
    if len(raw) < (stride + 1) * h:
        raise PngError("not enough image data")
    out = bytearray(stride * h)
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        ft = raw[base]
        line = bytearray(raw[base + 1:base + 1 + stride])
        if ft == 0:
            pass
        elif ft == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ft == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, prev))
        elif ft == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ft == 4:
            for i in range(stride):
                if i >= bpp:
                    line[i] = (line[i] + _paeth(line[i - bpp], prev[i], prev[i - bpp])) & 0xFF
                else:
                    line[i] = (line[i] + prev[i]) & 0xFF
        else:
            raise PngError(f"bad filter type {ft}")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    # samples -> one byte per sample, w * channels per row
    if depth == 16:
        samples = bytes(out[0::2])
    elif depth == 8:
        samples = bytes(out)
    else:
        per, mask = 8 // depth, (1 << depth) - 1
        rows = []
        for y in range(h):
            row = out[y * stride:(y + 1) * stride]
            vals = [(b >> (8 - depth * (k + 1))) & mask for b in row for k in range(per)][:w]
            rows.append(bytes(vals))
        samples = b"".join(rows)
        if ctype == 0:
            scale = 255 // mask
            samples = bytes(v * scale for v in samples)
    n = w * h
    rgba = bytearray(n * 4)
    if ctype == 6:
        rgba[:] = samples
    elif ctype == 2:
        rgba[0::4], rgba[1::4], rgba[2::4] = samples[0::3], samples[1::3], samples[2::3]
        rgba[3::4] = b"\xff" * n
        if trns and len(trns) == 6:
            key = bytes((trns[1], trns[3], trns[5])) if depth == 8 else bytes((trns[0], trns[2], trns[4]))
            for i in range(n):
                if samples[3 * i:3 * i + 3] == key:
                    rgba[4 * i + 3] = 0
    elif ctype == 0:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = samples
        rgba[3::4] = b"\xff" * n
        if trns and len(trns) == 2:
            key = trns[1] if depth >= 8 else trns[1] * (255 // ((1 << depth) - 1))
            for i in range(n):
                if samples[i] == key:
                    rgba[4 * i + 3] = 0
    elif ctype == 4:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = samples[0::2]
        rgba[3::4] = samples[1::2]
    else:
        if plte is None:
            raise PngError("palette image without PLTE")
        pal = [bytes(plte[i:i + 3]) + bytes(((trns[i // 3] if trns and i // 3 < len(trns) else 255),))
               for i in range(0, len(plte) - 2, 3)]
        try:
            rgba[:] = b"".join(pal[i] for i in samples)
        except IndexError:
            raise PngError("palette index out of range")
    return w, h, bytes(rgba)


def premultiply(rgba):
    """Straight-alpha RGBA bytes -> premultiplied RGBA bytes (round to nearest)."""
    if rgba[3::4].count(255) * 4 == len(rgba):
        return bytes(rgba)
    tables = {}
    out = bytearray(rgba)
    for i in range(0, len(out), 4):
        a = out[i + 3]
        if a == 255:
            continue
        if a == 0:
            out[i] = out[i + 1] = out[i + 2] = 0
            continue
        t = tables.get(a)
        if t is None:
            t = tables[a] = bytes((c * a + 127) // 255 for c in range(256))
        out[i], out[i + 1], out[i + 2] = t[out[i]], t[out[i + 1]], t[out[i + 2]]
    return bytes(out)


def _window(buf, stride, x0, x1, y0, y1, ch):
    return [buf[yy * stride + 4 * xx + ch] for yy in range(y0, y1 + 1) for xx in range(x0, x1 + 1)]


def pixel_off(exp, cand, w, h, x, y, tol=None, edge_tol=None, edge_contrast=None):
    """True when pixel (x, y) counts as off under the rule in the module docstring."""
    tol = TOL if tol is None else tol
    edge_tol = EDGE_TOL if edge_tol is None else edge_tol
    edge_contrast = EDGE_CONTRAST if edge_contrast is None else edge_contrast
    stride = w * 4
    i = y * stride + 4 * x
    e, c = exp[i:i + 4], cand[i:i + 4]
    if e == c:
        return False
    d = max(abs(e[0] - c[0]), abs(e[1] - c[1]), abs(e[2] - c[2]), abs(e[3] - c[3]))
    if d <= tol:
        return False
    x0, x1, y0, y1 = max(0, x - 1), min(w - 1, x + 1), max(0, y - 1), min(h - 1, y + 1)
    # 1. an edge that moved by up to one pixel
    explained = True
    e_rng = c_rng = 0
    for ch in range(4):
        en = _window(exp, stride, x0, x1, y0, y1, ch)
        cn = _window(cand, stride, x0, x1, y0, y1, ch)
        lo_e, hi_e, lo_c, hi_c = min(en), max(en), min(cn), max(cn)
        e_rng, c_rng = max(e_rng, hi_e - lo_e), max(c_rng, hi_c - lo_c)
        if not (lo_e - tol <= c[ch] <= hi_e + tol and lo_c - tol <= e[ch] <= hi_c + tol):
            explained = False
    if explained:
        return False
    # 2. a different anti-aliasing or coverage blend on an edge both images have
    if d <= edge_tol and e_rng >= edge_contrast and c_rng >= edge_contrast:
        return False
    return True


def count_off(exp, cand, w, h, tol=None, edge_tol=None, edge_contrast=None, cap=None):
    """Count off pixels between two premultiplied RGBA buffers of the same size (stop at cap)."""
    if exp == cand:
        return 0
    stride = w * 4
    off = 0
    for y in range(h):
        r0 = y * stride
        if exp[r0:r0 + stride] == cand[r0:r0 + stride]:
            continue
        for x in range(w):
            i = r0 + 4 * x
            if exp[i:i + 4] == cand[i:i + 4]:
                continue
            if pixel_off(exp, cand, w, h, x, y, tol, edge_tol, edge_contrast):
                off += 1
                if cap is not None and off >= cap:
                    return off
    return off


def off_mask(exp, cand, w, h):
    """Per-pixel classification for diff images: 0 equal, 1 different but accepted, 2 off."""
    out = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if exp[i:i + 4] != cand[i:i + 4]:
                out[y * w + x] = 2 if pixel_off(exp, cand, w, h, x, y) else 1
    return out


def compare_png_bytes(expected_png, candidate_png):
    """Return (passed, off_pixels, message). Raises nothing: a bad candidate file is a failure."""
    ew, eh, erg = read_png(expected_png)
    try:
        cw, ch, crg = read_png(candidate_png)
    except PngError as e:
        return False, None, f"unreadable PNG: {e}"
    if (cw, ch) != (ew, eh):
        return False, None, f"size {cw}x{ch}, expected {ew}x{eh}"
    limit = max_off(ew, eh)
    off = count_off(premultiply(erg), premultiply(crg), ew, eh, cap=limit + 1)
    if off > limit:
        return False, off, f"{off}+ pixels off (limit {limit})"
    return True, off, f"{off} pixels off (limit {limit})"


def write_png(path, w, h, rgba):
    """Write straight-alpha RGBA bytes as a compressed PNG (used for diff images)."""
    stride = w * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(h))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)
