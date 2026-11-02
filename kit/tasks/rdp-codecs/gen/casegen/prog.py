"""RemoteFX progressive messages (MS-RDPEGFX 2.2.4.2): SIMPLE / FIRST tiles with quality levels, UPGRADE
passes (SRL + RAW bit-planes), reduce-extrapolate DWT layout."""
import struct

import coef
import rlgr
from common import (BGR24, BGRA32, BGRX32, RGB16, RGBA32, RGBX32, BitWriter, Seq, Step, bytes_per_pixel,
                    choose_weighted)

SYNC, FRAME_BEGIN, FRAME_END, CONTEXT, REGION = 0xCCC0, 0xCCC1, 0xCCC2, 0xCCC3, 0xCCC4
TILE_SIMPLE, TILE_FIRST, TILE_UPGRADE = 0xCCC5, 0xCCC6, 0xCCC7

# nibble position (LL3, HL3, LH3, HH3, HL2, LH2, HH2, HL1, LH1, HH1) of each buffer band
PROG_BAND_NIBBLE = [7, 8, 9, 4, 5, 6, 1, 2, 3, 0]


def blk(btype, payload):
    return struct.pack("<HI", btype, 6 + len(payload)) + payload


def quant5(q):
    return bytes(q[2 * i] | (q[2 * i + 1] << 4) for i in range(5))


def band_vals(q):
    """10 nibble-order values -> per buffer band values."""
    return [q[n] for n in PROG_BAND_NIBBLE]


def srl_encode(values):
    """values: list of (value, numBits) for coefficients read through the SRL stream, in order."""
    bw = BitWriter()
    kp = 8
    i, n = 0, len(values)
    while i < n:
        k = kp // 8
        z = 0
        while i + z < n and values[i + z][0] == 0:
            z += 1
        if z >= (1 << k) or i + z == n:
            bw.put(0, 1)
            kp = min(kp + 4, 80)
            i += min(1 << k, n - i)
            continue
        bw.put(1, 1)
        if k:
            bw.put(z, k)
        v, nb = values[i + z]
        bw.put(1 if v < 0 else 0, 1)
        kp = max(kp - 6, 0)
        if nb > 1:
            m, mx = abs(v), (1 << nb) - 1
            bw.bits(0, m - 1)
            if m < mx:
                bw.put(1, 1)
        i += z + 1
    return bw.getvalue()


class TileState:
    def __init__(self, extrapolate, quant_idx, quants):
        self.extrapolate = extrapolate
        self.quant_idx = quant_idx                   # (y, cb, cr) indices into the sequence quant list
        self.qvals = [band_vals(quants[i]) for i in quant_idx]
        self.truth = None                            # quantized coefficients c per component
        self.sign = None                             # decoder view: first-pass RLGR output, updated by SRL
        self.prog = None                             # progQuant per component per band at the last pass


def first_pass(r, st, prog_vals, extrapolate, source):
    """Coefficient payloads for a SIMPLE/FIRST tile; prog_vals: per component per band progQuant."""
    bands = coef.EXT_BANDS if extrapolate else coef.RFX_BANDS
    ll_off, ll_n = bands[9]
    datas, signs, truths = [], [], []
    for comp in range(3):
        q = st.qvals[comp]
        shifts = [q[b] - 1 for b in range(10)]
        if source == "natural" and not extrapolate:
            c = coef.natural(r, shifts, shifts, shifts)[comp]
        else:
            c = coef.synthetic(r, shifts, "ext" if extrapolate else "rfx")
        p = prog_vals[comp]
        v = [0] * 4096
        for b, (off, cnt) in enumerate(bands):
            for i in range(off, off + cnt):
                if b == 9:
                    v[i] = c[i] >> p[b]
                else:
                    m = abs(c[i]) >> p[b]
                    v[i] = -m if c[i] < 0 else m
        tx = list(v)
        for i in range(ll_off + ll_n - 1, ll_off, -1):   # LL3 is differentially coded
            tx[i] = v[i] - v[i - 1]
        data = rlgr.encode(1, tx)
        dec = rlgr.decode(1, data)
        datas.append(data)
        signs.append(dec)
        truths.append(c)
    st.truth, st.sign, st.prog = truths, signs, [list(p) for p in prog_vals]
    return datas


def upgrade_pass(st, new_prog):
    """SRL and RAW payloads per component moving from st.prog to new_prog (both per band, non-increasing)."""
    bands = coef.EXT_BANDS
    out = []
    for comp in range(3):
        c, sign = st.truth[comp], st.sign[comp]
        old, new = st.prog[comp], new_prog[comp]
        srl_vals = []
        raw = BitWriter()
        for b, (off, cnt) in enumerate(bands):
            nb = old[b] - new[b]
            if nb <= 0:
                continue
            mask = (1 << nb) - 1
            for i in range(off, off + cnt):
                if b == 9:
                    raw.put((c[i] >> new[b]) & mask, nb)
                elif sign[i] != 0:
                    raw.put((abs(c[i]) >> new[b]) & mask, nb)
                else:
                    m = (abs(c[i]) >> new[b]) & mask
                    val = -m if c[i] < 0 else m
                    srl_vals.append((val, nb))
                    sign[i] = val
        out.append((srl_encode(srl_vals), raw.getvalue()))
    st.prog = [list(p) for p in new_prog]
    return out


def tile_simple_or_first(kind, qi, xi, yi, flags, quality, datas):
    body = struct.pack("<BBBHHB", qi[0], qi[1], qi[2], xi, yi, flags)
    if kind == TILE_FIRST:
        body += bytes([quality])
    body += struct.pack("<HHHH", len(datas[0]), len(datas[1]), len(datas[2]), 0)
    body += datas[0] + datas[1] + datas[2]
    return blk(kind, body)


def tile_upgrade(qi, xi, yi, quality, comps):
    body = struct.pack("<BBBHHB", qi[0], qi[1], qi[2], xi, yi, quality)
    lens = []
    for srl, raw in comps:
        lens += [len(srl), len(raw)]
    body += struct.pack("<6H", *lens)
    for srl, raw in comps:
        body += srl + raw
    return blk(TILE_UPGRADE, body)


def region(rects, quants, progs, flags, tiles):
    data = b"".join(tiles)
    body = struct.pack("<BHBBBHI", 64, len(rects), len(quants), len(progs), flags, len(tiles), len(data))
    body += b"".join(struct.pack("<HHHH", *rc) for rc in rects)
    body += b"".join(quant5(q) for q in quants)
    for quality, (py, pcb, pcr) in progs:
        body += bytes([quality]) + quant5(py) + quant5(pcb) + quant5(pcr)
    return blk(REGION, body + data)


def ladder(r, levels, max_start):
    """Per component, per nibble: non-increasing progQuant values over the quality levels, ending at 0."""
    comps = []
    for _ in range(3):
        nib = []
        for _ in range(10):
            start = r.randint(0, max_start)
            vals = [start]
            for _ in range(levels - 1):
                vals.append(max(0, vals[-1] - r.randint(0, 2)))
            vals[-1] = 0 if r.random() < 0.7 else vals[-1]
            nib.append(vals)
        comps.append(nib)
    # table entry j: (quality byte, (y, cb, cr) nibble lists)
    table = []
    for j in range(levels):
        table.append((min(100, 10 + 25 * j), tuple([comps[c][n][j] for n in range(10)] for c in range(3))))
    return table


def make_sequences(r, count, seed_base):
    seqs = []
    for i in range(count):
        W = choose_weighted(r, [(r.randint(16, 128), 2), (r.randint(129, 320), 2), (r.choice([64, 128, 256]), 1)])
        H = choose_weighted(r, [(r.randint(16, 128), 2), (r.randint(129, 240), 1), (r.choice([64, 128]), 1)])
        fmt = choose_weighted(r, [(BGRX32, 4), (BGRA32, 3), (RGBX32, 1), (RGBA32, 1), (BGR24, 1), (RGB16, 1)])
        extrapolate = r.random() < 0.6
        upgrades = extrapolate and r.random() < 0.75
        pad = r.choice([0, 0, 0, 16, 64])
        sid = r.randint(0, 0xFFFF)
        seq = Seq("progressive", W, H, fmt, stride=W * bytes_per_pixel(fmt) + pad, fill_seed=seed_base + i,
                  ctx0=sid, tags=["progressive", "extrapolate" if extrapolate else "dwt53",
                                   "upgrades" if upgrades else "single-pass"])
        nq = r.randint(1, 3)
        quants = [[r.randint(6, 8) + (1 if n >= 7 and r.random() < 0.5 else 0) for n in range(10)] for _ in range(nq)]
        levels = r.randint(2, 4)
        table = ladder(r, levels, 13 - 9 - 1 if upgrades else 3)
        gx, gy = (W + 63) // 64, (H + 63) // 64
        cells = [(x, y) for y in range(gy) for x in range(gx)]
        states = {}
        ctx_flags = 1 if upgrades or r.random() < 0.5 else 0
        nmsg = choose_weighted(r, [(1, 2), (2, 2), (3, 2), (4, 1), (6, 1)]) if upgrades else \
            choose_weighted(r, [(1, 3), (2, 2), (3, 1)])
        frame = r.randint(1, 1000)
        for m in range(nmsg):
            parts = []
            if m == 0 or r.random() < 0.2:
                parts.append(blk(SYNC, struct.pack("<IH", 0xCACCACCA, 0x0100)))
                parts.append(blk(CONTEXT, struct.pack("<BHB", 0, 64, ctx_flags)))
            r.shuffle(cells)
            ntiles = max(1, min(len(cells), choose_weighted(r, [(1, 2), (len(cells), 2), (r.randint(1, len(cells)), 3)])))
            tiles, kinds = [], set()
            for (xi, yi) in cells[:ntiles]:
                st = states.get((xi, yi))
                can_up = upgrades and st is not None and any(
                    any(st.prog[c][PROG_BAND_NIBBLE.index(n)] > 0 for n in range(10)) for c in range(3))
                if can_up and r.random() < 0.75:
                    # next quality level strictly below in some band (or full quality)
                    cur = [[st.prog[c][PROG_BAND_NIBBLE.index(n)] for n in range(10)] for c in range(3)]
                    choices = [j for j, (_, pq) in enumerate(table)
                               if all(pq[c][n] <= cur[c][n] for c in range(3) for n in range(10))]
                    choices.append(0xFF)
                    qual = r.choice(choices)
                    pq = table[qual][1] if qual != 0xFF else ([0] * 10, [0] * 10, [0] * 10)
                    new_prog = [band_vals(pq[c]) for c in range(3)]
                    comps = upgrade_pass(st, new_prog)
                    tiles.append(tile_upgrade(st.quant_idx, xi, yi, qual, comps))
                    kinds.add("upgrade")
                    continue
                qi = tuple(r.randrange(nq) for _ in range(3))
                st = TileState(extrapolate, qi, quants)
                kind = TILE_FIRST if (upgrades or r.random() < 0.5) else TILE_SIMPLE
                if kind == TILE_SIMPLE:
                    qual = 0xFF
                else:
                    qual = r.randrange(len(table)) if r.random() < 0.85 else 0xFF
                pq = table[qual][1] if qual != 0xFF else ([0] * 10, [0] * 10, [0] * 10)
                prog_vals = [band_vals(pq[c]) for c in range(3)]
                source = choose_weighted(r, [("natural", 3), ("synthetic", 2)])
                datas = first_pass(r, st, prog_vals, extrapolate, source)
                flags = 0
                if not upgrades and (xi, yi) in states and r.random() < 0.3:
                    # RFX_TILE_DIFFERENCE: small deltas against the tile's previous coefficients
                    flags = 1
                    small = [coef.synthetic(r, [12] * 10, "ext" if extrapolate else "rfx", 0.05) for _ in range(3)]
                    bands = coef.EXT_BANDS if extrapolate else coef.RFX_BANDS
                    ll_off, ll_n = bands[9]
                    datas = []
                    for c in small:
                        for k in range(ll_off, ll_off + ll_n):
                            c[k] = max(-2, min(2, c[k]))
                        tx = list(c)
                        for k in range(ll_off + ll_n - 1, ll_off, -1):
                            tx[k] = c[k] - c[k - 1]
                        datas.append(rlgr.encode(1, tx))
                    st.truth = None
                states[(xi, yi)] = st
                tiles.append(tile_simple_or_first(kind, qi, xi, yi, flags, qual, datas))
                kinds.add("simple" if kind == TILE_SIMPLE else "first")
                if flags:
                    kinds.add("diff")
            # clip rects inside the surface
            rk = choose_weighted(r, [("full", 2), ("tiles", 2), ("random", 3)])
            if rk == "full":
                rects = [(0, 0, W, H)]
            elif rk == "tiles":
                rects = [(x * 64, y * 64, min(64, W - x * 64), min(64, H - y * 64)) for (x, y) in cells[:ntiles]]
            else:
                rects = []
                for _ in range(r.randint(1, 6)):
                    x0, y0 = r.randrange(W), r.randrange(H)
                    rects.append((x0, y0, r.randint(1, W - x0), r.randint(1, H - y0)))
            rflags = 1 if extrapolate else 0
            parts.append(blk(FRAME_BEGIN, struct.pack("<IH", frame + m, 1)))
            parts.append(region(rects, quants, table, rflags, tiles))
            parts.append(blk(FRAME_END, b""))
            seq.add(Step([frame + m], b"".join(parts), tags=sorted(kinds) + [rk, f"tiles{ntiles}"]))
        seqs.append(seq)
    return seqs
