"""RDP8 bulk compression (ZGFX, MS-RDPEGFX 2.2.5 / 3.1.9.1): single and multipart segments, literal and
match tokens, unencoded runs, history shared across the messages of a sequence."""
import struct

from common import BitWriter, Seq, Step, choose_weighted

# (prefix length, prefix code, value bits, type (0 literal, 1 match), value base)
TOKENS = [(1, 0, 8, 0, 0), (5, 17, 5, 1, 0), (5, 18, 7, 1, 32), (5, 19, 9, 1, 160), (5, 20, 10, 1, 672),
          (5, 21, 12, 1, 1696), (5, 24, 0, 0, 0x00), (5, 25, 0, 0, 0x01), (6, 44, 14, 1, 5792),
          (6, 45, 15, 1, 22176), (6, 52, 0, 0, 0x02), (6, 53, 0, 0, 0x03), (6, 54, 0, 0, 0xFF),
          (7, 92, 18, 1, 54944), (7, 93, 20, 1, 317088), (7, 110, 0, 0, 0x04), (7, 111, 0, 0, 0x05),
          (7, 112, 0, 0, 0x06), (7, 113, 0, 0, 0x07), (7, 114, 0, 0, 0x08), (7, 115, 0, 0, 0x09),
          (7, 116, 0, 0, 0x0A), (7, 117, 0, 0, 0x0B), (7, 118, 0, 0, 0x3A), (7, 119, 0, 0, 0x3B),
          (7, 120, 0, 0, 0x3C), (7, 121, 0, 0, 0x3D), (7, 122, 0, 0, 0x3E), (7, 123, 0, 0, 0x3F),
          (7, 124, 0, 0, 0x40), (7, 125, 0, 0, 0x80), (8, 188, 20, 1, 1365664), (8, 189, 21, 1, 2414240),
          (8, 252, 0, 0, 0x0C), (8, 253, 0, 0, 0x38), (8, 254, 0, 0, 0x39), (8, 255, 0, 0, 0x66),
          (9, 380, 22, 1, 4511392), (9, 381, 23, 1, 8705696), (9, 382, 24, 1, 17094304)]
SHORT_LIT = {t[4]: t for t in TOKENS if t[3] == 0 and t[2] == 0}
MATCH = [t for t in TOKENS if t[3] == 1]
HISTORY = 2500000


def put_count(bw, n):
    if n == 3:
        bw.put(0, 1)
        return
    k = n.bit_length() - 1                      # 2^k <= n < 2^(k+1), k >= 2
    bw.put(1, 1)
    bw.bits(1, k - 2)
    bw.put(0, 1)
    bw.put(n - (1 << k), k)


def put_distance(bw, d):
    for (pl, pc, vb, _, base) in MATCH:
        if base <= d < base + (1 << vb):
            bw.put(pc, pl)
            bw.put(d - base, vb)
            return
    raise ValueError(d)


class Encoder:
    def __init__(self, r):
        self.r = r
        self.hist = bytearray()                     # everything output so far in the sequence
        self.index = {}

    def _add(self, data):
        start = len(self.hist)
        self.hist += data
        for i in range(max(0, start - 2), len(self.hist) - 2):
            self.index.setdefault(bytes(self.hist[i:i + 3]), []).append(i)

    def segment(self, data, compress):
        r = self.r
        if not compress:
            self._add(data)
            return bytes([0x04]) + data
        bw = BitWriter()
        i, n = 0, len(data)
        base = len(self.hist)
        buf = self.hist + data                      # matches may reach into the segment itself
        while i < n:
            pos = base + i
            best = (0, 0)
            cands = self.index.get(bytes(buf[pos:pos + 3]), [])[-24:] if pos + 3 <= len(buf) else []
            for c in reversed(cands):
                if c >= pos or pos - c > HISTORY - 1:
                    continue
                ln = 0
                while i + ln < n and ln < 2000 and buf[c + ln] == buf[pos + ln]:
                    ln += 1
                if ln > best[0]:
                    best = (ln, pos - c)
            ln, dist = best
            if ln >= 3 and r.random() < 0.95:
                ln = ln if r.random() < 0.8 else r.randint(3, ln)
                put_distance(bw, dist)
                put_count(bw, ln)
                chunk = bytes(buf[pos:pos + ln])
                i += ln
            elif r.random() < 0.02 and n - i > 4:
                ln = min(n - i, r.randint(1, 300))
                bw.put(17, 5)                       # distance token with distance 0: unencoded run
                bw.put(0, 5)
                bw.put(ln, 15)
                if bw.n:
                    bw.put(0, 8 - bw.n)
                for b in data[i:i + ln]:
                    bw.put(b, 8)
                chunk = bytes(data[i:i + ln])
                i += ln
            else:
                b = data[i]
                if b in SHORT_LIT and r.random() < 0.9:
                    t = SHORT_LIT[b]
                    bw.put(t[1], t[0])
                else:
                    bw.put(0, 1)
                    bw.put(b, 8)
                chunk = bytes([b])
                i += 1
            self._add(chunk)
        pad = (8 - bw.n) % 8
        body = bw.getvalue()
        return bytes([0x24]) + body + bytes([pad])


def payload(r, prev):
    """Bytes that look like graphics pipeline traffic: headers, repeated records, text, noise, reuse."""
    out = bytearray()
    target = choose_weighted(r, [(r.randint(1, 64), 1), (r.randint(65, 2000), 3), (r.randint(2001, 20000), 2),
                                 (r.randint(20001, 90000), 1)])
    words = [bytes(r.randrange(32, 127) for _ in range(r.randint(2, 9))) for _ in range(30)]
    while len(out) < target:
        k = choose_weighted(r, [("record", 3), ("text", 3), ("noise", 1), ("fill", 2), ("reuse", 2)])
        if k == "record":
            rec = struct.pack("<HHI", r.choice([0x0D, 0x0E, 0x01, 0x13]), r.randrange(65536), r.randrange(1 << 32))
            out += rec * r.randint(1, 6)
        elif k == "text":
            out += b" ".join(r.choice(words) for _ in range(r.randint(3, 40)))
        elif k == "noise":
            out += bytes(r.randrange(256) for _ in range(r.randint(1, 200)))
        elif k == "fill":
            out += bytes([r.choice([0, 0xFF, 0x80, r.randrange(256)])]) * r.randint(3, 600)
        elif prev:
            a = r.randrange(len(prev))
            out += prev[a:a + r.randint(3, 3000)]
    return bytes(out[:target])


def make_sequences(r, count, seed_base):
    seqs = []
    for i in range(count):
        seq = Seq("zgfx", 1, 1, 0x20048888, stride=4, fill_seed=seed_base + i, tags=["zgfx"])
        enc = Encoder(r)
        prev = b""
        for m in range(choose_weighted(r, [(1, 2), (2, 2), (4, 2), (8, 1)])):
            data = payload(r, prev)
            prev = (prev + data)[-200000:]
            compress_all = r.random() < 0.85
            if len(data) <= 65535 and r.random() < 0.6:
                seg = enc.segment(data, compress_all or r.random() < 0.5)
                msg = bytes([0xE0]) + seg
                kind = "single"
            else:
                parts, pos = [], 0
                while pos < len(data) or not parts:
                    ln = min(len(data) - pos, r.choice([65535, r.randint(1, 65535)]))
                    parts.append(enc.segment(data[pos:pos + ln], compress_all or r.random() < 0.5))
                    pos += ln
                msg = bytes([0xE1]) + struct.pack("<HI", len(parts), len(data))
                msg += b"".join(struct.pack("<I", len(p)) + p for p in parts)
                kind = f"multipart{len(parts)}"
            seq.add(Step([], msg, tags=[kind, "compressed" if compress_all else "mixed"]))
        seqs.append(seq)
    return seqs
