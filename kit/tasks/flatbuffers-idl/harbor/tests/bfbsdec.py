"""Decode a binary schema (.bfbs, reflection/reflection.fbs) into a canonical JSON text.

Used by collect.py for the schema_model bucket: two binary schemas that describe the same schema decode to the
same text, whatever order their builder wrote the objects in. Every read is bounds-checked; a malformed buffer
raises ValueError. Defaults from reflection.fbs are applied, so a field written with its default value and a
field left out decode alike.
"""
import json
import struct

BASE_TYPES = ["None", "UType", "Bool", "Byte", "UByte", "Short", "UShort", "Int", "UInt", "Long", "ULong",
              "Float", "Double", "String", "Vector", "Obj", "Union", "Array", "Vector64", "MaxBaseType"]

# field name, kind, default; slot order is the field id
S = "string"
TYPE = [("base_type", "i8", 0), ("element", "i8", 0), ("index", "i32", -1), ("fixed_length", "u16", 0),
        ("base_size", "u32", 4), ("element_size", "u32", 0)]
KEYVALUE = [("key", S, None), ("value", S, None)]
ENUMVAL = [("name", S, None), ("value", "i64", 0), ("object", "skip", None), ("union_type", ("t", "TYPE"), None),
           ("documentation", ("vs",), None), ("attributes", ("vt", "KEYVALUE"), None)]
ENUM = [("name", S, None), ("values", ("vt", "ENUMVAL"), None), ("is_union", "bool", False),
        ("underlying_type", ("t", "TYPE"), None), ("attributes", ("vt", "KEYVALUE"), None),
        ("documentation", ("vs",), None), ("declaration_file", S, None)]
FIELD = [("name", S, None), ("type", ("t", "TYPE"), None), ("id", "u16", 0), ("offset", "u16", 0),
         ("default_integer", "i64", 0), ("default_real", "f64", 0.0), ("deprecated", "bool", False),
         ("required", "bool", False), ("key", "bool", False), ("attributes", ("vt", "KEYVALUE"), None),
         ("documentation", ("vs",), None), ("optional", "bool", False), ("padding", "u16", 0),
         ("offset64", "bool", False)]
OBJECT = [("name", S, None), ("fields", ("vt", "FIELD"), None), ("is_struct", "bool", False),
          ("minalign", "i32", 0), ("bytesize", "i32", 0), ("attributes", ("vt", "KEYVALUE"), None),
          ("documentation", ("vs",), None), ("declaration_file", S, None)]
RPCCALL = [("name", S, None), ("request", ("ref",), None), ("response", ("ref",), None),
           ("attributes", ("vt", "KEYVALUE"), None), ("documentation", ("vs",), None)]
SERVICE = [("name", S, None), ("calls", ("vt", "RPCCALL"), None), ("attributes", ("vt", "KEYVALUE"), None),
           ("documentation", ("vs",), None), ("declaration_file", S, None)]
SCHEMAFILE = [("filename", S, None), ("included_filenames", ("vs",), None)]
SCHEMA = [("objects", ("vt", "OBJECT"), None), ("enums", ("vt", "ENUM"), None), ("file_ident", S, None),
          ("file_ext", S, None), ("root_table", ("ref",), None), ("services", ("vt", "SERVICE"), None),
          ("advanced_features", "u64", 0), ("fbs_files", ("vt", "SCHEMAFILE"), None)]
TABLES = {"TYPE": TYPE, "KEYVALUE": KEYVALUE, "ENUMVAL": ENUMVAL, "ENUM": ENUM, "FIELD": FIELD,
          "OBJECT": OBJECT, "RPCCALL": RPCCALL, "SERVICE": SERVICE, "SCHEMAFILE": SCHEMAFILE}
SCAL = {"i8": ("<b", 1), "u8": ("<B", 1), "bool": ("<B", 1), "i16": ("<h", 2), "u16": ("<H", 2),
        "i32": ("<i", 4), "u32": ("<I", 4), "i64": ("<q", 8), "u64": ("<Q", 8), "f64": ("<d", 8)}
MAX_ITEMS = 200000


class Reader:
    def __init__(self, buf):
        self.b = bytes(buf)
        self.n = len(self.b)
        self.items = 0

    def get(self, fmt, size, pos):
        if pos < 0 or pos + size > self.n:
            raise ValueError("read out of bounds at %d" % pos)
        return struct.unpack_from(fmt, self.b, pos)[0]

    def deref(self, pos):
        return pos + self.get("<I", 4, pos)

    def string(self, pos):
        p = self.deref(pos)
        ln = self.get("<I", 4, p)
        if p + 4 + ln + 1 > self.n:
            raise ValueError("string out of bounds")
        if self.b[p + 4 + ln] != 0:
            raise ValueError("string not terminated")
        self.items += 1
        return self.b[p + 4:p + 4 + ln].decode("utf-8", "surrogateescape")

    def vector(self, pos):
        p = self.deref(pos)
        ln = self.get("<I", 4, p)
        if ln > MAX_ITEMS or p + 4 + 4 * ln > self.n:
            raise ValueError("vector out of bounds")
        self.items += ln
        if self.items > MAX_ITEMS:
            raise ValueError("too many items")
        return [p + 4 + 4 * i for i in range(ln)]

    def table(self, tpos, spec, depth):
        if depth > 12:
            raise ValueError("nesting too deep")
        vt = tpos - self.get("<i", 4, tpos)
        vlen = self.get("<H", 2, vt)
        tlen = self.get("<H", 2, vt + 2)
        if vlen < 4 or vlen % 2 or tpos + tlen > self.n:
            raise ValueError("bad vtable")
        out = {}
        for i, (name, kind, dflt) in enumerate(spec):
            slot = 4 + 2 * i
            off = self.get("<H", 2, vt + slot) if slot + 2 <= vlen else 0
            if off and off >= tlen:
                raise ValueError("field offset past table end")
            pos = tpos + off
            if kind == "skip":
                continue
            if isinstance(kind, str) and kind in SCAL:
                fmt, sz = SCAL[kind]
                v = self.get(fmt, sz, pos) if off else dflt
                if kind == "bool":
                    v = bool(v)
                if kind == "f64" and v != v:
                    v = "nan"
                elif kind == "f64" and v in (float("inf"), float("-inf")):
                    v = repr(v)
                out[name] = v
            elif kind == S:
                out[name] = self.string(pos) if off else None
            elif kind[0] == "vs":
                out[name] = [self.string(p) for p in self.vector(pos)] if off else None
            elif kind[0] == "t":
                out[name] = self.table(self.deref(pos), TABLES[kind[1]], depth + 1) if off else None
            elif kind[0] == "vt":
                out[name] = [self.table(self.deref(p), TABLES[kind[1]], depth + 1)
                             for p in self.vector(pos)] if off else None
            elif kind[0] == "ref":
                # a reference to an Object: identified by its name
                out[name] = self.table(self.deref(pos), OBJECT[:1], depth + 1)["name"] if off else None
        if "base_type" in out:
            for k in ("base_type", "element"):
                v = out[k]
                out[k] = BASE_TYPES[v] if 0 <= v < len(BASE_TYPES) else v
        return out


def decode(buf):
    r = Reader(buf)
    if r.n < 8:
        raise ValueError("buffer too small")
    root = r.deref(0)
    ident = r.b[4:8].decode("latin-1")
    out = r.table(root, SCHEMA, 0)
    out["_ident"] = ident
    return json.dumps(out, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], "rb") as f:
        print(decode(f.read()))
