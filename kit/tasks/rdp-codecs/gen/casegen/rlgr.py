"""RLGR1 / RLGR3 entropy coder (MS-RDPRFX 3.1.8.1.7.3), encoder and decoder, bit-exact with the
reference pseudocode as implemented by FreeRDP's encoder."""
from common import BitReader, BitWriter

KPMAX, LSGR, UP_GR, DN_GR, UQ_GR, DQ_GR = 80, 3, 4, 6, 3, 3


def _upd(p, d):
    p += d
    if p < 0:
        p = 0
    if p > KPMAX:
        p = KPMAX
    return p


def _code_gr(bs, state, val):
    kr = state["krp"] >> LSGR
    vk = val >> kr
    bs.bits(1, vk)
    bs.put(0, 1)
    if kr:
        bs.put(val & ((1 << kr) - 1), kr)
    if vk == 0:
        state["krp"] = _upd(state["krp"], -2)
    elif vk > 1:
        state["krp"] = _upd(state["krp"], vk)


def _two_ms(v):
    return 2 * v if v >= 0 else -2 * v - 1


def encode(mode, data):
    """mode 1 = RLGR1, 3 = RLGR3. data: list of ints (int16 range)."""
    bs = BitWriter()
    st = {"krp": 1 << LSGR}
    kp = 1 << LSGR
    k = 1
    i, n = 0, len(data)

    def nxt():
        nonlocal i
        if i < n:
            v = data[i]
            i += 1
            return v
        return 0

    while i < n:
        if k:
            zeros = 0
            v = nxt()
            while v == 0 and i < n:
                zeros += 1
                v = nxt()
            runmax = 1 << k
            while zeros >= runmax:
                bs.put(0, 1)
                zeros -= runmax
                kp = _upd(kp, UP_GR)
                k = kp >> LSGR
                runmax = 1 << k
            bs.put(1, 1)
            if k:
                bs.put(zeros, k)
            mag = -v if v < 0 else v
            bs.put(1 if v < 0 else 0, 1)
            _code_gr(bs, st, mag - 1 if mag else 0)
            kp = _upd(kp, -DN_GR)
            k = kp >> LSGR
        elif mode == 1:
            t = _two_ms(nxt())
            _code_gr(bs, st, t)
            kp = _upd(kp, -DQ_GR if t else UQ_GR)
            k = kp >> LSGR
        else:
            t1 = _two_ms(nxt())
            t2 = _two_ms(nxt())
            s = t1 + t2
            _code_gr(bs, st, s)
            nidx = s.bit_length()
            if nidx:
                bs.put(t1, nidx)
            if t1 and t2:
                kp = _upd(kp, -2 * DQ_GR)
                k = kp >> LSGR
            elif not t1 and not t2:
                kp = _upd(kp, 2 * UQ_GR)
                k = kp >> LSGR
    return bs.getvalue()


def decode(mode, data, count=4096):
    """Mirror of the reference decoder: stops at end of data or after count values, zero-fills."""
    br = BitReader(data)
    total = len(data) * 8
    out = []
    k, kp = 1, 1 << LSGR
    kr, krp = 1, 1 << LSGR

    def lead(bit):
        c = 0
        while br.pos < total and ((data[br.pos >> 3] >> (7 - (br.pos & 7))) & 1) == bit:
            c += 1
            br.pos += 1
        return c

    while br.pos < total and len(out) < count:
        if k:
            vk = lead(0)
            if br.pos >= total:
                break
            br.pos += 1
            run = 0
            for _ in range(vk):
                run += 1 << k
                kp = min(kp + UP_GR, KPMAX)
                k = kp >> LSGR
            if total - br.pos < k:
                break
            run += br.get(k)
            if total - br.pos < 1:
                break
            sign = br.get(1)
            vk = lead(1)
            if br.pos >= total:
                break
            br.pos += 1
            if total - br.pos < kr:
                break
            code = br.get(kr) | (vk << kr)
            if vk == 0:
                krp = max(krp - 2, 0)
                kr = krp >> LSGR
            elif vk != 1:
                krp = min(krp + vk, KPMAX)
                kr = krp >> LSGR
            kp = max(kp - DN_GR, 0)
            k = kp >> LSGR
            mag = code + 1
            out.extend([0] * min(run, count - len(out)))
            if len(out) < count:
                out.append(-mag if sign else mag)
        else:
            vk = lead(1)
            if br.pos >= total:
                break
            br.pos += 1
            if total - br.pos < kr:
                break
            code = br.get(kr) | (vk << kr)
            if vk == 0:
                krp = max(krp - 2, 0)
                kr = krp >> LSGR
            elif vk != 1:
                krp = min(krp + vk, KPMAX)
                kr = krp >> LSGR
            if mode == 1:
                if not code:
                    kp = min(kp + UQ_GR, KPMAX)
                    k = kp >> LSGR
                    mag = 0
                else:
                    kp = max(kp - DQ_GR, 0)
                    k = kp >> LSGR
                    mag = -((code + 1) >> 1) if code & 1 else code >> 1
                if len(out) < count:
                    out.append(mag)
            else:
                nidx = code.bit_length() if code else 0
                if total - br.pos < nidx:
                    break
                v1 = br.get(nidx) if nidx else 0
                v2 = code - v1
                if v1 and v2:
                    kp = max(kp - 2 * DQ_GR, 0)
                    k = kp >> LSGR
                elif not v1 and not v2:
                    kp = min(kp + 2 * UQ_GR, KPMAX)
                    k = kp >> LSGR
                for v in (v1, v2):
                    if len(out) < count:
                        out.append(-((v + 1) >> 1) if v & 1 else v >> 1)
    out.extend([0] * (count - len(out)))
    return out
