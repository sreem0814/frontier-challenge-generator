"""Random .proto files (proto2 and proto3) for the flatc --proto converter."""
import random

from schemagen import WORDS, DOCS

PSCALARS = ["int32", "int64", "uint32", "uint64", "sint32", "sint64", "fixed32", "fixed64", "sfixed32",
            "sfixed64", "bool", "string", "bytes", "float", "double"]


def ident(r, cap=False):
    w = r.choice(WORDS)
    if r.random() < 0.4:
        w += "_" + r.choice(WORDS)
    if cap:
        w = "".join(p.capitalize() for p in w.split("_"))
    return w


def comment(r, ind):
    q = r.random()
    if q < 0.2:
        return "".join(ind + "// " + r.choice(DOCS) + "\n" for _ in range(r.randint(1, 2)))
    if q < 0.25:
        return ind + "/* " + r.choice(DOCS) + " */\n"
    if q < 0.28:
        return ind + "/// " + r.choice(DOCS) + "\n"
    return ""


def gen_enum(r, ind, names, syntax):
    name = ident(r, True)
    while name in names:
        name += "X"
    names.add(name)
    s = comment(r, ind) + ind + "enum %s {\n" % name
    vals = set()
    n = r.randint(1, 6)
    cur = 0 if syntax == 3 or r.random() < 0.7 else r.randint(-3, 5)
    if r.random() < 0.15:
        s += ind + "  option allow_alias = true;\n"
    for i in range(n):
        vn = (name.upper() + "_" if r.random() < 0.5 else "") + ident(r).upper()
        if vn in vals:
            continue
        vals.add(vn)
        s += comment(r, ind + "  ") + ind + "  %s = %d" % (vn, cur)
        if r.random() < 0.08:
            s += " [deprecated = true]"
        s += ";\n"
        cur += r.choice([1, 1, 1, 2, 10]) if r.random() < 0.95 else -1
    if r.random() < 0.08:
        s += ind + "  reserved %d;\n" % (cur + 5)
    return name, s + ind + "}\n"


def gen_message(r, ind, names, types, syntax, depth=0):
    name = ident(r, True)
    while name in names:
        name += "Msg"
    names.add(name)
    inner_names = set()
    body = ""
    local_types = list(types)
    if depth < 2 and r.random() < 0.3:
        en, es = gen_enum(r, ind + "  ", inner_names, syntax)
        body += es
        local_types.append((name + "." + en, "enum"))
    if depth < 2 and r.random() < 0.25:
        mn, ms = gen_message(r, ind + "  ", inner_names, local_types, syntax, depth + 1)
        body += ms
        local_types.append((name + "." + mn, "msg"))
    fid = 1
    taken = set()
    for _ in range(r.randint(0, 8)):
        fn = ident(r)
        if fn in taken:
            continue
        taken.add(fn)
        q = r.random()
        if q < 0.55 or not local_types:
            ty = r.choice(PSCALARS)
        else:
            ty = r.choice(local_types)[0]
        label = ""
        if syntax == 2:
            label = r.choice(["optional ", "optional ", "required ", "repeated "])
        else:
            label = r.choice(["", "", "repeated ", "optional "])
        opts = []
        if r.random() < 0.15 and ty in PSCALARS and label.strip() != "repeated" and ty not in ("bytes",):
            if ty == "string":
                opts.append('default = "%s"' % r.choice(WORDS))
            elif ty == "bool":
                opts.append("default = %s" % r.choice(["true", "false"]))
            elif ty in ("float", "double"):
                opts.append("default = %s" % r.choice(["1.5", "-2", "1e3", "0.25"]))
            else:
                opts.append("default = %d" % r.randint(0, 100))
        if r.random() < 0.08:
            opts.append("deprecated = true")
        if label.strip() == "repeated" and r.random() < 0.1:
            opts.append("packed = true")
        if r.random() < 0.03:
            fid += 1  # a gap
        body += comment(r, ind + "  ")
        body += ind + "  %s%s %s = %d%s;\n" % (label, ty, fn, fid,
                                             (" [" + ", ".join(opts) + "]") if opts else "")
        fid += 1
    if r.random() < 0.25:
        on = ident(r)
        body += ind + "  oneof %s {\n" % on
        for _ in range(r.randint(1, 3)):
            fn = ident(r)
            if fn in taken:
                continue
            taken.add(fn)
            ty = r.choice(PSCALARS + [t[0] for t in local_types])
            body += ind + "    %s %s = %d;\n" % (ty, fn, fid)
            fid += 1
        body += ind + "  }\n"
    if r.random() < 0.12:
        kt = r.choice(["string", "int32", "uint64", "bool"])
        vt = r.choice(PSCALARS + [t[0] for t in local_types])
        fn = ident(r) + "_map"
        if fn not in taken:
            body += ind + "  map<%s, %s> %s = %d;\n" % (kt, vt, fn, fid)
            fid += 1
    if r.random() < 0.1:
        body += ind + "  reserved %d, %d to %d;\n" % (fid + 1, fid + 3, fid + 5)
    if syntax == 2 and r.random() < 0.08:
        body += ind + "  extensions 100 to 199;\n"
    if r.random() < 0.05:
        body += ind + "  option deprecated = true;\n"
    return name, comment(r, ind) + ind + "message %s {\n" % name + body + ind + "}\n"


def gen_proto(r, imports=()):
    syntax = r.choice([2, 3])
    s = ""
    if r.random() < 0.3:
        s += "// test proto\n"
    if r.random() < 0.95:
        s += 'syntax = "proto%d";\n\n' % syntax
    if r.random() < 0.8:
        s += "package %s;\n\n" % ".".join(r.choice(WORDS) for _ in range(r.randint(1, 3)))
    for imp in imports:
        s += 'import "%s";\n' % imp
    if r.random() < 0.3:
        s += 'option java_package = "com.example.%s";\n' % r.choice(WORDS)
    if r.random() < 0.15:
        s += "option optimize_for = SPEED;\n"
    names = set()
    types = []
    for _ in range(r.randint(1, 5)):
        if r.random() < 0.3:
            n, t = gen_enum(r, "", names, syntax)
            types.append((n, "enum"))
        else:
            n, t = gen_message(r, "", names, types, syntax)
            types.append((n, "msg"))
        s += "\n" + t
    msgs = [t for t, k in types if k == "msg"]
    if msgs and r.random() < 0.12:
        s += "\nservice %s {\n" % ident(r, True)
        for _ in range(r.randint(1, 3)):
            s += "  rpc %s (%s) returns (%s);\n" % (ident(r, True), r.choice(msgs), r.choice(msgs))
        s += "}\n"
    if msgs and syntax == 2 and r.random() < 0.06:
        s += "\nextend %s {\n  optional int32 ext_%s = 150;\n}\n" % (r.choice(msgs), r.choice(WORDS))
    return s, [t for t, _ in types]


def proto_mutate(r, text):
    """Small damage to a proto file for the error cases."""
    lines = text.split("\n")
    q = r.random()
    idx = [i for i, l in enumerate(lines) if "=" in l and l.strip().endswith(";") and "syntax" not in l]
    if q < 0.25 and idx:
        i = r.choice(idx)
        lines[i] = lines[i].rstrip(";")
    elif q < 0.45 and idx:
        i = r.choice(idx)
        lines[i] = lines[i].replace(lines[i].split()[0], "undefined_type_" + r.choice(WORDS), 1)
    elif q < 0.6 and len(idx) > 1:
        i, j = r.sample(idx, 2)
        a = lines[i].rsplit("=", 1)
        b = lines[j].rsplit("=", 1)
        lines[j] = b[0] + "=" + a[1]  # duplicate id
    elif q < 0.75:
        lines.insert(r.randrange(len(lines)), r.choice(["}", "message {", "oneof", "= 3;", "option;",
                                                         "enum E { }", "group Foo = 1 {}"]))
    elif q < 0.9 and idx:
        i = r.choice(idx)
        lines[i] = lines[i].replace("= ", "= -", 1)
    else:
        return text.replace("{", "", 1)
    return "\n".join(lines)
