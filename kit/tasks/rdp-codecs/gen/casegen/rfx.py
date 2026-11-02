"""RemoteFX messages (MS-RDPRFX 2.2.2): header blocks, frames with one region and one tileset."""
import struct

import coef
import rlgr
from common import BGRA32, BGRX32, RGBA32, RGBX32, BGR24, RGB16, XRGB32, Seq, Step, bytes_per_pixel, choose_weighted

WBT_SYNC, WBT_CODEC_VERSIONS, WBT_CHANNELS, WBT_CONTEXT = 0xCCC0, 0xCCC1, 0xCCC2, 0xCCC3
WBT_FRAME_BEGIN, WBT_FRAME_END, WBT_REGION, WBT_EXTENSION = 0xCCC4, 0xCCC5, 0xCCC6, 0xCCC7
CBT_REGION, CBT_TILESET, CBT_TILE = 0xCAC1, 0xCAC2, 0xCAC3

# position of each buffer band's quant value in the 10-nibble TS_RFX_CODEC_QUANT
RFX_BAND_NIBBLE = [8, 7, 9, 5, 4, 6, 2, 1, 3, 0]


def blk(btype, payload, channel=None):
    extra = b"" if channel is None else bytes([1, channel])
    return struct.pack("<HI", btype, 6 + len(extra) + len(payload)) + extra + payload


def sync():
    return blk(WBT_SYNC, struct.pack("<IH", 0xCACCACCA, 0x0100))


def codec_versions():
    return blk(WBT_CODEC_VERSIONS, struct.pack("<BBH", 1, 1, 0x0100))


def channels(chans):
    return blk(WBT_CHANNELS, bytes([len(chans)]) + b"".join(struct.pack("<BHH", 0, w, h) for w, h in chans))


def properties(mode, flags=0x02):
    et = 0x01 if mode == 1 else 0x04
    return flags | (1 << 3) | (1 << 5) | (et << 9) | (1 << 13)


def context(mode, flags=0x02):
    return blk(WBT_CONTEXT, struct.pack("<BHH", 0, 0x40, properties(mode, flags)), channel=0xFF)


def frame_begin(idx):
    return blk(WBT_FRAME_BEGIN, struct.pack("<IH", idx, 1), channel=0)


def frame_end():
    return blk(WBT_FRAME_END, b"", channel=0)


def region(rects):
    body = bytes([1]) + struct.pack("<H", len(rects))
    body += b"".join(struct.pack("<HHHH", *rc) for rc in rects)
    body += struct.pack("<HH", CBT_REGION, 1)
    return blk(WBT_REGION, body, channel=0)


def quant_bytes(q):
    """q: 10 values in TS_RFX_CODEC_QUANT nibble order (LL3, LH3, HL3, HH3, LH2, HL2, HH2, LH1, HL1, HH1)."""
    return bytes(q[2 * i] | (q[2 * i + 1] << 4) for i in range(5))


def tile(qy, qcb, qcr, xi, yi, ydata, cbdata, crdata):
    body = struct.pack("<BBBHHHHH", qy, qcb, qcr, xi, yi, len(ydata), len(cbdata), len(crdata))
    body += ydata + cbdata + crdata
    return struct.pack("<HI", CBT_TILE, 6 + len(body)) + body


def tileset(mode, quants, tiles, flags=0x02):
    data = b"".join(tiles)
    props = 1 | (flags << 1) | (1 << 4) | (1 << 6) | ((0x01 if mode == 1 else 0x04) << 10) | (1 << 14)
    body = struct.pack("<HHHBBHI", CBT_TILESET, 0, props, len(quants), 0x40, len(tiles), len(data))
    body += b"".join(quant_bytes(q) for q in quants)
    body += data
    return blk(WBT_EXTENSION, body, channel=0)


def band_shifts(q):
    """Decoder shift per buffer band: quant value - 1."""
    return [q[n] - 1 for n in RFX_BAND_NIBBLE]


def diff_encode_ll(c, off=4032, n=64):
    out = list(c)
    for i in range(off + n - 1, off, -1):
        out[i] = c[i] - c[i - 1]
    return out


def tile_data(r, mode, qy, qcb, qcr, source):
    if source == "natural":
        comps = coef.natural(r, band_shifts(qy), band_shifts(qcb), band_shifts(qcr))
    else:
        comps = [coef.synthetic(r, band_shifts(q)) for q in (qy, qcb, qcr)]
    return [rlgr.encode(mode, diff_encode_ll(c)) for c in comps]


def random_quant(r):
    base = r.randint(6, 9)
    return [min(15, max(6, base + r.randint(-1, 3) + (1 if i >= 7 else 0))) for i in range(10)]


def make_sequences(r, count, seed_base):
    """Surface-bits / GFX RemoteFX calls: a channel, frames of tiles clipped by region rects."""
    seqs = []
    for i in range(count):
        cw = choose_weighted(r, [(r.randint(16, 128), 2), (r.randint(129, 320), 2), (r.choice([64, 128, 256]), 1)])
        ch = choose_weighted(r, [(r.randint(16, 128), 2), (r.randint(129, 240), 1), (r.choice([64, 128]), 1)])
        left = r.choice([0, 0, r.randint(0, 40)])
        top = r.choice([0, 0, r.randint(0, 40)])
        sw = cw + left + r.choice([0, 0, r.randint(-20, 30)])
        sh = ch + top + r.choice([0, 0, r.randint(-20, 30)])
        sw, sh = max(8, sw), max(8, sh)
        fmt = choose_weighted(r, [(BGRX32, 4), (BGRA32, 2), (RGBX32, 1), (RGBA32, 1), (BGR24, 1), (RGB16, 1)])
        tilefmt = choose_weighted(r, [(BGRX32, 3), (BGRA32, 2), (RGBX32, 1), (XRGB32, 1)])
        mode = r.choice([1, 3])
        pad = r.choice([0, 0, 0, 16, 64])
        seq = Seq("rfx", sw, sh, fmt, stride=sw * bytes_per_pixel(fmt) + pad, fill_seed=seed_base + i,
                  ctx0=tilefmt, tags=["rfx", f"rlgr{mode}"])
        nmsg = choose_weighted(r, [(1, 3), (2, 2), (3, 2), (5, 1)])
        gx, gy = (cw + 63) // 64, (ch + 63) // 64
        nchan = 1 if r.random() < 0.9 else 2
        for m in range(nmsg):
            parts = []
            first = m == 0
            headers = first or r.random() < 0.2
            if headers:
                hdr = [sync(), context(mode), codec_versions(),
                       channels([(cw, ch)] + [(r.randint(16, 400), r.randint(16, 300))] * (nchan - 1))]
                if r.random() < 0.3:
                    r.shuffle(hdr)
                parts += hdr
            nq = choose_weighted(r, [(1, 4), (2, 2), (3, 1), (5, 1)])
            quants = [random_quant(r) for _ in range(nq)]
            cells = [(x, y) for y in range(gy) for x in range(gx)]
            r.shuffle(cells)
            ntiles = max(1, min(len(cells), choose_weighted(r, [(1, 2), (len(cells), 2), (r.randint(1, len(cells)), 3)])))
            source = choose_weighted(r, [("natural", 3), ("synthetic", 2)])
            tiles = []
            for (xi, yi) in sorted(cells[:ntiles], key=lambda c: (c[1], c[0])) if r.random() < 0.7 else cells[:ntiles]:
                iy, icb, icr = (r.randrange(nq) for _ in range(3))
                yd, cbd, crd = tile_data(r, mode, quants[iy], quants[icb], quants[icr], source)
                tiles.append(tile(iy, icb, icr, xi, yi, yd, cbd, crd))
            kind = choose_weighted(r, [("full", 2), ("tiles", 2), ("random", 3), ("empty", 1)])
            if kind == "empty":
                rects = []                                   # decoder uses (0, 0, channel w, channel h)
            elif kind == "full":
                rects = [(0, 0, cw, ch)]
            elif kind == "tiles":
                rects = [(xi * 64, yi * 64, 64, 64) for (xi, yi) in cells[:ntiles]]
            else:
                rects = []
                for _ in range(r.randint(1, 6)):
                    x0, y0 = r.randrange(cw), r.randrange(ch)
                    rects.append((x0, y0, r.randint(1, cw - x0), r.randint(1, ch - y0)))
            parts += [frame_begin(r.randrange(1 << 16)), region(rects), tileset(mode, quants, tiles), frame_end()]
            seq.add(Step([left, top], b"".join(parts),
                         tags=[f"tiles{ntiles}", f"quant{nq}", kind, source] + (["headers"] if headers else [])))
        seqs.append(seq)
    return seqs
