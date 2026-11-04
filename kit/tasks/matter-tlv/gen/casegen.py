"""Generate case scripts for case_runner (authoring only; never shipped in the image).

usage: python3 -I casegen.py --seed N --scale K > cases.txt

Six buckets: tlv_write, tlv_read, tlv_tools, msg_header, json_tlv, onboarding. Inputs come from an
independent Python TLV encoder (all tag forms, all length widths, non-minimal encodings), random writer
programs, mutated byte strings, random headers, JSON documents in the jsontlv format, and onboarding payloads.
"""
import argparse
import base64
import json
import random
import struct

ap = argparse.ArgumentParser()
ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--prefix", default="")
args = ap.parse_args()
R = random.Random(args.seed)

out = []
counter = [0]


def case(bucket, ops):
    counter[0] += 1
    out.append(f"CASE {args.prefix}{counter[0]:05d} {bucket}")
    out.extend(ops)
    out.append("END")


def hx(b):
    return b.hex() if b else "-"


# ------------------------------------------------------------------------------------------------
# values
# ------------------------------------------------------------------------------------------------
EDGE_U = [0, 1, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0x10000, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF,
          0x100000000, 0x7FFFFFFFFFFFFFFF, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF]
EDGE_I = [0, 1, -1, 127, -128, 128, -129, 32767, -32768, 32768, -32769, 2**31 - 1, -2**31, 2**31, -2**31 - 1,
          2**63 - 1, -2**63]


def rand_u(bits=64):
    if R.random() < 0.4:
        return R.choice([v for v in EDGE_U if v < 2**bits])
    return R.getrandbits(R.randint(1, bits))


def rand_i(bits=64):
    lo, hi = -2**(bits - 1), 2**(bits - 1) - 1
    if R.random() < 0.4:
        return R.choice([v for v in EDGE_I if lo <= v <= hi])
    v = R.getrandbits(R.randint(1, bits - 1))
    return -v if R.random() < 0.5 else v


def rand_f64bits():
    c = R.random()
    if c < 0.1:
        return R.choice([0x0000000000000000, 0x8000000000000000, 0x7FF0000000000000, 0xFFF0000000000000,
                         0x7FF8000000000000, 0x3FF0000000000000, 0x0000000000000001])
    if c < 0.5:
        return struct.unpack("<Q", struct.pack("<d", R.choice([1.5, -2.25, 0.1, 1e300, -1e-300, 3.0, 100.0,
                                                                  R.uniform(-1e6, 1e6)])))[0]
    return R.getrandbits(64)


def rand_f32bits():
    c = R.random()
    if c < 0.1:
        return R.choice([0, 0x80000000, 0x7F800000, 0xFF800000, 0x7FC00000, 0x3F800000, 1])
    if c < 0.5:
        return struct.unpack("<I", struct.pack("<f", R.choice([1.5, -2.25, 0.5, 3.0, R.uniform(-1e4, 1e4)])))[0]
    return R.getrandbits(32)


def rand_text(maxlen=24, valid=True):
    n = R.choice([0, 1, 2, 5, R.randint(0, maxlen)])
    c = R.random()
    if c < 0.6:
        s = "".join(R.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_.:/") for _ in range(n))
        b = s.encode()
    elif c < 0.85:
        s = "".join(R.choice(["a", "é", "€", "日本", "😀", "ß", "Z", " ", "\u001e", "Ω"]) for _ in range(max(1, n // 2)))
        b = s.encode()
    else:
        b = bytes(R.getrandbits(8) for _ in range(n))
    if not valid and R.random() < 0.7:
        b = b + R.choice([b"\xff", b"\xc3", b"\xe2\x82", b"\x00", b"\xed\xa0\x80", b"\xc0\xaf", b"\xf8\x88\x80\x80\x80"])
    return b


def rand_bytes(maxlen=40):
    n = R.choice([0, 1, 3, R.randint(0, maxlen)])
    if R.random() < 0.05:
        n = R.choice([255, 256, 300])
    return bytes(R.getrandbits(8) for _ in range(n))


# ------------------------------------------------------------------------------------------------
# independent TLV encoder (Matter spec Appendix A)
# ------------------------------------------------------------------------------------------------
# tag: ("anon",) ("ctx", n) ("common", n) ("implicit", n) ("fq", vendor, profile, n)
def enc_tag(tag, minimal=True):
    k = tag[0]
    if k == "anon":
        return 0x00, b""
    if k == "ctx":
        return 0x20, bytes([tag[1]])
    if k in ("common", "implicit"):
        base = 0x40 if k == "common" else 0x80
        if tag[1] <= 0xFFFF and (minimal or R.random() < 0.5):
            return base, struct.pack("<H", tag[1])
        return base + 0x20, struct.pack("<I", tag[1])
    if k == "fq":
        if tag[3] <= 0xFFFF and (minimal or R.random() < 0.5):
            return 0xC0, struct.pack("<HHH", tag[1], tag[2], tag[3])
        return 0xE0, struct.pack("<HHI", tag[1], tag[2], tag[3])
    raise ValueError(k)


def int_width(v, signed):
    for w, f in ((1, "b"), (2, "h"), (4, "i"), (8, "q")):
        if signed and -2**(8 * w - 1) <= v < 2**(8 * w - 1):
            return w
        if not signed and v < 2**(8 * w):
            return w
    return 8


WIDTH_CODE = {1: 0, 2: 1, 4: 2, 8: 3}
PACK = {(1, True): "<b", (2, True): "<h", (4, True): "<i", (8, True): "<q",
        (1, False): "<B", (2, False): "<H", (4, False): "<I", (8, False): "<Q"}


def enc(el, minimal=True):
    """el: (tag, kind, value). kind: int uint bool f32 f64 str bytes null struct array list"""
    tag, kind, val = el
    tc, tb = enc_tag(tag, minimal)
    if kind in ("int", "uint"):
        signed = kind == "int"
        w = int_width(val, signed)
        if not minimal and R.random() < 0.4:
            w = R.choice([x for x in (1, 2, 4, 8) if x >= w])
        return bytes([tc | (0 if signed else 4) | WIDTH_CODE[w]]) + tb + struct.pack(PACK[(w, signed)], val)
    if kind == "bool":
        return bytes([tc | (0x09 if val else 0x08)]) + tb
    if kind == "f32":
        return bytes([tc | 0x0A]) + tb + struct.pack("<I", val)
    if kind == "f64":
        return bytes([tc | 0x0B]) + tb + struct.pack("<Q", val)
    if kind in ("str", "bytes"):
        base = 0x0C if kind == "str" else 0x10
        w = int_width(len(val), False)
        if not minimal and R.random() < 0.4:
            w = R.choice([x for x in (1, 2, 4, 8) if x >= w])
        return bytes([tc | base | WIDTH_CODE[w]]) + tb + struct.pack(PACK[(w, False)], len(val)) + val
    if kind == "null":
        return bytes([tc | 0x14]) + tb
    if kind in ("struct", "array", "list"):
        t = {"struct": 0x15, "array": 0x16, "list": 0x17}[kind]
        return bytes([tc | t]) + tb + b"".join(enc(c, minimal) for c in val) + b"\x18"
    raise ValueError(kind)


IMPLICIT = [0x00000000, 0x235A0000, 0x00230001, 0xFFF10002]


def rand_tag(ctx_kind):
    """ctx_kind: 'top', 'struct', 'array', 'list'"""
    if ctx_kind == "array":
        return ("anon",)
    c = R.random()
    if ctx_kind == "struct" and c < 0.05:
        return ("anon",)                         # invalid inside a structure
    if ctx_kind in ("top", "list") and c < 0.25:
        return ("anon",)
    c = R.random()
    if c < 0.5:
        return ("ctx", R.choice([0, 1, 2, 3, 7, 15, 31, 128, 254, 255, R.randint(0, 255)]))
    if c < 0.65:
        return ("common", R.choice([0, 1, 255, 256, 0xFFFF, 0x10000, R.getrandbits(32)]))
    if c < 0.8:
        return ("implicit", R.choice([0, 1, 0xFFFF, 0x10000, R.getrandbits(32)]))
    return ("fq", R.choice([0, 0x235A, 0xFFF1, R.getrandbits(16)]), R.choice([0, 1, R.getrandbits(16)]),
            R.choice([0, 7, 0xFFFF, 0x10000, R.getrandbits(32)]))


def rand_scalar(tag):
    k = R.choice(["int", "uint", "bool", "f32", "f64", "str", "bytes", "null", "int", "uint", "str"])
    if k == "int":
        return (tag, k, rand_i())
    if k == "uint":
        return (tag, k, rand_u())
    if k == "bool":
        return (tag, k, R.random() < 0.5)
    if k == "f32":
        return (tag, k, rand_f32bits())
    if k == "f64":
        return (tag, k, rand_f64bits())
    if k == "str":
        return (tag, k, rand_text(valid=R.random() < 0.9))
    if k == "bytes":
        return (tag, k, rand_bytes())
    return (tag, "null", None)


def rand_tree(depth=0, ctx="top", maxdepth=4, width=5):
    tag = rand_tag(ctx)
    if depth < maxdepth and R.random() < (0.55 if depth == 0 else 0.3):
        kind = R.choice(["struct", "struct", "array", "list"])
        n = R.randint(0, width)
        return (tag, kind, [rand_tree(depth + 1, kind, maxdepth, width) for _ in range(n)])
    return rand_scalar(tag)


def rand_doc():
    top = ("anon",) if R.random() < 0.8 else rand_tag("top")
    kind = R.choice(["struct", "struct", "array", "list"])
    n = R.randint(1, 6)
    return (top, kind, [rand_tree(1, kind) for _ in range(n)])


def mutate(b):
    b = bytearray(b)
    if not b:
        return bytes(b)
    m = R.choice(["flip", "trunc", "trunc", "type", "insert", "dellast", "lenbig", "dup"])
    if m == "flip":
        i = R.randrange(len(b))
        b[i] ^= 1 << R.randrange(8)
    elif m == "trunc":
        b = b[:R.randrange(len(b))]
    elif m == "type":
        i = R.randrange(len(b))
        b[i] = (b[i] & 0xE0) | R.choice([0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x18, 0x15])
    elif m == "insert":
        i = R.randrange(len(b) + 1)
        b[i:i] = bytes([R.getrandbits(8)])
    elif m == "dellast":
        b = b[:-1]
    elif m == "lenbig":
        i = R.randrange(len(b))
        b[i] = 0xFF
    else:
        i = R.randrange(len(b))
        b = b[:i] + b[i:]
        b += b[i:i + 3]
    return bytes(b)


def tag_tok(tag):
    k = tag[0]
    if k == "anon":
        return "a"
    if k == "ctx":
        return f"c{tag[1]}"
    if k == "common":
        return f"m{tag[1]}"
    if k == "implicit":
        return f"i{tag[1]}"
    return f"p{(tag[1] << 16) | tag[2]:08x}.{tag[3]}"


# ------------------------------------------------------------------------------------------------
# bucket: tlv_write
# ------------------------------------------------------------------------------------------------
def writer_ops_for(el, ops, ctx="top", use_open=False):
    tag, kind, val = el
    t = tag_tok(tag)
    if kind == "int":
        w = R.choice([w for w in ("i8", "i16", "i32", "i64") if -2**({"i8": 7, "i16": 15, "i32": 31, "i64": 63}[w]) <= val < 2**({"i8": 7, "i16": 15, "i32": 31, "i64": 63}[w])])
        ops.append(f"W.{w} {t} {val}" + (" p" if R.random() < 0.2 else ""))
    elif kind == "uint":
        w = R.choice([w for w in ("u8", "u16", "u32", "u64") if val < 2**({"u8": 8, "u16": 16, "u32": 32, "u64": 64}[w])])
        ops.append(f"W.{w} {t} {val}" + (" p" if R.random() < 0.2 else ""))
    elif kind == "bool":
        ops.append(f"W.bool {t} {int(val)}")
    elif kind == "f32":
        ops.append(f"W.f32 {t} {val:08x}")
    elif kind == "f64":
        ops.append(f"W.f64 {t} {val:016x}")
    elif kind == "str":
        op = R.choice(["str", "str", "cstr", "strz"])
        ops.append(f"W.{op} {t} {hx(val)}")
    elif kind == "bytes":
        ops.append(f"W.{R.choice(['bytes', 'bspan'])} {t} {hx(val)}")
    elif kind == "null":
        ops.append(f"W.null {t}")
    else:
        ty = {"struct": "S", "array": "A", "list": "L"}[kind]
        if use_open and R.random() < 0.35:
            ops.append(f"W.open {t} {ty}")
            for c in val:
                writer_ops_for(c, ops, kind, use_open)
            ops.append("W.close")
        elif R.random() < 0.1:
            ops.append(f"W.pre {t} {ty} {hx(b''.join(enc(c) for c in val))}")
        else:
            ops.append(f"W.start {t} {ty}")
            for c in val:
                writer_ops_for(c, ops, kind, use_open)
            ops.append("W.end")


def gen_write():
    doc = rand_doc()
    ops = []
    mode = R.choice(["init", "init", "init", "chunks", "vec"])
    size_full = len(enc(doc)) + 8
    if mode == "init":
        size = R.choice([size_full + 32, size_full + 32, max(0, size_full - R.randint(1, 20)), R.randint(0, 12)])
        ops.append(f"W.init {size}")
    elif mode == "chunks":
        ops.append(f"W.initchunks {R.choice([1, 3, 7, 16, 64])} {R.choice([2, 8, 64, 1000])}" +
                   (f" {R.randint(4, size_full + 16)}" if R.random() < 0.3 else ""))
    else:
        ops.append("W.initvec")
    if R.random() < 0.3:
        ops.append(f"W.ipid {R.choice(IMPLICIT):08x}")
    if R.random() < 0.15 and mode == "init":
        ops.append(f"W.reserve {R.randint(0, 20)}")
    writer_ops_for(doc, ops, "top", use_open=R.random() < 0.4)
    # sprinkle extra operations
    for _ in range(R.choice([0, 0, 1, 2])):
        pos = R.randint(1, len(ops))
        extra = R.choice([
            f"W.fmt {tag_tok(rand_tag('list'))} {R.randint(0, 9)} {R.randint(-99999, 99999)} {R.randint(0, 99999)} {R.randint(32, 126)}",
            f"W.fmt {tag_tok(rand_tag('list'))} {R.choice([1, 6, 8, 9])} {hx(rand_text(12))} {hx(rand_text(12))}",
            "W.end", f"W.unreserve {R.randint(0, 8)}", f"W.reserve {R.randint(0, 8)}",
            f"W.copyctb {tag_tok(rand_tag('list'))} {hx(enc(rand_doc()))}",
            f"W.str {tag_tok(rand_tag('list'))} {hx(rand_text(valid=False))}",
            "W.state",
        ])
        ops.insert(pos, extra)
    ops.append("W.state")
    ops.append("W.fin")
    ops.append("W.dump")
    if mode != "chunks" or R.random() < 0.5:
        ops.append("R.fromw")
        ops.append("R.walk 1")
    case("tlv_write", ops)


# ------------------------------------------------------------------------------------------------
# bucket: tlv_read
# ------------------------------------------------------------------------------------------------
def explicit_read_ops(n):
    ops = []
    depth = 0
    for _ in range(n):
        c = R.random()
        if c < 0.35:
            ops.append("R.next")
        elif c < 0.42:
            ops.append(f"R.nextt {tag_tok(rand_tag('struct'))}")
        elif c < 0.47:
            ops.append(f"R.nextty {R.choice(['0', '4', '8', '10', '12', '16', '20', 'S', 'A', 'L'])} {tag_tok(rand_tag('struct'))}")
        elif c < 0.50:
            ops.append(f"R.expect {tag_tok(rand_tag('struct'))}")
        elif c < 0.52:
            ops.append(f"R.expectty {R.choice(['4', '12', 'S'])} {tag_tok(rand_tag('struct'))}")
        elif c < 0.62:
            ops.append("R.enter")
            depth += 1
        elif c < 0.68 and depth:
            ops.append("R.exit")
            depth -= 1
        elif c < 0.71:
            ops.append("R.open")
        elif c < 0.74:
            ops.append("R.close")
        elif c < 0.78:
            ops.append("R.skip")
        elif c < 0.81:
            ops.append("R.veoc")
        elif c < 0.85:
            ops.append(f"R.find {tag_tok(rand_tag('struct'))}")
        elif c < 0.88:
            ops.append("R.cnt")
        elif c < 0.92:
            ops.append("R.getall")
        elif c < 0.95:
            ops.append(f"R.bufs {R.choice([-1, 0, 3])}")
        elif c < 0.97:
            ops.append(f"R.{R.choice(['gbytes', 'gstr'])} {R.randint(0, 40)}")
        else:
            ops.append("R.info")
    return ops


def gen_read():
    doc = rand_doc()
    data = enc(doc, minimal=R.random() < 0.5)
    if R.random() < 0.35:
        data = mutate(data)
    if R.random() < 0.1:
        data = data + enc(rand_doc())          # two top-level elements
    ops = []
    mode = R.choice(["init", "init", "init", "chunks", "cont"])
    if mode == "init":
        ops.append(f"R.init {hx(data)}")
    elif mode == "chunks":
        ops.append(f"R.initc {hx(data)} {R.choice([1, 2, 3, 5, 8, 17])}" +
                   (f" {R.randint(1, len(data) + 4)}" if R.random() < 0.2 else ""))
    else:
        ops.append(f"R.initcont {hx(data)}")
    if R.random() < 0.4:
        ops.append(f"R.ipid {R.choice(IMPLICIT):08x}")
    if R.random() < 0.5:
        ops.append(f"R.walk {R.choice([0, 1, 1, 2])}")
    else:
        ops += explicit_read_ops(R.randint(4, 30))
        if mode == "cont":
            ops.insert(R.randint(2, len(ops)), R.choice(["R.gsv", "R.gbv"]))
    case("tlv_read", ops)


# ------------------------------------------------------------------------------------------------
# bucket: tlv_tools (utilities, debug dump, updater, copy, circular buffer)
# ------------------------------------------------------------------------------------------------
def gen_tools():
    k = R.choice(["util", "util", "dump", "dump", "upd", "upd", "copy", "circ", "circ"])
    ops = []
    if k == "util":
        doc = rand_doc()
        data = enc(doc)
        if R.random() < 0.15:
            data = mutate(data)
        for _ in range(R.randint(1, 4)):
            ops.append(f"R.init {hx(data)}")
            ops.append(f"R.ipid {R.choice(IMPLICIT):08x}")
            if R.random() < 0.6:
                ops.append("R.next")
            if R.random() < 0.3:
                ops.append("R.enter")
            ops.append(R.choice([
                "U.count", "U.count r", "U.count n",
                f"U.find {tag_tok(rand_tag('struct'))}", f"U.find {tag_tok(rand_tag('struct'))} r",
                f"U.findn {R.randint(0, 8)}", f"U.findn {R.randint(0, 8)} r",
                "U.iter", "U.iter r", f"U.iter {R.randint(0, 5)} r",
            ]))
    elif k == "dump":
        data = enc(rand_doc(), minimal=R.random() < 0.7)
        if R.random() < 0.15:
            data = mutate(data)
        ops.append(f"R.init {hx(data)}")
        ops.append(f"R.ipid {R.choice(IMPLICIT):08x}")
        if R.random() < 0.7:
            ops.append("R.next")
        ops.append("D.dump")
        if R.random() < 0.1:
            ops.append("D.names")
    elif k == "upd":
        doc = rand_doc()
        data = enc(doc)
        maxlen = len(data) + R.choice([0, 2, 8, 64])
        ops.append(f"P.init {hx(data)} {maxlen}")
        if R.random() < 0.3:
            ops.append(f"P.ipid {R.choice(IMPLICIT):08x}")
        depth = 0
        for _ in range(R.randint(2, 14)):
            c = R.random()
            if c < 0.3:
                ops.append("P.next")
            elif c < 0.45:
                ops.append("P.move")
            elif c < 0.55:
                ops.append("P.enter")
                depth += 1
            elif c < 0.62 and depth:
                ops.append("P.exit")
                depth -= 1
            elif c < 0.72:
                t = tag_tok(rand_tag("struct"))
                ops.append(R.choice([f"P.u32 {t} {rand_u(32)}", f"P.i64 {t} {rand_i()}", f"P.bool {t} 1",
                                     f"P.null {t}", f"P.str {t} {hx(rand_text(10))}", f"P.u8 {t} {rand_u(8)} p"]))
            elif c < 0.78:
                ops.append(f"P.start {tag_tok(rand_tag('struct'))} {R.choice(['S', 'A', 'L'])}")
            elif c < 0.82:
                ops.append("P.end")
            elif c < 0.88:
                ops.append("P.getall")
            else:
                ops.append("P.moveend")
        ops.append("P.moveend")
        ops.append("P.fin")
        ops.append("P.dump")
    elif k == "copy":
        src = enc(rand_doc())
        if R.random() < 0.1:
            src = mutate(src)
        ops.append(f"R.init {hx(src)}")
        ops.append(f"W.init {R.choice([len(src) + 20, len(src) + 20, max(0, len(src) - 3)])}")
        ops.append("W.start a S")
        for _ in range(R.randint(1, 3)):
            ops.append(R.choice(["R.next", "R.next", "R.enter", "R.next"]))
            ops.append(R.choice([f"W.copyel", f"W.copyel {tag_tok(rand_tag('struct'))}", "W.copyct",
                                 f"W.copyct {tag_tok(rand_tag('struct'))}"]))
        ops.append("W.end")
        ops.append("W.fin")
        ops.append("W.dump")
    else:
        size = R.choice([16, 24, 32, 48, 64, 100])
        head = R.choice([0, 0, R.randint(1, size - 1)])
        limit = R.choice([-1, -1, 0, 1, 2])
        ops.append(f"C.init {size} {head} {limit}")
        ops.append("W.initcirc")
        for _ in range(R.randint(2, 12)):
            t = tag_tok(rand_tag("top"))
            ops.append(R.choice([f"W.u32 {t} {rand_u(32)}", f"W.str {t} {hx(rand_text(14))}",
                                 f"W.bytes {t} {hx(rand_bytes(20))}", f"W.i64 {t} {rand_i()}",
                                 f"W.bool {t} 0", f"W.null {t}"]))
            if R.random() < 0.15:
                ops.append("W.start a S")
                ops.append(f"W.u16 c1 {rand_u(16)}")
                ops.append("W.end")
            if R.random() < 0.1:
                ops.append("C.evict")
            if R.random() < 0.15:
                ops.append("C.state")
        ops.append("W.fin")
        ops.append("C.state")
        ops.append("R.initcirc")
        ops.append("R.walk 0")
    case("tlv_tools", ops)


# ------------------------------------------------------------------------------------------------
# bucket: msg_header
# ------------------------------------------------------------------------------------------------
def rand_packet():
    sec = R.choice([0, 0, 1, 0x80, 0x81, 0x20, 0x40, 0x02, 0x03, R.getrandbits(8)])
    sid = R.choice([0, 1, 0xFFFF, R.getrandbits(16)])
    ctr = R.choice([0, 1, 0xFFFFFFFF, R.getrandbits(32)])
    src = R.choice(["-", f"{R.getrandbits(64):x}", f"{R.getrandbits(16):x}"])
    dst, grp = "-", "-"
    c = R.random()
    if c < 0.35:
        dst = f"{R.getrandbits(64):x}"
    elif c < 0.6:
        grp = str(R.getrandbits(16))
    elif c < 0.65:
        dst, grp = f"{R.getrandbits(64):x}", str(R.getrandbits(16))
    extra = R.choice([0, 0, 0, 0x20, 0x10, 0x30, 0x08, R.getrandbits(8)])
    return sec, sid, ctr, src, dst, grp, extra


def enc_packet(sec, sid, ctr, src, dst, grp, extra):
    mf = 0
    tail = b""
    if src != "-":
        mf |= 0x04
        tail += struct.pack("<Q", int(src, 16))
    if dst != "-":
        mf |= 0x01
        tail += struct.pack("<Q", int(dst, 16))
    elif grp != "-":
        mf |= 0x02
        tail += struct.pack("<H", int(grp))
    mf |= extra & 0xF8
    return bytes([mf]) + struct.pack("<HBI", sid, sec, ctr) + tail


def gen_header():
    ops = []
    for _ in range(R.randint(1, 4)):
        c = R.random()
        if c < 0.3:
            sec, sid, ctr, src, dst, grp, extra = rand_packet()
            size = R.choice([64, 64, R.randint(0, 30)])
            ops.append(f"H.penc {sec} {sid} {ctr} {src} {dst} {grp} {size} {extra if R.random() < 0.3 else 0}")
        elif c < 0.6:
            p = enc_packet(*rand_packet())
            if R.random() < 0.6:
                p += bytes(R.getrandbits(8) for _ in range(R.choice([0, 4, 16, 20])))
            if R.random() < 0.3:
                p = mutate(p)
            ops.append(f"H.pdec {hx(p)}" + (" r" if R.random() < 0.6 else ""))
        elif c < 0.78:
            vid = R.choice([0, 0, 0xFFF1, R.getrandbits(16)])
            ack = R.choice(["-", "-", str(R.getrandbits(32))])
            ops.append(f"H.yenc {R.getrandbits(2)} {R.getrandbits(16)} {vid} {R.choice([0, 1, 2, 3, R.getrandbits(16)])} "
                       f"{R.getrandbits(8)} {ack} {R.choice([64, 64, R.randint(0, 12)])}")
        else:
            xf = R.choice([0, 1, 2, 3, 0x10, 0x11, 0x08, 0x05, R.getrandbits(8)])
            p = bytes([xf, R.getrandbits(8)]) + struct.pack("<HH", R.getrandbits(16), R.choice([0, 1, R.getrandbits(16)]))
            if xf & 0x10:
                p += struct.pack("<H", R.getrandbits(16))
            if xf & 0x02:
                p += struct.pack("<I", R.getrandbits(32))
            if xf & 0x08:
                n = R.choice([0, 2, 5])
                p += struct.pack("<H", n) + bytes(R.getrandbits(8) for _ in range(n))
            if R.random() < 0.3:
                p = mutate(p)
            ops.append(f"H.ydec {hx(p)}" + (" r" if R.random() < 0.6 else ""))
    case("msg_header", ops)


# ------------------------------------------------------------------------------------------------
# bucket: json_tlv
# ------------------------------------------------------------------------------------------------
def json_value(depth=0, forced=None):
    t = forced or R.choice(["UINT", "INT", "BOOL", "FLOAT", "DOUBLE", "BYTES", "STRING", "NULL", "STRUCT", "ARRAY",
                            "UINT", "INT", "STRING"])
    if t == "STRUCT" and depth > 2:
        t = "UINT"
    if t == "ARRAY" and depth > 2:
        t = "INT"
    if t == "UINT":
        v = rand_u()
        return t, (str(v) if v >= 2**32 and R.random() < 0.85 else v)
    if t == "INT":
        v = rand_i()
        return t, (str(v) if not -2**31 <= v < 2**31 and R.random() < 0.85 else v)
    if t == "BOOL":
        return t, R.random() < 0.5
    if t in ("FLOAT", "DOUBLE"):
        c = R.random()
        if c < 0.1:
            return t, R.choice(["Infinity", "-Infinity"])
        if c < 0.4:
            return t, R.randint(-70000, 70000)
        return t, round(R.uniform(-1e5, 1e5), R.randint(0, 6))
    if t == "BYTES":
        return t, base64.b64encode(rand_bytes(24)).decode()
    if t == "STRING":
        return t, rand_text(16).decode("utf-8", "replace")
    if t == "NULL":
        return t, None
    if t == "STRUCT":
        return t, json_struct(depth + 1)
    sub = R.choice(["UINT", "INT", "BOOL", "STRING", "BYTES", "DOUBLE", "FLOAT", "STRUCT", "NULL", "?"])
    if sub == "?":
        return "ARRAY-?", []
    items = [json_value(depth + 1, sub)[1] for _ in range(R.randint(0, 4))]
    return f"ARRAY-{sub}", items


def json_struct(depth=0):
    d = {}
    ids = sorted(R.sample(range(0, 300), R.randint(0, 5)))
    for fid in ids:
        if R.random() < 0.05:
            fid = R.choice([0xFFF10001, 0x00010010, 65536, 2**32])
        t, v = json_value(depth)
        name = (R.choice(["alpha", "x", "valueName"]) + ":") if R.random() < 0.2 else ""
        d[f"{name}{fid}:{t}"] = v
    return d


def corrupt_json(s):
    c = R.random()
    if c < 0.25:
        return s[:R.randrange(max(1, len(s)))]
    if c < 0.45:
        return s.replace(":UINT", ":UINT8", 1).replace(":INT", ":INTX", 1)
    if c < 0.6:
        return s.replace("\"", "", 2)
    if c < 0.75:
        return "[" + s + "]"
    if c < 0.85:
        return s.replace(":STRUCT", ":ARRAY-STRUCT", 1)
    return s.replace("1:", "a:", 1)


def gen_json():
    ops = []
    for _ in range(R.randint(1, 3)):
        c = R.random()
        if c < 0.4:
            doc = json_struct()
            js = json.dumps(doc, ensure_ascii=R.random() < 0.5, indent=R.choice([None, 2]))
            if R.random() < 0.25:
                js = corrupt_json(js)
            size = R.choice([1024, 1024, 4096, R.randint(0, 40)])
            ops.append(f"J.{R.choice(['j2t', 'j2t', 'j2tw'])} {hx(js.encode())} {size}")
        elif c < 0.8:
            # TLV in data-model shape (anonymous struct, context tags) and arbitrary TLV
            if R.random() < 0.6:
                kids = []
                for n in sorted(R.sample(range(0, 40), R.randint(0, 6))):
                    el = rand_tree(1, "struct")
                    kids.append((("ctx", n),) + el[1:])
                doc = (("anon",), "struct", kids)
            else:
                doc = rand_doc()
            data = enc(doc)
            if R.random() < 0.1:
                data = mutate(data)
            ops.append(f"J.{R.choice(['t2j', 't2j', 't2j', 'old'])} {hx(data)}")
        elif c < 0.9:
            ops.append(f"J.tag {R.choice([0, 1, 255, 256, 0xFFFF, 0x10000, 0xFFF10001, 0x00010010, R.getrandbits(32)])}")
        else:
            js = json.dumps(json_struct())
            ops.append(f"J.pretty {hx(js.encode())}")
    case("json_tlv", ops)


# ------------------------------------------------------------------------------------------------
# bucket: onboarding
# ------------------------------------------------------------------------------------------------
B38 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-."


def rand_fields(valid_bias=0.7):
    ok = R.random() < valid_bias
    ver = 0 if ok or R.random() < 0.5 else R.randint(1, 7)
    vid = R.choice([0, 0xFFF1, 0xFFF4, R.getrandbits(16)])
    pid = R.choice([0, 0x8000, 0x8001, R.getrandbits(16)])
    flow = R.choice([0, 0, 1, 2]) if ok else R.randint(0, 3)
    rv = R.choice(["2", "4", "6", "1", "8", "16", "32", "-"]) if ok else R.choice(["0", "255", "64", "-", "3"])
    disc = (f"L{R.getrandbits(12)}" if R.random() < 0.85 else f"S{R.getrandbits(4)}")
    pin = R.choice([20202021, 12345679, 1, 99999998, R.randint(1, 99999998)]) if ok else \
        R.choice([0, 11111111, 22222222, 33333333, 44444444, 55555555, 66666666, 77777777, 88888888, 99999999,
                  12345678, 87654321, 99999999 + 1, R.getrandbits(27)])
    return f"{ver},{vid},{pid},{flow},{rv},{disc},{pin}"


def rand_opt():
    items = []
    for _ in range(R.choice([0, 0, 1, 2, 3])):
        c = R.random()
        if c < 0.35:
            items.append(f"s{R.choice([0x80, 0x81, 0xFF, R.randint(0x80, 0xFF), R.randint(0, 0x7F)])}={hx(rand_text(12))}")
        elif c < 0.7:
            items.append(f"i{R.choice([0x80, 0x82, R.randint(0x80, 0xFF), R.randint(0, 0x7F)])}={rand_i(32)}")
        elif c < 0.85:
            items.append(f"N={hx(rand_text(20))}")
        elif c < 0.95:
            items.append(f"n={rand_u(32)}")
        else:
            items.append(R.choice(["R", f"r{R.randint(0x80, 0xFF)}"]))
    return ";".join(items) if items else "-"


def b38_random(n):
    return "".join(R.choice(B38) for _ in range(n))


def gen_onboarding():
    ops = []
    for _ in range(R.randint(1, 4)):
        c = R.random()
        if c < 0.2:
            f, o = rand_fields(), rand_opt()
            ops.append(f"Q.gen {f} {o} {R.choice(['0', '0', '1'])} {R.choice([0, 64, 128, 512, 3])}")
            ops.append(f"Q.basic {f} {R.choice([128, 128, 22, 23, 10])}")
        elif c < 0.42:
            # parse: a valid string produced by our own encoder of the QR bit layout, possibly corrupted
            s = qr_string()
            if R.random() < 0.35:
                s = corrupt_str(s)
            ops.append(f"Q.parse {hx(s.encode())}")
        elif c < 0.55:
            ops.append(f"M.gen {rand_fields()} {R.choice(['0', '0', '1'])} {R.choice(['0', '0', '1'])} {R.choice([40, 40, 11, 12, 21, 22])}")
        elif c < 0.67:
            s = manual_string()
            if R.random() < 0.35:
                s = corrupt_str(s, digits=True)
            ops.append(f"M.parse {hx(s.encode())}")
        elif c < 0.75:
            b = rand_bytes(30)
            ops.append(f"B.enc {hx(b)} {R.choice([512, 512, len(b) * 2, R.randint(0, 20)])}")
        elif c < 0.83:
            s = b38_random(R.choice([0, 1, 2, 3, 4, 5, 10, 15, R.randint(0, 40)]))
            if R.random() < 0.2:
                s = s[:max(0, len(s) - 1)] + R.choice(["a", "*", "/", " ", "ZZZ"])
            ops.append(f"B.dec {hx(s.encode())}")
        elif c < 0.88:
            rid = bytes(R.getrandbits(8) for _ in range(R.choice([18, 18, 0, 5, 17, 19, 30])))
            kind = R.choice(["bytes", "bytes", "bytes", "str", "uint"])
            val = len(rid) if kind == "uint" else rid
            tlv = enc((("anon",), "struct", [(("ctx", R.choice([0, 0, 0, 1])), kind, val)]))
            if R.random() < 0.2:
                tlv = mutate(tlv)
            ops.append(f"A.parse {hx(tlv)}")
        elif c < 0.93:
            ops.append(f"S.valid {rand_fields(0.5)}")
        elif c < 0.97:
            ops.append(f"S.opt {rand_fields()} {rand_opt()} {R.randint(0x80, 0x84)}")
        else:
            parts = [qr_string() for _ in range(R.randint(1, 3))] if R.random() < 0.6 else [manual_string()]
            s = parts[0] + "".join("*" + p[3:] for p in parts[1:]) if parts[0].startswith("MT:") else parts[0]
            ops.append(f"S.str {hx(s.encode())}")
    case("onboarding", ops)


def verhoeff(digits):
    d = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
         [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
         [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
         [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
    p = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
         [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
         [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = d[c][p[(i + 1) % 8][int(ch)]]
    return str(inv[c])


def manual_string():
    """Manual pairing code from the Matter spec 5.1.4 layout (independent encoder)."""
    disc = R.getrandbits(4)
    pin = R.choice([20202021, R.randint(1, 99999998), R.getrandbits(27)])
    long_ = R.random() < 0.4
    flow_bit = 1 if long_ else 0
    if R.random() < 0.1:
        flow_bit ^= 1
    vid = 0 if R.random() < 0.3 else R.getrandbits(16)
    pid = R.getrandbits(16)
    c1 = (R.choice([0, 0, 0, 1]) << 3) | (flow_bit << 2) | (disc >> 2)
    c2 = ((disc & 3) << 14) | (pin & 0x3FFF)
    c3 = pin >> 14
    s = f"{c1}{c2:05d}{c3:04d}"
    if long_:
        s += f"{vid:05d}{pid:05d}"
    if R.random() < 0.15:
        s = s[:-1] + str((int(s[-1]) + 1) % 10)
    s += verhoeff(s)
    if R.random() < 0.2:
        s = s[:4] + "-" + s[4:7] + "-" + s[7:]
    return s


def b38enc(data):
    out = []
    for i in range(0, len(data), 3):
        chunk = data[i:i + 3]
        v = int.from_bytes(chunk, "little")
        n = {1: 2, 2: 4, 3: 5}[len(chunk)]
        for _ in range(n):
            out.append(B38[v % 38])
            v //= 38
    return "".join(out)


def qr_string():
    """QR payload from the Matter spec 5.1.3 bit layout (independent encoder), with optional TLV data."""
    ver = 0 if R.random() < 0.9 else R.randint(1, 7)
    vid, pid = R.getrandbits(16), R.getrandbits(16)
    flow = R.choice([0, 0, 1, 2, 3])
    rv = R.choice([2, 4, 6, 1, 0x20, 0x22, 0, 0xFF])
    disc = R.getrandbits(12)
    pin = R.choice([20202021, R.randint(1, 99999998), R.choice([0, 11111111, 12345678, 99999999])])
    bits = ver | (vid << 3) | (pid << 19) | (flow << 35) | (rv << 37) | (disc << 45) | (pin << 57)
    pad = 0 if R.random() < 0.95 else 1
    bits |= pad << 84
    data = bits.to_bytes(11, "little")
    if R.random() < 0.4:
        kids = []
        if R.random() < 0.6:
            kids.append((("ctx", 0), "str", rand_text(16)) if R.random() < 0.6 else (("ctx", 0), "uint", rand_u(32)))
        for _ in range(R.randint(0, 3)):
            t = R.choice([R.randint(0x80, 0xFF), R.randint(1, 4)])
            kids.append((("ctx", t), R.choice(["str", "int", "uint", "int"]),
                         None))
        kids = [(k[0], k[1], rand_text(10) if k[1] == "str" else (rand_i(32) if k[1] == "int" else rand_u(32)))
                if k[2] is None else k for k in kids]
        tlv = enc((("anon",), "struct", kids))
        data += tlv
    return "MT:" + b38enc(data)


def corrupt_str(s, digits=False):
    if not s:
        return s
    c = R.random()
    i = R.randrange(len(s))
    if c < 0.3:
        alphabet = "0123456789" if digits else B38
        return s[:i] + R.choice(alphabet) + s[i + 1:]
    if c < 0.5:
        return s[:i]
    if c < 0.65:
        return s + R.choice(["0", "A", "-", "00000"])
    if c < 0.8:
        return s.replace("MT:", R.choice(["mt:", "MT", "XX:", ""]), 1)
    return s[:i] + R.choice([" ", "a", "!", "*"]) + s[i:]


GENS = [("tlv_write", gen_write, 700), ("tlv_read", gen_read, 900), ("tlv_tools", gen_tools, 700),
        ("msg_header", gen_header, 300), ("json_tlv", gen_json, 500), ("onboarding", gen_onboarding, 600)]

for name, fn, n in GENS:
    for _ in range(max(1, int(n * args.scale))):
        fn()
print("\n".join(out))
