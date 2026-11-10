"""Minimal msgpack codec with ordered maps (duplicate keys kept) and strict type tags.

Values: MMap (list of (key, value) pairs), list (array), str, Bin (bytes), int, bool, None, float.
canon() turns a value into a hashable, type-strict tuple so that True != 1 and str != bin.
"""
import struct


class MMap(list):
    """An ordered msgpack map: a list of (key, value) pairs."""


class Bin(bytes):
    pass


def _pack(v, out):
    if v is None:
        out.append(0xC0)
    elif v is True:
        out.append(0xC3)
    elif v is False:
        out.append(0xC2)
    elif isinstance(v, int):
        if 0 <= v < 0x80:
            out.append(v)
        elif -32 <= v < 0:
            out.append(v & 0xFF)
        elif 0 <= v <= 0xFF:
            out += b"\xcc" + struct.pack(">B", v)
        elif 0 <= v <= 0xFFFF:
            out += b"\xcd" + struct.pack(">H", v)
        elif 0 <= v <= 0xFFFFFFFF:
            out += b"\xce" + struct.pack(">I", v)
        elif v >= 0:
            out += b"\xcf" + struct.pack(">Q", v)
        elif v >= -0x80:
            out += b"\xd0" + struct.pack(">b", v)
        elif v >= -0x8000:
            out += b"\xd1" + struct.pack(">h", v)
        elif v >= -0x80000000:
            out += b"\xd2" + struct.pack(">i", v)
        else:
            out += b"\xd3" + struct.pack(">q", v)
    elif isinstance(v, float):
        out += b"\xcb" + struct.pack(">d", v)
    elif isinstance(v, Bin):
        n = len(v)
        if n <= 0xFF:
            out += b"\xc4" + struct.pack(">B", n)
        elif n <= 0xFFFF:
            out += b"\xc5" + struct.pack(">H", n)
        else:
            out += b"\xc6" + struct.pack(">I", n)
        out += v
    elif isinstance(v, str):
        b = v.encode("utf-8", "surrogateescape")
        n = len(b)
        if n < 32:
            out.append(0xA0 | n)
        elif n <= 0xFF:
            out += b"\xd9" + struct.pack(">B", n)
        elif n <= 0xFFFF:
            out += b"\xda" + struct.pack(">H", n)
        else:
            out += b"\xdb" + struct.pack(">I", n)
        out += b
    elif isinstance(v, MMap):
        n = len(v)
        if n < 16:
            out.append(0x80 | n)
        elif n <= 0xFFFF:
            out += b"\xde" + struct.pack(">H", n)
        else:
            out += b"\xdf" + struct.pack(">I", n)
        for k, x in v:
            _pack(k, out)
            _pack(x, out)
    elif isinstance(v, list):
        n = len(v)
        if n < 16:
            out.append(0x90 | n)
        elif n <= 0xFFFF:
            out += b"\xdc" + struct.pack(">H", n)
        else:
            out += b"\xdd" + struct.pack(">I", n)
        for x in v:
            _pack(x, out)
    else:
        raise TypeError("cannot pack %r" % (type(v),))


def packb(v) -> bytes:
    out = bytearray()
    _pack(v, out)
    return bytes(out)


def unpackb(data: bytes):
    v, off = _unpack(data, 0)
    if off != len(data):
        raise ValueError("trailing bytes")
    return v


def _unpack(d, i):
    b = d[i]
    i += 1
    if b <= 0x7F:
        return b, i
    if b >= 0xE0:
        return b - 0x100, i
    if 0x80 <= b <= 0x8F:
        return _map(d, i, b & 0x0F)
    if 0x90 <= b <= 0x9F:
        return _arr(d, i, b & 0x0F)
    if 0xA0 <= b <= 0xBF:
        n = b & 0x1F
        return d[i:i + n].decode("utf-8", "surrogateescape"), i + n
    if b == 0xC0:
        return None, i
    if b == 0xC2:
        return False, i
    if b == 0xC3:
        return True, i
    if b in (0xC4, 0xC5, 0xC6):
        w = {0xC4: 1, 0xC5: 2, 0xC6: 4}[b]
        n = int.from_bytes(d[i:i + w], "big")
        i += w
        return Bin(d[i:i + n]), i + n
    if b == 0xCA:
        return struct.unpack(">f", d[i:i + 4])[0], i + 4
    if b == 0xCB:
        return struct.unpack(">d", d[i:i + 8])[0], i + 8
    if b in (0xCC, 0xCD, 0xCE, 0xCF):
        w = {0xCC: 1, 0xCD: 2, 0xCE: 4, 0xCF: 8}[b]
        return int.from_bytes(d[i:i + w], "big"), i + w
    if b in (0xD0, 0xD1, 0xD2, 0xD3):
        w = {0xD0: 1, 0xD1: 2, 0xD2: 4, 0xD3: 8}[b]
        return int.from_bytes(d[i:i + w], "big", signed=True), i + w
    if b in (0xD9, 0xDA, 0xDB):
        w = {0xD9: 1, 0xDA: 2, 0xDB: 4}[b]
        n = int.from_bytes(d[i:i + w], "big")
        i += w
        return d[i:i + n].decode("utf-8", "surrogateescape"), i + n
    if b in (0xDC, 0xDD):
        w = 2 if b == 0xDC else 4
        n = int.from_bytes(d[i:i + w], "big")
        return _arr(d, i + w, n)
    if b in (0xDE, 0xDF):
        w = 2 if b == 0xDE else 4
        n = int.from_bytes(d[i:i + w], "big")
        return _map(d, i + w, n)
    raise ValueError("unsupported msgpack type 0x%02x" % b)


def _map(d, i, n):
    m = MMap()
    for _ in range(n):
        k, i = _unpack(d, i)
        v, i = _unpack(d, i)
        m.append((k, v))
    return m, i


def _arr(d, i, n):
    a = []
    for _ in range(n):
        v, i = _unpack(d, i)
        a.append(v)
    return a, i


def canon(v):
    if v is None:
        return ("n",)
    if v is True or v is False:
        return ("t", v)
    if isinstance(v, int):
        return ("i", v)
    if isinstance(v, float):
        return ("f", v)
    if isinstance(v, Bin):
        return ("b", bytes(v))
    if isinstance(v, str):
        return ("s", v)
    if isinstance(v, MMap):
        return ("m", tuple((canon(k), canon(x)) for k, x in v))
    if isinstance(v, list):
        return ("a", tuple(canon(x) for x in v))
    raise TypeError(type(v))


def to_json(v):
    """A JSON-able view for display (maps become lists of pairs to keep order and duplicates)."""
    if isinstance(v, MMap):
        return {"__map__": [[to_json(k), to_json(x)] for k, x in v]}
    if isinstance(v, list):
        return [to_json(x) for x in v]
    if isinstance(v, Bin):
        return {"__bin__": bytes(v).hex()}
    return v


def from_json(v):
    if isinstance(v, dict):
        if "__map__" in v:
            return MMap((from_json(k), from_json(x)) for k, x in v["__map__"])
        if "__bin__" in v:
            return Bin(bytes.fromhex(v["__bin__"]))
        return MMap((k, from_json(x)) for k, x in v.items())
    if isinstance(v, list):
        return [from_json(x) for x in v]
    return v
