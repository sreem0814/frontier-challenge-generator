"""Random FlatBuffers schema worlds: a model of enums, unions, structs, tables and services spread over one or
more .fbs files (with includes and namespaces), emitted as schema text with randomized formatting, plus JSON
documents for a root table. The model is only a generator aid: the reference flatc decides what every schema
means, so a generated schema it rejects simply becomes a diagnostics case.
"""
import json
import math
import random

SCALARS = {
    "bool": ("b", 1), "byte": ("i", 1), "int8": ("i", 1), "ubyte": ("u", 1), "uint8": ("u", 1),
    "short": ("i", 2), "int16": ("i", 2), "ushort": ("u", 2), "uint16": ("u", 2),
    "int": ("i", 4), "int32": ("i", 4), "uint": ("u", 4), "uint32": ("u", 4),
    "long": ("i", 8), "int64": ("i", 8), "ulong": ("u", 8), "uint64": ("u", 8),
    "float": ("f", 4), "float32": ("f", 4), "double": ("f", 8), "float64": ("f", 8),
}
INTS = [k for k, v in SCALARS.items() if v[0] in "iu"]
UINTS = [k for k, v in SCALARS.items() if v[0] == "u"]
FLOATS = [k for k, v in SCALARS.items() if v[0] == "f"]

WORDS = ("alpha beta gamma delta omega kappa sigma theta lambda zeta orbit comet nova pulsar quasar nebula "
         "meadow river canyon haven valley summit glacier delta forest prairie tundra lagoon reef atoll "
         "copper silver nickel cobalt zinc iron tin lead argon neon xenon helium boron carbon "
         "falcon heron osprey raven sparrow kestrel condor pelican puffin swift wren finch "
         "anchor bridge castle tower gate market garden mill forge quarry depot hangar "
         "signal packet frame header record entry sample event metric vector matrix tensor "
         "count total limit offset index level stage phase epoch tick span width height depth "
         "name label title note tag color shade tone hue mode kind flavor state status").split()
KEYWORDISH = ["type", "class", "self", "async", "await", "default", "union", "struct", "enum", "func", "fn",
              "let", "var", "val", "object", "string", "int", "match", "move", "ref", "in", "is", "as", "new",
              "namespace", "table", "import", "package", "end", "nil", "None", "true", "def", "static"]
DOCS = ["The main record.", "Holds a value.", "Unit: milliseconds.", "Deprecated soon; see `next`.",
        "  Indented doc line.", "Multi-word doc with punctuation: a, b; c!", "Value in [0, 1).",
        "Unicode: été → λ", "", "Note: \"quoted\" text and 'single' quotes.",
        "Second paragraph.", "Plain line", "Escapes \\n stay literal.", "<b>html</b> & entities"]
HASHES = {16: [], 32: ["fnv1_32", "fnv1a_32"], 64: ["fnv1_64", "fnv1a_64"]}


class Ctx:
    def __init__(self, rng, flags=None):
        self.r = rng
        self.used = set()
        self.flags = flags or {}

    def word(self):
        return self.r.choice(WORDS)

    def type_name(self):
        for _ in range(100):
            n = self.word().capitalize() + (self.word().capitalize() if self.r.random() < 0.6 else "")
            if self.r.random() < 0.1:
                n += str(self.r.randint(0, 99))
            if n not in self.used:
                self.used.add(n)
                return n
        n = "T%d" % len(self.used)
        self.used.add(n)
        return n

    def field_name(self, taken):
        for _ in range(100):
            r = self.r.random()
            if r < 0.04:
                n = self.r.choice(KEYWORDISH)
            elif r < 0.09:
                n = self.word().capitalize() + self.word().capitalize()  # warns: not snake_case
            elif r < 0.12:
                n = self.word() + str(self.r.randint(0, 9))
            elif r < 0.6:
                n = self.word()
            else:
                n = self.word() + "_" + self.word()
            if n not in taken:
                taken.add(n)
                return n
        n = "f%d" % len(taken)
        taken.add(n)
        return n


# ---------------------------------------------------------------- model

def mk_world(rng, size=None, features=None):
    """Return a world dict: files (list of file dicts), defs by qualified name, root table."""
    c = Ctx(rng)
    r = rng
    feat = features or {}
    size = size or r.choice([1, 2, 3, 4, 6, 8, 12])
    nfiles = 1 if r.random() < 0.55 else r.choice([2, 2, 3, 4])
    nspaces = [""] + [".".join(c.word() for _ in range(r.randint(1, 3))) for _ in range(3)]
    files = []
    for i in range(nfiles):
        name = ("schema" if i == 0 else r.choice(["inc", "common", "types", "lib", "base"]) + str(i)) + ".fbs"
        if i > 0 and r.random() < 0.3:
            name = r.choice(["sub/", "deps/", "lib/x/"]) + name
        files.append({"name": name, "items": [], "includes": [], "attrs": []})
    defs = []  # in declaration order (dependencies first)
    world = {"files": files, "defs": defs, "c": c, "feat": feat}

    def add(kind, d, fidx):
        d["kind"] = kind
        d["file"] = fidx
        if "ns" not in d:
            d["ns"] = r.choice(nspaces) if r.random() < 0.6 else (nspaces[1] if fidx else nspaces[0])
        d["q"] = (d["ns"] + "." if d["ns"] else "") + d["name"]
        defs.append(d)
        files[fidx]["items"].append(d)
        return d

    # later files are included by earlier ones: file 0 includes 1.., so definitions in higher index files are
    # visible to lower ones. Generate from the last file to the first.
    order = list(range(nfiles - 1, -1, -1))
    per_file = [max(1, size // nfiles + r.randint(-1, 1)) for _ in range(nfiles)]
    for fidx in order:
        for _ in range(per_file[fidx]):
            k = r.random()
            vis = [d for d in defs if d["file"] >= fidx]
            if k < 0.22:
                add("enum", gen_enum(c), fidx)
            elif k < 0.40:
                add("struct", gen_struct(c, vis), fidx)
            elif k < 0.50 and any(d["kind"] == "table" for d in vis):
                add("union", gen_union(c, vis), fidx)
            else:
                add("table", gen_table(c, vis, world), fidx)
        if fidx < nfiles - 1:
            files[fidx]["includes"].append(files[fidx + 1]["name"])
            if fidx + 2 < nfiles and r.random() < 0.4:
                files[fidx]["includes"].append(files[fidx + 2]["name"])
    tables = [d for d in defs if d["kind"] == "table" and d["file"] == 0]
    if not tables:
        t = add("table", gen_table(c, defs, world), 0)
        tables = [t]
    # self/forward references inside tables: allow tables to point to any table in the same or included files
    for d in defs:
        if d["kind"] == "table" and r.random() < 0.35:
            cands = [t for t in defs if t["kind"] == "table" and t["file"] >= d["file"]]
            if cands:
                tgt = r.choice(cands)
                f = gen_field_named(c, d)
                f["type"] = ("vector", ("table", tgt)) if r.random() < 0.5 else ("table", tgt)
                d["fields"].append(f)
    world["root"] = r.choice(tables)
    f0 = files[0]
    f0["root_type"] = world["root"] if r.random() < 0.9 else None
    if r.random() < 0.5:
        f0["file_identifier"] = "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(4))
    if r.random() < 0.25:
        f0["file_extension"] = r.choice(["bin", "dat", "mon", "x"])
    if r.random() < 0.25:
        add("service", gen_service(c, [d for d in defs if d["kind"] == "table"]), 0)
    # custom attributes
    for d in defs:
        for (a, _v) in d.get("attrs", []):
            if a.startswith("x_") and a not in f0["attrs"]:
                files[d["file"]]["attrs"].append(a)
        for f in d.get("fields", []):
            for (a, _v) in f.get("attrs", []):
                if a.startswith("x_") and a not in files[d["file"]]["attrs"]:
                    files[d["file"]]["attrs"].append(a)
        for v in d.get("values", []):
            for (a, _v) in v.get("attrs", []):
                if a.startswith("x_") and a not in files[d["file"]]["attrs"]:
                    files[d["file"]]["attrs"].append(a)
    if r.random() < 0.15:
        f0["native_include"] = r.choice(["native/types.h", "extra.h"])
    return world


def maybe_doc(c, p=0.3):
    if c.r.random() < p:
        return [c.r.choice(DOCS) for _ in range(c.r.choice([1, 1, 2, 3]))]
    return []


def custom_attr(c):
    a = "x_" + c.word()
    v = c.r.choice([None, None, '"' + c.word() + '"', str(c.r.randint(0, 99))])
    return (a, v)


def gen_enum(c):
    r = c.r
    flags = r.random() < 0.25
    ut = r.choice(UINTS if flags and r.random() < 0.9 else INTS)
    n = r.randint(1, 9)
    kind, size = SCALARS[ut]
    bits = size * 8
    vals = []
    taken = set()
    cur = None
    if flags:
        n = min(n, bits)
        bitpos = sorted(r.sample(range(min(bits, 64)), n))
        for b in bitpos:
            nm = c.type_name() if r.random() < 0.3 else c.word().capitalize()
            while nm in taken:
                nm = c.type_name()
            taken.add(nm)
            v = {"name": nm, "doc": maybe_doc(c, 0.15), "attrs": []}
            if r.random() < 0.6 or (vals and vals[-1]["v"] + 1 != b) or (not vals and b != 0):
                v["explicit"] = b
            v["v"] = b
            vals.append(v)
    else:
        lo = -(1 << (bits - 1)) if kind == "i" else 0
        hi = (1 << (bits - 1)) - 1 if kind == "i" else (1 << bits) - 1
        start = r.choice([0, 0, 0, 1, -1, 3, 100, lo]) if kind == "i" else r.choice([0, 0, 1, 5, 200])
        cur = max(lo, min(hi, start))
        for i in range(n):
            nm = r.choice([c.word().capitalize(), c.type_name(), c.word().upper()])
            while nm in taken:
                nm = c.type_name()
            taken.add(nm)
            v = {"name": nm, "doc": maybe_doc(c, 0.15), "attrs": []}
            if r.random() < 0.08:
                v["attrs"].append(custom_attr(c))
            if i == 0 or r.random() < 0.35:
                if i > 0:
                    step = r.choice([1, 1, 2, 5, 10, 100])
                    nxt = min(hi, cur + step)
                    if nxt <= cur:
                        break
                    cur = nxt
                v["explicit"] = cur
            else:
                if cur + 1 > hi:
                    break
                cur = cur + 1
            v["v"] = cur
            vals.append(v)
    attrs = []
    if flags:
        attrs.append(("bit_flags", None))
    if r.random() < 0.08:
        attrs.append(custom_attr(c))
    return {"name": c.type_name(), "ut": ut, "values": vals, "attrs": attrs, "doc": maybe_doc(c), "flags": flags}


def gen_union(c, vis):
    r = c.r
    tabs = [d for d in vis if d["kind"] == "table"]
    structs = [d for d in vis if d["kind"] == "struct"]
    mem = []
    taken = set()
    for t in r.sample(tabs, min(len(tabs), r.randint(1, 4))):
        alias = None
        if r.random() < 0.15:
            alias = c.type_name()
        if (alias or t["name"]) in taken:
            continue
        taken.add(alias or t["name"])
        mem.append({"t": t, "alias": alias, "doc": maybe_doc(c, 0.1)})
    if structs and r.random() < 0.12:
        s = r.choice(structs)
        if s["name"] not in taken:
            mem.append({"t": s, "alias": None, "doc": []})
    if r.random() < 0.06:
        mem.append({"t": "string", "alias": "Str" + c.word().capitalize(), "doc": []})
    u = {"name": c.type_name(), "members": mem, "attrs": [], "doc": maybe_doc(c)}
    if r.random() < 0.05:
        u["ut"] = r.choice(["ubyte", "ushort", "uint"])
    return u


def zero_ok(e):
    return e.get("flags") or 0 in [v["v"] for v in e["values"]]


def gen_struct(c, vis):
    r = c.r
    enums = [d for d in vis if d["kind"] == "enum" and zero_ok(d)]
    structs = [d for d in vis if d["kind"] == "struct"]
    taken = set()
    fields = []
    for _ in range(r.randint(1, 6)):
        f = {"name": c.field_name(taken), "doc": maybe_doc(c, 0.15), "attrs": []}
        k = r.random()
        if k < 0.6:
            f["type"] = ("scalar", r.choice(list(SCALARS)))
        elif k < 0.72 and enums:
            f["type"] = ("enum", r.choice(enums))
        elif k < 0.84 and structs:
            f["type"] = ("struct", r.choice(structs))
        else:
            et = r.random()
            if et < 0.6:
                el = ("scalar", r.choice(list(SCALARS)))
            elif et < 0.8 and enums:
                el = ("enum", r.choice(enums))
            elif structs:
                el = ("struct", r.choice(structs))
            else:
                el = ("scalar", "int")
            f["type"] = ("array", el, r.randint(1, 5))
        if r.random() < 0.05:
            f["attrs"].append(custom_attr(c))
        fields.append(f)
    attrs = []
    if r.random() < 0.15:
        attrs.append(("force_align", str(r.choice([8, 16, 16, 32] if r.random() < 0.9 else [1, 2, 3, 4]))))
    if r.random() < 0.05:
        attrs.append(custom_attr(c))
    return {"name": c.type_name(), "fields": fields, "attrs": attrs, "doc": maybe_doc(c)}


def gen_field_named(c, t):
    return {"name": c.field_name(t["taken"]), "doc": maybe_doc(c, 0.15), "attrs": []}


def gen_table(c, vis, world):
    r = c.r
    enums = [d for d in vis if d["kind"] == "enum"]
    structs = [d for d in vis if d["kind"] == "struct"]
    unions = [d for d in vis if d["kind"] == "union"]
    tables = [d for d in vis if d["kind"] == "table"]
    t = {"name": c.type_name(), "fields": [], "attrs": [], "doc": maybe_doc(c), "taken": set()}
    for _ in range(r.randint(0 if r.random() < 0.05 else 1, 10)):
        f = gen_field_named(c, t)
        k = r.random()
        if k < 0.38:
            st = r.choice(list(SCALARS))
            f["type"] = ("scalar", st)
            q = r.random()
            if q < 0.35:
                f["default"] = rand_scalar_literal(r, st, schema=True)
            elif q < 0.45:
                f["default"] = "null"
            if SCALARS[st][0] == "u" and SCALARS[st][1] >= 4 and r.random() < 0.05:
                f["attrs"].append(("hash", '"' + r.choice(HASHES[SCALARS[st][1] * 8]) + '"'))
                f.pop("default", None)
        elif k < 0.48 and enums:
            e = r.choice(enums)
            f["type"] = ("enum", e)
            q = r.random()
            zero = 0 in [v["v"] for v in e["values"]]
            if e["values"] and (q < 0.35 or (not zero and not 0.35 <= q < 0.4)):
                f["default"] = r.choice(e["values"])["name"] if r.random() < 0.8 else str(r.choice(e["values"])["v"])
            elif q < 0.4:
                f["default"] = "null"
        elif k < 0.58:
            f["type"] = ("string",)
            if r.random() < 0.05:
                f["default"] = json.dumps(c.word())
        elif k < 0.64 and structs:
            f["type"] = ("struct", r.choice(structs))
        elif k < 0.70 and unions:
            f["type"] = ("union", r.choice(unions))
        elif k < 0.75 and tables:
            f["type"] = ("table", r.choice(tables))
        else:
            et = r.random()
            if et < 0.4:
                el = ("scalar", r.choice(list(SCALARS)))
            elif et < 0.55:
                el = ("string",)
            elif et < 0.65 and [e for e in enums if zero_ok(e)]:
                el = ("enum", r.choice([e for e in enums if zero_ok(e)]))
            elif et < 0.8 and structs:
                el = ("struct", r.choice(structs))
            elif et < 0.92 and tables:
                el = ("table", r.choice(tables))
            elif unions and r.random() < 0.5:
                el = ("union", r.choice(unions))
            else:
                el = ("scalar", "ubyte")
            f["type"] = ("vector", el)
            if el == ("scalar", "ubyte") and r.random() < 0.3:
                if tables and r.random() < 0.6:
                    f["attrs"].append(("nested_flatbuffer", '"' + r.choice(tables)["q"] + '"'))
                    f["nested"] = None
                else:
                    f["attrs"].append(("flexbuffer", None))
            if r.random() < 0.04:
                f["default"] = "[]"
        # attributes
        ty = f["type"][0]
        if ty in ("string", "vector", "table", "struct") and r.random() < 0.1:
            f["attrs"].append(("required", None))
        if r.random() < 0.06:
            f["attrs"].append(("deprecated", None))
        if ty in ("string", "scalar") and f.get("default") != "null" and r.random() < 0.05 and "key" not in [a for a, _ in sum(
                [x["attrs"] for x in t["fields"]], [])]:
            f["attrs"].append(("key", None))
        if ty == "string" and r.random() < 0.04:
            f["attrs"].append(("shared", None))
        if ty == "vector" and f["type"][1][0] == "scalar" and r.random() < 0.015:
            f["attrs"].append(("vector64", None) if r.random() < 0.5 else ("offset64", None))
        if r.random() < 0.05:
            f["attrs"].append(custom_attr(c))
        t["fields"].append(f)
    if r.random() < 0.08:
        t["attrs"].append(("original_order", None))
    if r.random() < 0.05:
        t["attrs"].append(custom_attr(c))
    if r.random() < 0.06:
        t["attrs"].append(("csharp_partial", None))
    if r.random() < 0.2 and t["fields"]:
        t["ids"] = "shuffle" if r.random() < 0.6 else "inorder"
    t["q_hint"] = t["name"]
    return t


def gen_service(c, tables):
    r = c.r
    calls = []
    taken = set()
    for _ in range(r.randint(1, 4)):
        nm = c.word().capitalize() + c.word().capitalize()
        if nm in taken:
            continue
        taken.add(nm)
        call = {"name": nm, "req": r.choice(tables), "resp": r.choice(tables), "attrs": [], "doc": maybe_doc(c, 0.2)}
        if r.random() < 0.4:
            call["attrs"].append(("streaming", '"' + r.choice(["none", "server", "client", "bidi"]) + '"'))
        if r.random() < 0.1:
            call["attrs"].append(("idempotent", None))
        calls.append(call)
    return {"name": c.type_name(), "calls": calls, "attrs": [], "doc": maybe_doc(c)}


# ---------------------------------------------------------------- literals

def int_range(st):
    k, s = SCALARS[st]
    if k == "b":
        return 0, 1
    if k == "i":
        return -(1 << (8 * s - 1)), (1 << (8 * s - 1)) - 1
    return 0, (1 << (8 * s)) - 1


def rand_int(r, st):
    lo, hi = int_range(st)
    q = r.random()
    if q < 0.15:
        return r.choice([lo, hi, 0])
    if q < 0.5:
        return max(lo, min(hi, r.randint(-100, 100)))
    return r.randint(lo, hi)


def fmt_int(r, v, allow_hex=True):
    q = r.random()
    if allow_hex and q < 0.12:
        return ("-" if v < 0 else "") + "0x" + format(abs(v), r.choice(["x", "X"]))
    if q < 0.16 and v >= 0:
        return "+" + str(v)
    return str(v)


def rand_float(r, st):
    q = r.random()
    if q < 0.08:
        return r.choice(["inf", "-inf", "nan", "+inf", "infinity", "-nan"])
    if q < 0.2:
        return str(r.randint(-1000, 1000))
    if q < 0.3:
        return r.choice(["0.0", "-0.0", "1e10", "1.5e-7", "3.4028235e38", "1e-45", "2.2250738585072014e-308",
                         "0x1.8p1", "-0x10", "1.", ".5", "6.02214076e23", "123456789.123456789"])
    m = r.uniform(-1e4, 1e4)
    return repr(round(m, r.randint(0, 8))) if st in ("double", "float64") else "%g" % m


def rand_scalar_literal(r, st, schema=False):
    k = SCALARS[st][0]
    if k == "b":
        return r.choice(["true", "false", "0", "1"])
    if k == "f":
        return rand_float(r, st)
    return fmt_int(r, rand_int(r, st))


# ---------------------------------------------------------------- emit schema text

def q_ref(d, from_ns, r):
    """Reference d from namespace from_ns: unqualified when in the same namespace, else fully qualified (or a
    resolvable suffix when the reference namespace is a prefix)."""
    if d["ns"] == from_ns:
        return d["name"] if r.random() < 0.9 else d["q"]
    return d["q"]


def type_text(ty, ns, r):
    k = ty[0]
    if k == "scalar":
        return ty[1]
    if k == "string":
        return "string"
    if k in ("enum", "struct", "table", "union"):
        return q_ref(ty[1], ns, r)
    if k == "vector":
        return "[" + type_text(ty[1], ns, r) + "]"
    if k == "array":
        return "[" + type_text(ty[1], ns, r) + ":" + str(ty[2]) + "]"
    raise ValueError(k)


def attrs_text(attrs, r):
    if not attrs:
        return ""
    parts = []
    for a, v in attrs:
        parts.append(a if v is None else a + r.choice([": ", ":", " : "]) + v)
    return " (" + r.choice([", ", ","]).join(parts) + ")"


def doc_text(doc, ind):
    return "".join(ind + "///" + (" " if d and not d.startswith(" ") else "") + d + "\n" for d in doc)


def emit_file(world, fidx, r, style=None):
    f = world["files"][fidx]
    st = style or {}
    ind = st.get("ind", r.choice(["  ", "    ", "\t", " "]))
    out = []
    if r.random() < 0.3:
        out.append(r.choice(["// Generated test schema.\n", "/* block\n   comment */\n", "// © example\n"]))
    for inc in f["includes"]:
        rel = inc
        out.append('include "%s";\n' % rel)
    if f.get("native_include"):
        out.append('native_include "%s";\n' % f["native_include"])
    for a in f["attrs"]:
        out.append(('attribute "%s";\n' if r.random() < 0.7 else "attribute %s;\n") % a)
    if out and r.random() < 0.7:
        out.append("\n")
    cur_ns = None
    for d in f["items"]:
        if d["ns"] != cur_ns:
            if d["ns"] or cur_ns is not None:
                out.append("namespace %s;\n\n" % d["ns"] if d["ns"] else "namespace ;\n\n")
            cur_ns = d["ns"]
        out.append(emit_def(d, cur_ns or "", r, ind))
        out.append("\n" if r.random() < 0.8 else "")
    ns0 = cur_ns or ""
    if fidx == 0:
        rt = f.get("root_type")
        if rt is not None:
            out.append("root_type %s;\n" % q_ref(rt, ns0, r))
        if f.get("file_identifier"):
            out.append('file_identifier "%s";\n' % f["file_identifier"])
        if f.get("file_extension"):
            out.append('file_extension "%s";\n' % f["file_extension"])
    return "".join(out)


def emit_def(d, ns, r, ind):
    k = d["kind"]
    s = doc_text(d.get("doc", []), "")
    if k == "enum":
        s += "enum %s : %s%s {" % (d["name"], d["ut"], attrs_text(d["attrs"], r))
        vals = d["values"]
        nl = r.random() < 0.7
        for i, v in enumerate(vals):
            s += ("\n" + doc_text(v["doc"], ind) + ind) if nl else (" " if i == 0 else " ")
            s += v["name"]
            if "explicit" in v:
                s += " = " + fmt_int(r, v["explicit"])
            s += attrs_text(v["attrs"], r)
            if i < len(vals) - 1 or r.random() < 0.2:
                s += ","
        s += ("\n}\n" if nl else " }\n")
        return s
    if k == "union":
        s += "union %s%s%s {" % (d["name"], (" : " + d["ut"]) if d.get("ut") else "", attrs_text(d["attrs"], r))
        for i, m in enumerate(d["members"]):
            s += "\n" + doc_text(m["doc"], ind) + ind
            tn = "string" if m["t"] == "string" else q_ref(m["t"], ns, r)
            s += (m["alias"] + ": " + tn) if m["alias"] else tn
            if i < len(d["members"]) - 1 or r.random() < 0.2:
                s += ","
        return s + "\n}\n"
    if k in ("struct", "table"):
        fields = d["fields"]
        ids = None
        if d.get("ids"):
            # a union field takes two ids (its type and its value); id names the value slot
            width = [2 if f["type"][0] == "union" or (f["type"][0] == "vector" and f["type"][1][0] == "union")
                     else 1 for f in fields]
            order = list(range(len(fields)))
            if d["ids"] == "shuffle":
                r.shuffle(order)
            ids, nxt = [0] * len(fields), 0
            for i in order:
                nxt += width[i]
                ids[i] = nxt - 1
            if r.random() < 0.05:
                ids[r.randrange(len(ids))] += 1  # a gap: rejected
        s += "%s %s%s {\n" % (k, d["name"], attrs_text(d["attrs"], r))
        for i, f in enumerate(fields):
            s += doc_text(f["doc"], ind)
            s += ind + f["name"] + r.choice([":", ": ", " : "]) + type_text(f["type"], ns, r)
            if "default" in f:
                s += r.choice([" = ", "=", " ="]) + f["default"]
            attrs = list(f["attrs"])
            if ids is not None:
                # a union field takes two ids (type and value): id names the value slot
                attrs.append(("id", str(ids[i])))
            s += attrs_text(attrs, r) + ";\n"
        return s + "}\n"
    if k == "service":
        s += "rpc_service %s%s {\n" % (d["name"], attrs_text(d["attrs"], r))
        for c in d["calls"]:
            s += doc_text(c["doc"], ind)
            s += ind + "%s(%s):%s%s;\n" % (c["name"], q_ref(c["req"], ns, r), q_ref(c["resp"], ns, r),
                                          attrs_text(c["attrs"], r))
        return s + "}\n"
    raise ValueError(k)


def fix_union_ids(world):
    """Tables with explicit ids: a union field occupies two ids, so renumber to keep them valid."""
    for d in world["defs"]:
        if d["kind"] == "table" and d.get("ids"):
            d["ids"] = d["ids"]  # emitted ids may be invalid for unions; the reference decides


def emit_world(world, r):
    return {f["name"]: emit_file(world, i, r) for i, f in enumerate(world["files"])}


# ---------------------------------------------------------------- JSON documents

def json_string(r):
    q = r.random()
    if q < 0.3:
        return r.choice(WORDS)
    pool = ["a", "Z", " ", "\n", "\t", "\"", "\\", "/", "é", "€", "\U0001F600", "\u0001", "\u007f",
            "x", "0", "中", "\r", "\b", "\f"]
    return "".join(r.choice(pool) for _ in range(r.randint(0, 12)))


class Obj(list):
    """A JSON object as an ordered list of (key, value) pairs."""


class Raw:
    """A JSON fragment emitted verbatim (hex numbers, unquoted names, special floats)."""

    def __init__(self, s):
        self.s = s


def json_scalar(r, st, strict):
    k = SCALARS[st][0]
    if k == "b":
        q = r.random()
        if q < 0.7:
            return r.choice([True, False])
        return Raw(r.choice(["1", "0"])) if strict else Raw(r.choice(["1", "0", '"true"', '"false"']))
    if k == "f":
        q = r.random()
        if q < 0.1 and not strict:
            return Raw(r.choice(["inf", "-inf", "nan", "+inf", '"nan"', '"-inf"']))
        if q < 0.2:
            return Raw(str(r.randint(-1000, 1000)))
        if q < 0.3:
            return Raw(r.choice(["0.0", "-0.0", "1e10", "1.5e-7", "3.4028235e38", "1e-45", "6.02214076e23",
                                 "0.1", "123456789.123456789", "1E5", "-2.5E-3"]))
        return Raw(repr(round(r.uniform(-1e5, 1e5), r.randint(0, 9))))
    v = rand_int(r, st)
    if not strict and r.random() < 0.08:
        return Raw(fmt_int(r, v))
    if r.random() < 0.05:
        return Raw('"%d"' % v)
    return Raw(str(v))


def json_value(r, ty, depth, strict, world):
    k = ty[0]
    if k == "scalar":
        return json_scalar(r, ty[1], strict)
    if k == "string":
        return json_string(r)
    if k == "enum":
        e = ty[1]
        if not e["values"]:
            return Raw("0")
        q = r.random()
        if e.get("flags") and q < 0.3:
            names = r.sample([v["name"] for v in e["values"]], r.randint(1, min(3, len(e["values"]))))
            return " ".join(names)
        if q < 0.75:
            return r.choice(e["values"])["name"]
        if q < 0.8:
            return e["name"] + "." + r.choice(e["values"])["name"]
        return Raw(str(r.choice(e["values"])["v"]))
    if k == "struct":
        return Obj((f["name"], json_value(r, f["type"], depth + 1, strict, world)) for f in ty[1]["fields"])
    if k == "array":
        return [json_value(r, ty[1], depth + 1, strict, world) for _ in range(ty[2])]
    if k == "table":
        return json_table(r, ty[1], depth + 1, strict, world)
    if k == "vector":
        n = r.choice([0, 1, 2, 3, 5]) if depth < 3 else r.choice([0, 1])
        el = ty[1]
        if el[0] == "union":
            return None  # handled by the table
        return [json_value(r, el, depth + 1, strict, world) for _ in range(n)]
    return None


def json_table(r, t, depth, strict, world):
    out = []
    if depth > 4:
        return Obj()
    for f in t["fields"]:
        ty = f["type"]
        attrs = dict(f["attrs"])
        req = "required" in attrs
        if not req and r.random() < (0.25 if depth == 0 else 0.45):
            continue
        if "deprecated" in attrs and r.random() < 0.95:
            continue
        nm = f["name"]
        if ty[0] == "union":
            u = ty[1]
            if not u["members"]:
                continue
            m = r.choice(u["members"])
            mname = m["alias"] or (m["t"]["name"] if m["t"] != "string" else "string")
            if m["t"] == "string":
                val = json_string(r)
            elif m["t"]["kind"] == "struct":
                val = json_value(r, ("struct", m["t"]), depth + 1, strict, world)
            else:
                val = json_table(r, m["t"], depth + 1, strict, world)
            tv = mname if r.random() < 0.9 else Raw(str(u["members"].index(m) + 1))
            if r.random() < 0.95:
                out.append((nm + "_type", tv))
                out.append((nm, val))
            else:
                out.append((nm, val))
                out.append((nm + "_type", tv))
            continue
        if ty[0] == "vector" and ty[1][0] == "union":
            u = ty[1][1]
            if not u["members"]:
                continue
            n = r.randint(0, 3)
            types, vals = [], []
            for _ in range(n):
                m = r.choice(u["members"])
                mname = m["alias"] or (m["t"]["name"] if m["t"] != "string" else "string")
                types.append(mname)
                if m["t"] == "string":
                    vals.append(json_string(r))
                elif m["t"]["kind"] == "struct":
                    vals.append(json_value(r, ("struct", m["t"]), depth + 1, strict, world))
                else:
                    vals.append(json_table(r, m["t"], depth + 1, strict, world))
            out.append((nm + "_type", types))
            out.append((nm, vals))
            continue
        if "nested_flatbuffer" in attrs:
            tname = attrs["nested_flatbuffer"].strip('"')
            tgt = [d for d in world["defs"] if d["kind"] == "table" and d["q"] == tname]
            if tgt and r.random() < 0.8:
                out.append((nm, json_table(r, tgt[0], depth + 1, strict, world)))
            else:
                out.append((nm, [Raw(str(r.randint(0, 255))) for _ in range(r.randint(0, 4))]))
            continue
        if "flexbuffer" in attrs:
            out.append((nm, rand_any_json(r, 0)))
            continue
        if f.get("default") == "null" and r.random() < 0.2:
            out.append((nm, Raw("null")))
            continue
        out.append((nm, json_value(r, ty, depth, strict, world)))
    if r.random() < 0.3:
        r.shuffle(out)
    return Obj(out)


def rand_any_json(r, depth):
    q = r.random()
    if depth > 2 or q < 0.4:
        return r.choice([Raw(str(r.randint(-5000, 5000))), Raw(repr(r.uniform(-10, 10))), True, False,
                         Raw("null"), json_string(r), Raw(str(r.randint(0, 1 << 40)))])
    if q < 0.7:
        return [rand_any_json(r, depth + 1) for _ in range(r.randint(0, 4))]
    return Obj((r.choice(WORDS) + str(i), rand_any_json(r, depth + 1)) for i in range(r.randint(0, 4)))


def dump_json(v, r, strict, ind="  ", lvl=0, compact=False):
    """Serialize generator values: dict / list of pairs -> object, list -> array, Raw -> verbatim."""
    nl = "" if compact else "\n"
    pad = "" if compact else ind * (lvl + 1)
    end = "" if compact else ind * lvl
    if isinstance(v, Raw):
        return v.s
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, str):
        s = json.dumps(v, ensure_ascii=r.random() < 0.5)
        return s
    if isinstance(v, dict):
        v = Obj(v.items())
    if isinstance(v, Obj):
        if not v:
            return "{}"
        parts = []
        for k, x in v:
            key = json.dumps(k) if (strict or r.random() < 0.7) else k
            parts.append(pad + key + ": " + dump_json(x, r, strict, ind, lvl + 1, compact))
        trail = "," if (not strict and r.random() < 0.1) else ""
        return "{" + nl + ("," + nl).join(parts) + trail + nl + end + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        parts = [dump_json(x, r, strict, ind, lvl + 1, True) for x in v]
        return "[" + ", ".join(parts) + "]"
    if isinstance(v, (int, float)):
        return repr(v)
    raise TypeError(type(v))


def gen_json(world, r, strict=False, table=None):
    t = table or world["root"]
    doc = json_table(r, t, 0, strict, world)
    s = dump_json(doc, r, strict, compact=r.random() < 0.15)
    if r.random() < 0.1 and not strict:
        s = "// data\n" + s
    return s + ("\n" if r.random() < 0.8 else "")
