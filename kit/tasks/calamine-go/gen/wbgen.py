"""wbgen.py: generate random but realistic workbooks with several real writers.

Runs inside the throwaway generator container (gen/Dockerfile.gen). One random "spec" per seed
describes sheets, typed cells, number formats, formulas (as an AST), merged ranges and defined
names; each writer renders the spec in its own format:

  <id>-xw.xlsx    XlsxWriter
  <id>-op.xlsx    openpyxl
  <id>-raw.xlsx   hand-written SpreadsheetML (inline strings, rich text, shared formulas, ...)
  <id>-xlwt.xls   xlwt (BIFF8)
  <id>-b12.xlsb   hand-written BIFF12 package
  <id>-raw.ods    hand-written OpenDocument content.xml
  LibreOffice conversions of <id>-xw.xlsx are made by lo_convert.sh: -lo.xlsx -lo8.xls -lo5.xls -lo.ods

usage: python3 wbgen.py --out DIR --first N --count K [--big]
"""
import argparse
import datetime as dt
import io
import math
import os
import random
import struct
import zipfile
from xml.sax.saxutils import escape as xesc

# ---------------------------------------------------------------- spec

WORDS = ("alpha beta gamma delta north south east west total region q1 q2 q3 q4 revenue cost "
         "margin units price item code name date status open closed pending widget gadget "
         "sprocket bolt nut washer london paris tokyo berlin oslo lima cairo quito").split()
UNICODE_WORDS = ["café", "naïve", "Ærø", "Łódź", "Straße", "ελληνικά", "русский", "日本語", "中文字",
                 "한국어", "עברית", "عربى", "emoji😀", "ﬁle", "Ω≈ç√", "tab\there", "line\nbreak",
                 "  padded  ", "quote\"s", "amp&lt<gt>", "x000D_lit _x000D_", "back\\slash"]
SHEET_NAMES = ["Data", "Summary", "Sheet1", "Report 2024", "Q1", "Raw data", "Lookups", "Notes",
               "Été", "Δεδομένα", "数据", "O'Brien", "Plan-B", "Totals", "Inputs", "Calc"]

DATE_FORMATS = ["yyyy-mm-dd", "dd/mm/yyyy", "mmm d, yyyy", "d-mmm-yy", "yyyy-mm-dd hh:mm:ss",
                "hh:mm", "h:mm:ss AM/PM", "[h]:mm:ss", "mm:ss.0", "dddd, mmmm dd", "m/d/yy h:mm",
                "[$-409]mmmm d, yyyy", "yy\\-mm", "[mm]:ss"]
NUM_FORMATS = ["0.00", "#,##0", "0%", "0.0%", "#,##0.00 \"EUR\"", "$#,##0.00", "0.00E+00",
               "# ?/?", "@", "\"Day \"0", "0_);[Red](0)", "#,##0;-#,##0;\"zero\""]
BUILTIN_DATE_IDS = [14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47]

# function name -> (FTAB index, fixed arity or None for variable)
FUNCS = {
    "SUM": (4, None), "AVERAGE": (5, None), "MIN": (6, None), "MAX": (7, None), "COUNT": (0, None),
    "IF": (1, None), "ABS": (24, 1), "ROUND": (27, 2), "SQRT": (20, 1), "LEN": (32, 1),
    "UPPER": (113, 1), "LOWER": (112, 1), "NOT": (38, 1), "AND": (36, None), "OR": (37, None),
    "PI": (19, 0), "INT": (25, 1), "MOD": (39, 2), "LEFT": (115, None), "RIGHT": (116, None),
    "MID": (31, 3), "TRIM": (118, 1), "POWER": (337, 2), "CONCATENATE": (336, None),
    "ISBLANK": (129, 1), "NA": (10, 0), "TODAY": (221, 0), "YEAR": (69, 1), "DATE": (65, 3),
    "PRODUCT": (183, None), "COUNTA": (169, None), "LN": (22, 1), "EXP": (21, 1),
}


class N:  # formula AST node
    def __init__(self, kind, *args):
        self.kind = kind
        self.args = args


class Spec:
    pass


def rand_word(r):
    if r.random() < 0.12:
        return r.choice(UNICODE_WORDS)
    w = r.choice(WORDS)
    if r.random() < 0.3:
        w = w.capitalize()
    if r.random() < 0.2:
        w += " " + r.choice(WORDS)
    return w


def rand_string(r):
    p = r.random()
    if p < 0.02:
        return ""
    if p < 0.05:
        n = r.choice([300, 1200, 9000])
        base = rand_word(r) + " "
        return (base * (n // len(base) + 1))[:n]
    if p < 0.10:
        return str(r.randint(0, 99999)).zfill(r.choice([5, 8]))  # numeric-looking text
    return rand_word(r)


def rand_float(r):
    p = r.random()
    if p < 0.3:
        return round(r.uniform(-1000, 1000), r.choice([1, 2, 3]))
    if p < 0.5:
        return r.choice([0.1, 0.5, 1.5, -2.25, 3.14159, 1e-7, 1e15, 123456789.125, -0.0001, 2.5e-300])
    if p < 0.7:
        return float(r.randint(-100000, 100000))
    return r.uniform(-1e6, 1e6)


def rand_date_serial(r, is1904):
    d = dt.date(r.randint(1901, 2090), r.randint(1, 12), r.randint(1, 28))
    base = dt.date(1904, 1, 1) if is1904 else dt.date(1899, 12, 30)
    v = float((d - base).days)
    if r.random() < 0.5:
        v += r.choice([0.25, 0.5, 0.75, r.random()])
        v = round(v, 9)
    return v


def make_spec(seed, big=False):
    r = random.Random(seed)
    s = Spec()
    s.seed = seed
    s.is1904 = r.random() < 0.12
    nsheets = r.choice([1, 1, 2, 2, 3, 4])
    names = r.sample(SHEET_NAMES, nsheets)
    s.sheets = []
    for si, name in enumerate(names):
        sh = Spec()
        sh.name = name
        sh.state = "visible"
        if si > 0 and r.random() < 0.2:
            sh.state = r.choice(["hidden", "hidden", "veryHidden"])
        sh.cells = {}  # (row, col) -> dict(t=..., v=..., fmt=..., f=AST or None)
        sh.merges = []
        if r.random() < 0.15:
            s.sheets.append(sh)  # an empty sheet
            continue
        r0 = r.choice([0, 0, 0, 1, 2, 5, 17])
        c0 = r.choice([0, 0, 0, 1, 3, 26])
        nrows = r.choice([1, 3, 8, 15, 40]) if not big else r.choice([800, 2500])
        ncols = r.choice([1, 2, 4, 6, 9]) if not big else r.choice([6, 10])
        coltypes = [r.choice(["str", "int", "float", "date", "bool", "mixed", "num_fmt"]) for _ in range(ncols)]
        datefmts = [r.choice(DATE_FORMATS + [None, None]) for _ in range(ncols)]
        numfmts = [r.choice(NUM_FORMATS) for _ in range(ncols)]
        header = r.random() < 0.8
        if header:
            for c in range(ncols):
                sh.cells[(r0, c0 + c)] = dict(t="s", v=rand_word(r) if r.random() < 0.9 else "Col %d" % c)
        start = r0 + (1 if header else 0)
        density = r.choice([1.0, 1.0, 0.9, 0.6])
        for i in range(nrows):
            for c in range(ncols):
                if r.random() > density:
                    continue
                pos = (start + i, c0 + c)
                t = coltypes[c]
                if t == "mixed":
                    t = r.choice(["str", "int", "float", "bool", "date"])
                if t == "str":
                    sh.cells[pos] = dict(t="s", v=rand_string(r))
                elif t == "int":
                    sh.cells[pos] = dict(t="n", v=float(r.randint(-5000, 100000)))
                elif t == "float":
                    sh.cells[pos] = dict(t="n", v=rand_float(r))
                elif t == "num_fmt":
                    sh.cells[pos] = dict(t="n", v=rand_float(r), fmt=numfmts[c])
                elif t == "bool":
                    sh.cells[pos] = dict(t="b", v=r.random() < 0.5)
                elif t == "date":
                    fmt = datefmts[c] or ("builtin:%d" % r.choice(BUILTIN_DATE_IDS))
                    sh.cells[pos] = dict(t="d", v=rand_date_serial(r, s.is1904), fmt=fmt)
        # formulas: totals row and per-row calculations
        numcols = [c for c in range(ncols) if coltypes[c] in ("int", "float", "num_fmt")]
        last = start + nrows - 1
        sh.block = dict(r0=r0, c0=c0, header=header, start=start, last=last, ncols=ncols, numcols=numcols)
        if numcols and nrows > 1 and r.random() < 0.8:
            trow = last + 1 + r.choice([0, 1])
            for c in numcols:
                fn = r.choice(["SUM", "SUM", "AVERAGE", "MIN", "MAX", "COUNT", "PRODUCT"])
                area = N("area", None, start, c0 + c, last, c0 + c, r.random() < 0.3)
                sh.cells[(trow, c0 + c)] = dict(t="f", f=N("func", fn, [area]))
        if len(numcols) >= 2 and r.random() < 0.7:
            fc = c0 + ncols + r.choice([0, 1])
            a, b = r.sample(numcols, 2)
            tmpl = r.choice(["mul", "add_abs", "if", "round", "pct", "pow", "neg", "concat", "cmp", "div"])
            for i in range(min(nrows, 60)):
                row = start + i
                ra = N("ref", None, row, c0 + a, False, False)
                rb = N("ref", None, row, c0 + b, False, False)
                if tmpl == "mul":
                    f = N("bin", "*", ra, rb)
                elif tmpl == "add_abs":
                    f = N("bin", "+", ra, N("ref", None, start, c0 + b, True, True))
                elif tmpl == "if":
                    f = N("func", "IF", [N("bin", ">", ra, rb), N("str", "high"), N("str", "low")])
                elif tmpl == "round":
                    f = N("func", "ROUND", [N("bin", "/", ra, N("num", 3.0)), N("int", 2)])
                elif tmpl == "pct":
                    f = N("pct", N("paren", N("bin", "-", ra, rb)))
                elif tmpl == "pow":
                    f = N("bin", "^", N("func", "ABS", [ra]), N("num", 0.5))
                elif tmpl == "neg":
                    f = N("neg", N("paren", N("bin", "+", ra, N("int", 1))))
                elif tmpl == "concat":
                    f = N("bin", "&", N("str", "v="), ra)
                elif tmpl == "cmp":
                    f = N("func", "AND", [N("bin", ">=", ra, N("int", 0)), N("bin", "<>", rb, N("int", 7))])
                else:
                    f = N("bin", "/", ra, rb)
                sh.cells[(row, fc)] = dict(t="f", f=f)
        if r.random() < 0.4:
            row = last + 3
            sh.cells[(row, c0)] = dict(t="f", f=N("bin", "/", N("int", 1), N("int", 0)))
            sh.cells[(row, c0 + 1)] = dict(t="f", f=N("func", "NA", []))
            sh.cells[(row, c0 + 2)] = dict(t="f", f=N("func", "SQRT", [N("num", -4.0)]))
            sh.cells[(row, c0 + 3)] = dict(t="f", f=N("func", "LEN", [N("str", "héllo wörld")]))
            sh.cells[(row, c0 + 4)] = dict(t="f", f=N("bool", r.random() < 0.5))
            sh.cells[(row, c0 + 5)] = dict(t="f", f=N("func", "PI", []))
        if header and ncols >= 2 and r.random() < 0.5:
            # merged title above the table, or a merged block inside
            if r0 >= 1:
                sh.cells[(r0 - 1, c0)] = dict(t="s", v="Title: " + rand_word(r))
                sh.merges.append((r0 - 1, c0, r0 - 1, c0 + ncols - 1))
            else:
                sh.merges.append((start, c0, start + 1, c0))
        s.sheets.append(sh)
    # cross-sheet formulas
    if nsheets > 1 and r.random() < 0.7:
        src = s.sheets[1]
        dst = s.sheets[0]
        if src.cells:
            (sr, sc) = r.choice(sorted(src.cells))
            row = max([k[0] for k in dst.cells] + [0]) + 2
            dst.cells[(row, 0)] = dict(t="f", f=N("ref", src.name, sr, sc, r.random() < 0.5, r.random() < 0.5))
            dst.cells[(row, 1)] = dict(t="f", f=N("func", "SUM", [N("area", src.name, sr, sc, sr + 3, sc + 1, False)]))
    # defined names
    s.names = []
    if r.random() < 0.5:
        sh = s.sheets[0]
        if sh.cells:
            ks = sorted(sh.cells)
            (a, b) = ks[0]
            (c, d) = ks[-1]
            s.names.append(("DataRange", sh.name, (a, b, max(a, c), max(b, d))))
        if r.random() < 0.5:
            s.names.append(("TaxRate", None, 0.2))
    add_extras(s, random.Random(seed * 131 + 17))
    return s


def add_extras(s, r):
    """Pictures, VBA, tables, pivot caches, hyperlinks and properties (own random stream)."""
    import extras
    s.vba = r.random() < 0.35
    s.vba_seed = r.randint(0, 1 << 30)
    s.images = []
    if r.random() < 0.5:
        for k in range(r.choice([1, 1, 2, 3])):
            si = r.randrange(len(s.sheets))
            ext, data = extras.random_image(r)
            s.images.append(dict(sheet=si, row=r.randint(0, 30), col=r.randint(0, 8), ext=ext, data=data,
                                 name="Picture %d" % (k + 1)))
    s.props = extras.random_properties(r) if r.random() < 0.8 else {}
    s.links = []
    for si, sh in enumerate(s.sheets):
        sh.table = None
        sh.pivot = None
        b = getattr(sh, "block", None)
        if b and b["header"] and b["ncols"] >= 2 and b["last"] > b["start"] and r.random() < 0.45:
            names = []
            for c in range(b["ncols"]):
                cell = sh.cells.get((b["r0"], b["c0"] + c))
                n = cell["v"] if cell and cell["t"] == "s" and cell["v"].strip() else "Column%d" % (c + 1)
                n = n.replace("\n", " ").replace("\t", " ").strip()[:40] or "Column%d" % (c + 1)
                while n in names:
                    n += "_%d" % c
                names.append(n)
                sh.cells[(b["r0"], b["c0"] + c)] = dict(t="s", v=n)
            sh.table = dict(name="Table%d" % (si + 1) if r.random() < 0.7 else "tbl_%s" % r.choice(["Sales", "Q1", "Data"]) + str(si),
                            r0=b["r0"], c0=b["c0"], r1=b["last"], c1=b["c0"] + b["ncols"] - 1, columns=names,
                            totals=r.random() < 0.25)
            if r.random() < 0.6:
                sh.pivot = dict(name="PivotTable%d" % (si + 1), seed=r.randint(0, 1 << 30))
        if r.random() < 0.35:
            for k in range(r.choice([1, 2, 3])):
                row, col = r.randint(0, 40), r.randint(0, 9)
                if r.random() < 0.7:
                    target = extras.random_url(r)
                    loc = None
                else:
                    target = None
                    other = r.choice(s.sheets).name
                    loc = "'%s'!A%d" % (other.replace("'", "''"), r.randint(1, 20))
                s.links.append(dict(sheet=si, row=row, col=col, url=target, loc=loc,
                                    tip=r.choice([None, None, "Open the source", "Détails"]),
                                    text=r.choice(["link", "Source", "see " + str(k)])))


# ---------------------------------------------------------------- formula rendering

def col_name(c):
    s = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


def quote_sheet(name):
    if all(ch.isalnum() or ch == "_" for ch in name) and not name[0].isdigit():
        return name
    return "'" + name.replace("'", "''") + "'"


def a1(row, col, abs_r=False, abs_c=False):
    return ("$" if abs_c else "") + col_name(col) + ("$" if abs_r else "") + str(row + 1)


def fmt_num(v):
    if v == int(v) and abs(v) < 1e15:
        return str(int(v)) if not (v == 0 and math.copysign(1, v) < 0) else "0"
    return repr(v)


def excel_text(n):
    k, a = n.kind, n.args
    if k == "num":
        return fmt_num(a[0])
    if k == "int":
        return str(a[0])
    if k == "str":
        return '"' + a[0].replace('"', '""') + '"'
    if k == "bool":
        return "TRUE" if a[0] else "FALSE"
    if k == "ref":
        sheet, row, col, ar, ac = a
        return (quote_sheet(sheet) + "!" if sheet else "") + a1(row, col, ar, ac)
    if k == "area":
        sheet, r1, c1, r2, c2, absf = a
        return (quote_sheet(sheet) + "!" if sheet else "") + a1(r1, c1, absf, absf) + ":" + a1(r2, c2, absf, absf)
    if k == "func":
        return a[0] + "(" + ",".join(excel_text(x) for x in a[1]) + ")"
    if k == "bin":
        return excel_text(a[1]) + a[0] + excel_text(a[2])
    if k == "neg":
        return "-" + excel_text(a[0])
    if k == "pct":
        return excel_text(a[0]) + "%"
    if k == "paren":
        return "(" + excel_text(a[0]) + ")"
    raise ValueError(k)


def ods_ref(sheet, row, col, ar, ac):
    s = "[" + (("$" + quote_sheet(sheet)) if sheet else "") + "." + a1(row, col, ar, ac) + "]"
    return s


def ods_text(n):
    k, a = n.kind, n.args
    if k == "ref":
        return ods_ref(*a)
    if k == "area":
        sheet, r1, c1, r2, c2, absf = a
        p = ("$" + quote_sheet(sheet)) if sheet else ""
        return "[" + p + "." + a1(r1, c1, absf, absf) + ":." + a1(r2, c2, absf, absf) + "]"
    if k == "func":
        return a[0] + "(" + ";".join(ods_text(x) for x in a[1]) + ")"
    if k == "bin":
        return ods_text(a[1]) + a[0] + ods_text(a[2])
    if k == "neg":
        return "-" + ods_text(a[0])
    if k == "pct":
        return ods_text(a[0]) + "%"
    if k == "paren":
        return "(" + ods_text(a[0]) + ")"
    return excel_text(n)


# ---------------------------------------------------------------- BIFF12 rgce

BINOPS = {"+": 0x03, "-": 0x04, "*": 0x05, "/": 0x06, "^": 0x07, "&": 0x08, "<": 0x09, "<=": 0x0A,
          "=": 0x0B, ">": 0x0C, ">=": 0x0D, "<>": 0x0E}
FTAB_ARGC = {0: 255, 1: 3, 4: 255, 5: 255, 6: 255, 7: 255, 10: 0, 19: 0, 20: 1, 21: 1, 22: 1, 24: 1, 25: 1,
             27: 2, 31: 3, 32: 1, 36: 255, 37: 255, 38: 1, 39: 2, 65: 3, 69: 1, 112: 1, 113: 1, 115: 255,
             116: 255, 118: 1, 129: 1, 169: 255, 183: 255, 221: 0, 336: 255, 337: 2}


def b12_rgce(n, sheet_index):
    """Return BIFF12 rgce bytes. sheet_index maps a sheet name to its XTI index."""
    k, a = n.kind, n.args
    if k == "num":
        return b"\x1f" + struct.pack("<d", a[0])
    if k == "int":
        return b"\x1e" + struct.pack("<H", a[0])
    if k == "str":
        u = a[0].encode("utf-16-le")
        return b"\x17" + struct.pack("<H", len(u) // 2) + u
    if k == "bool":
        return b"\x1d" + bytes([1 if a[0] else 0])
    if k == "ref":
        sheet, row, col, ar, ac = a
        colw = col | (0 if ar else 0x4000) | (0 if ac else 0x8000)
        if sheet:
            return b"\x3a" + struct.pack("<HIH", sheet_index[sheet], row, colw)
        return b"\x24" + struct.pack("<IH", row, colw)
    if k == "area":
        sheet, r1, c1, r2, c2, absf = a
        fl = 0 if absf else 0xC000
        if sheet:
            return b"\x3b" + struct.pack("<HIIHH", sheet_index[sheet], r1, r2, c1 | fl, c2 | fl)
        return b"\x25" + struct.pack("<IIHH", r1, r2, c1 | fl, c2 | fl)
    if k == "func":
        name, args = a
        idx, fixed = FUNCS[name]
        body = b"".join(b12_rgce(x, sheet_index) for x in args)
        if fixed is not None and FTAB_ARGC.get(idx) == len(args):
            return body + b"\x41" + struct.pack("<H", idx)
        return body + b"\x42" + bytes([len(args)]) + struct.pack("<H", idx)
    if k == "bin":
        return b12_rgce(a[1], sheet_index) + b12_rgce(a[2], sheet_index) + bytes([BINOPS[a[0]]])
    if k == "neg":
        return b12_rgce(a[0], sheet_index) + b"\x13"
    if k == "pct":
        return b12_rgce(a[0], sheet_index) + b"\x14"
    if k == "paren":
        return b12_rgce(a[0], sheet_index) + b"\x15"
    raise ValueError(k)


# ---------------------------------------------------------------- cached values (rough evaluator)

def evaluate(n, sheet, spec, depth=0):
    """A small evaluator so hand-written formats can carry plausible cached values."""
    k, a = n.kind, n.args
    try:
        if depth > 20:
            return 0.0
        if k in ("num",):
            return float(a[0])
        if k == "int":
            return float(a[0])
        if k == "str":
            return a[0]
        if k == "bool":
            return bool(a[0])
        if k == "ref":
            sh = sheet if a[0] is None else next(s for s in spec.sheets if s.name == a[0])
            c = sh.cells.get((a[1], a[2]))
            if c is None:
                return 0.0
            if c["t"] == "f":
                return evaluate(c["f"], sh, spec, depth + 1)
            return c["v"]
        if k == "area":
            sh = sheet if a[0] is None else next(s for s in spec.sheets if s.name == a[0])
            vals = []
            for r in range(a[1], a[3] + 1):
                for c in range(a[2], a[4] + 1):
                    cell = sh.cells.get((r, c))
                    if cell is None:
                        continue
                    v = evaluate(cell["f"], sh, spec, depth + 1) if cell["t"] == "f" else cell["v"]
                    if isinstance(v, float):
                        vals.append(v)
            return vals
        if k == "func":
            name, args = a
            vs = [evaluate(x, sheet, spec, depth + 1) for x in args]
            flat = []
            for v in vs:
                flat.extend(v if isinstance(v, list) else [v])
            nums = [v for v in flat if isinstance(v, float)]
            if name == "SUM":
                return float(sum(nums))
            if name == "AVERAGE":
                return sum(nums) / len(nums) if nums else ("#DIV/0!",)
            if name == "MIN":
                return min(nums) if nums else 0.0
            if name == "MAX":
                return max(nums) if nums else 0.0
            if name in ("COUNT",):
                return float(len(nums))
            if name == "PRODUCT":
                p = 1.0
                for v in nums:
                    p *= v
                return p
            if name == "IF":
                return vs[1] if vs[0] else vs[2]
            if name == "ABS":
                return abs(vs[0])
            if name == "ROUND":
                return float(round(vs[0], int(vs[1])))
            if name == "SQRT":
                return math.sqrt(vs[0]) if vs[0] >= 0 else ("#NUM!",)
            if name == "LEN":
                return float(len(vs[0]))
            if name == "AND":
                return all(bool(v) for v in flat)
            if name == "NA":
                return ("#N/A",)
            if name == "PI":
                return math.pi
            return 0.0
        if k == "bin":
            x = evaluate(a[1], sheet, spec, depth + 1)
            y = evaluate(a[2], sheet, spec, depth + 1)
            op = a[0]
            if op == "&":
                def tx(v):
                    if isinstance(v, bool):
                        return "TRUE" if v else "FALSE"
                    if isinstance(v, float):
                        return fmt_num(v)
                    return str(v)
                return tx(x) + tx(y)
            if not isinstance(x, (float, bool)) or not isinstance(y, (float, bool)):
                if op in (">", "<", ">=", "<=", "=", "<>"):
                    return False
                return ("#VALUE!",)
            x, y = float(x), float(y)
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                return x / y if y else ("#DIV/0!",)
            if op == "^":
                try:
                    return float(x ** y)
                except Exception:
                    return ("#NUM!",)
            return {">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y, "=": x == y, "<>": x != y}[op]
        if k == "neg":
            v = evaluate(a[0], sheet, spec, depth + 1)
            return -v if isinstance(v, float) else v
        if k == "pct":
            v = evaluate(a[0], sheet, spec, depth + 1)
            return v / 100.0 if isinstance(v, float) else v
        if k == "paren":
            return evaluate(a[0], sheet, spec, depth + 1)
    except Exception:
        return ("#VALUE!",)
    return 0.0


def cached(cell, sheet, spec):
    v = evaluate(cell["f"], sheet, spec)
    if isinstance(v, list):
        v = ("#VALUE!",)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        v = ("#NUM!",)
    if isinstance(v, complex):
        v = ("#NUM!",)
    return v


# ---------------------------------------------------------------- XlsxWriter / openpyxl / xlwt

def fmt_code(fmt):
    if fmt is None:
        return None
    if fmt.startswith("builtin:"):
        return int(fmt.split(":")[1])
    return fmt


def write_xlsxwriter(spec, path):
    import xlsxwriter
    wb = xlsxwriter.Workbook(path, {"date_1904": spec.is1904, "strings_to_numbers": False,
                                    "strings_to_formulas": False, "strings_to_urls": False})
    fcache = {}

    def fmt(code):
        if code is None:
            return None
        if code not in fcache:
            fcache[code] = wb.add_format({"num_format": code})
        return fcache[code]
    for sh in spec.sheets:
        ws = wb.add_worksheet(sh.name)
        if sh.state == "hidden":
            ws.hide()
        elif sh.state == "veryHidden":
            ws.very_hidden()
        for (r, c), cell in sorted(sh.cells.items()):
            f = fmt(fmt_code(cell.get("fmt")))
            t = cell["t"]
            if t == "s":
                ws.write_string(r, c, cell["v"], f)
            elif t in ("n", "d"):
                ws.write_number(r, c, cell["v"], f)
            elif t == "b":
                ws.write_boolean(r, c, cell["v"], f)
            elif t == "f":
                v = cached(cell, sh, spec)
                if isinstance(v, tuple):
                    v = v[0]
                ws.write_formula(r, c, "=" + excel_text(cell["f"]), f, v)
        for (r1, c1, r2, c2) in sh.merges:
            v = sh.cells.get((r1, c1), {}).get("v", "")
            ws.merge_range(r1, c1, r2, c2, v if isinstance(v, str) else "")
    for (name, sheet, val) in spec.names:
        if sheet is None:
            wb.define_name(name, "=" + fmt_num(val))
        else:
            r1, c1, r2, c2 = val
            wb.define_name(name, "=" + quote_sheet(sheet) + "!" + a1(r1, c1, True, True) + ":" + a1(r2, c2, True, True))
    xw_extras(spec, wb)
    wb.close()


def write_openpyxl(spec, path):
    import openpyxl
    from openpyxl.workbook.defined_name import DefinedName
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if spec.is1904:
        wb.epoch = openpyxl.utils.datetime.CALENDAR_MAC_1904
    for sh in spec.sheets:
        ws = wb.create_sheet(sh.name)
        ws.sheet_state = sh.state
        for (r, c), cell in sorted(sh.cells.items()):
            t = cell["t"]
            x = ws.cell(row=r + 1, column=c + 1)
            if t == "f":
                x.value = "=" + excel_text(cell["f"])
            else:
                x.value = cell["v"]
            code = fmt_code(cell.get("fmt"))
            if code is not None:
                if isinstance(code, int):
                    code = openpyxl.styles.numbers.BUILTIN_FORMATS.get(code, "General")
                x.number_format = code
        for (r1, c1, r2, c2) in sh.merges:
            ws.merge_cells(start_row=r1 + 1, start_column=c1 + 1, end_row=r2 + 1, end_column=c2 + 1)
    for (name, sheet, val) in spec.names:
        if sheet is None:
            txt = fmt_num(val)
        else:
            r1, c1, r2, c2 = val
            txt = quote_sheet(sheet) + "!" + a1(r1, c1, True, True) + ":" + a1(r2, c2, True, True)
        try:
            wb.defined_names[name] = DefinedName(name, attr_text=txt)
        except TypeError:
            wb.defined_names.append(DefinedName(name, attr_text=txt))
    op_extras(spec, wb)
    wb.save(path)


PROP_KEYS_XW = {"title": "title", "subject": "subject", "author": "author", "manager": "manager",
                "company": "company", "category": "category", "keywords": "keywords", "comments": "comments",
                "status": "status"}


def xw_extras(spec, wb):
    import extras
    if spec.props:
        wb.set_properties(dict(spec.props))
    if spec.vba:
        wb.add_vba_project(io.BytesIO(extras.vba_project_bin(random.Random(spec.vba_seed), [s.name for s in spec.sheets])),
                           is_stream=True)
    sheets = wb.worksheets()
    for im in spec.images:
        sheets[im["sheet"]].insert_image(im["row"], im["col"], "image.%s" % im["ext"],
                                         {"image_data": io.BytesIO(im["data"]), "description": im["name"]})
    for si, sh in enumerate(spec.sheets):
        t = sh.table
        if t:
            cols = []
            for k, n in enumerate(t["columns"]):
                c = {"header": n}
                if t["totals"]:
                    c["total_function"] = "sum" if k in sh.block["numcols"] else None
                    if c["total_function"] is None:
                        del c["total_function"]
                cols.append(c)
            try:
                sheets[si].add_table(t["r0"], t["c0"], t["r1"] + (1 if t["totals"] else 0), t["c1"],
                                     {"name": t["name"], "columns": cols, "total_row": t["totals"]})
            except Exception as e:
                print("xw table skipped", type(e).__name__)
    for ln in spec.links:
        url = ln["url"] if ln["url"] else "internal:" + ln["loc"]
        try:
            sheets[ln["sheet"]].write_url(ln["row"], ln["col"], url, string=ln["text"], tip=ln["tip"])
        except Exception as e:
            print("xw link skipped", type(e).__name__)


def op_extras(spec, wb):
    from openpyxl.worksheet.hyperlink import Hyperlink
    from openpyxl.worksheet.table import Table
    p = spec.props
    if p:
        for src, dst in (("title", "title"), ("subject", "subject"), ("author", "creator"), ("keywords", "keywords"),
                         ("comments", "description"), ("category", "category"), ("status", "contentStatus")):
            if src in p:
                setattr(wb.properties, dst, p[src])
    sheets = wb.worksheets
    for im in spec.images:
        try:
            from openpyxl.drawing.image import Image
            img = Image(io.BytesIO(im["data"]))
            sheets[im["sheet"]].add_image(img, a1(im["row"], im["col"]))
        except Exception as e:
            print("op image skipped", type(e).__name__)
    for si, sh in enumerate(spec.sheets):
        t = sh.table
        if t and not t["totals"]:
            try:
                sheets[si].add_table(Table(displayName=t["name"], ref="%s:%s" % (a1(t["r0"], t["c0"]), a1(t["r1"], t["c1"]))))
            except Exception as e:
                print("op table skipped", type(e).__name__)
    for ln in spec.links:
        c = sheets[ln["sheet"]].cell(row=ln["row"] + 1, column=ln["col"] + 1)
        if c.value is None:
            c.value = ln["text"]
        if ln["url"]:
            c.hyperlink = ln["url"]
            if ln["tip"]:
                c.hyperlink.tooltip = ln["tip"]
        else:
            c.hyperlink = Hyperlink(ref=c.coordinate, location=ln["loc"], tooltip=ln["tip"], display=ln["text"])


def write_xlwt(spec, path):
    import xlwt
    wb = xlwt.Workbook(encoding="utf-8")
    if spec.is1904:
        wb.dates_1904 = True
    scache = {}

    def style(code):
        if code is None:
            return xlwt.Style.default_style
        if isinstance(code, int):
            code = {14: "M/D/YY", 15: "D-MMM-YY", 16: "D-MMM", 17: "MMM-YY", 18: "h:mm AM/PM",
                    19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "M/D/YY h:mm", 45: "mm:ss",
                    46: "[h]:mm:ss", 47: "mm:ss.0"}[code]
        if code not in scache:
            scache[code] = xlwt.easyxf(num_format_str=code)
        return scache[code]
    for sh in spec.sheets:
        ws = wb.add_sheet(sh.name[:31], cell_overwrite_ok=True)
        if sh.state != "visible":
            ws.visibility = 1 if sh.state == "hidden" else 2
        merged = set()
        for (r1, c1, r2, c2) in sh.merges:
            v = sh.cells.get((r1, c1), {}).get("v", "")
            ws.write_merge(r1, r2, c1, c2, v if isinstance(v, str) else "")
            for rr in range(r1, r2 + 1):
                for cc in range(c1, c2 + 1):
                    merged.add((rr, cc))
        for (r, c), cell in sorted(sh.cells.items()):
            if (r, c) in merged or r > 65535 or c > 255:
                continue
            st = style(fmt_code(cell.get("fmt")))
            t = cell["t"]
            if t == "s":
                ws.write(r, c, cell["v"][:32767], st)
            elif t in ("n", "d"):
                ws.write(r, c, cell["v"], st)
            elif t == "b":
                ws.write(r, c, bool(cell["v"]), st)
            elif t == "f":
                try:
                    ws.write(r, c, xlwt.Formula(excel_text(cell["f"])), st)
                except Exception:
                    pass
    wb.save(path)


# ---------------------------------------------------------------- hand-written SpreadsheetML

def xml_attr(s):
    return xesc(s, {'"': "&quot;"})


def raw_xlsx(spec, path, r):
    """A SpreadsheetML package with features the big writers rarely emit."""
    opt_inline = r.random() < 0.5
    opt_no_r = r.random() < 0.4          # omit r= on some cells/rows
    opt_shared = r.random() < 0.7        # shared formulas for runs of similar formulas
    opt_rich = r.random() < 0.5
    opt_prefix = r.random() < 0.3        # x: prefixed SpreadsheetML elements
    opt_absolute_paths = r.random() < 0.3
    P = "x:" if opt_prefix else ""
    ns = 'xmlns%s="http://schemas.openxmlformats.org/spreadsheetml/2006/main"' % (":x" if opt_prefix else "")
    import extras
    X = extras.RawXlsxExtras(spec, r, P)
    sheet_rels = []
    # styles
    numfmts = {}
    xfs = [0]  # xf index -> numFmtId

    def xf_for(code):
        if code is None:
            return 0
        if isinstance(code, int):
            fid = code
        else:
            if code not in numfmts:
                numfmts[code] = 164 + len(numfmts)
            fid = numfmts[code]
        if fid not in xfs:
            xfs.append(fid)
        return xfs.index(fid)
    sst = []
    sst_index = {}

    def sidx(sv):
        if sv not in sst_index:
            sst_index[sv] = len(sst)
            sst.append(sv)
        return sst_index[sv]

    def text_el(s):
        sp = ' xml:space="preserve"' if (s != s.strip() or "\n" in s) else ""
        s2 = s.replace("\r", "_x000D_")
        return "<%st%s>%s</%st>" % (P, sp, xesc(s2), P)

    def rich_el(s):
        if opt_rich and len(s) > 3 and r.random() < 0.4:
            k = len(s) // 2
            parts = [s[:k], s[k:]]
            out = ""
            for i, p in enumerate(parts):
                sp = ' xml:space="preserve"' if p != p.strip() else ""
                out += '<%sr><%srPr><%sb/></%srPr><%st%s>%s</%st></%sr>' % (P, P, P, P, P, sp, xesc(p), P, P)
            if r.random() < 0.3:
                out += '<%srPh sb="0" eb="1"><%st>yomi</%st></%srPh>' % (P, P, P, P)
            return out
        return text_el(s)
    sheets_xml = []
    for si, sh in enumerate(spec.sheets):
        rows = {}
        for (rr, cc), cell in sh.cells.items():
            rows.setdefault(rr, []).append((cc, cell))
        out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<%sworksheet %s xmlns:r="%s">' % (P, ns, extras.REL)]
        if sh.cells:
            ks = sorted(sh.cells)
            mr = max(k[0] for k in ks)
            mc = max(k[1] for k in ks)
            nr = min(k[0] for k in ks)
            nc = min(k[1] for k in ks)
            out.append('<%sdimension ref="%s:%s"/>' % (P, a1(nr, nc), a1(mr, mc)))
        out.append("<%ssheetData>" % P)
        shared_groups = {}
        prev_row = -1
        for rr in sorted(rows):
            omit_row_r = opt_no_r and rr == prev_row + 1 and r.random() < 0.5
            prev_row = rr
            out.append("<%srow%s>" % (P, "" if omit_row_r else ' r="%d"' % (rr + 1)))
            prev_c = -1
            for cc, cell in sorted(rows[rr], key=lambda x: x[0]):
                omit_c_r = opt_no_r and not omit_row_r and cc == prev_c + 1 and r.random() < 0.5
                if omit_row_r and cc != prev_c + 1:
                    omit_c_r = False
                prev_c = cc
                ra = "" if omit_c_r else ' r="%s"' % a1(rr, cc)
                st = xf_for(fmt_code(cell.get("fmt")))
                sa = ' s="%d"' % st if st else ""
                t = cell["t"]
                if t == "s":
                    v = cell["v"]
                    if opt_inline and r.random() < 0.7:
                        out.append('<%sc%s%s t="inlineStr"><%sis>%s</%sis></%sc>' % (P, ra, sa, P, rich_el(v), P, P))
                    elif r.random() < 0.1:
                        out.append('<%sc%s%s t="str"><%sv>%s</%sv></%sc>' % (P, ra, sa, P, xesc(v.replace("\r", "_x000D_")), P, P))
                    else:
                        key = ("rich", v) if (opt_rich and r.random() < 0.3) else ("plain", v)
                        out.append('<%sc%s%s t="s"><%sv>%d</%sv></%sc>' % (P, ra, sa, P, sidx(key), P, P))
                elif t in ("n", "d"):
                    v = cell["v"]
                    if t == "d" and r.random() < 0.15:
                        iso = (dt.datetime(1899, 12, 30) + dt.timedelta(days=v)).replace(microsecond=0).isoformat()
                        out.append('<%sc%s%s t="d"><%sv>%s</%sv></%sc>' % (P, ra, sa, P, iso, P, P))
                    else:
                        tn = ' t="n"' if r.random() < 0.3 else ""
                        out.append('<%sc%s%s%s><%sv>%s</%sv></%sc>' % (P, ra, sa, tn, P, repr(float(v)), P, P))
                elif t == "b":
                    out.append('<%sc%s%s t="b"><%sv>%d</%sv></%sc>' % (P, ra, sa, P, 1 if cell["v"] else 0, P, P))
                elif t == "f":
                    v = cached(cell, sh, spec)
                    ftxt = excel_text(cell["f"])
                    key = None
                    if opt_shared:
                        # group formulas by their R1C1-like shape: same text after removing row numbers
                        shape = "".join(ch for ch in ftxt if not ch.isdigit())
                        key = (cc, shape)
                    fel = "<%sf>%s</%sf>" % (P, xesc(ftxt), P)
                    if key is not None:
                        g = shared_groups.get(key)
                        if g is None:
                            # find the run of rows below with the same shape in this column
                            run = [rr]
                            nxt = rr + 1
                            while (nxt, cc) in sh.cells and sh.cells[(nxt, cc)]["t"] == "f" and \
                                    "".join(ch for ch in excel_text(sh.cells[(nxt, cc)]["f"]) if not ch.isdigit()) == shape:
                                run.append(nxt)
                                nxt += 1
                            if len(run) > 1:
                                g = shared_groups[key] = (len(shared_groups), run[-1])
                                fel = '<%sf t="shared" ref="%s:%s" si="%d">%s</%sf>' % (
                                    P, a1(rr, cc), a1(run[-1], cc), g[0], xesc(ftxt), P)
                            else:
                                shared_groups[key] = None
                        elif g is not None and rr <= g[1]:
                            fel = '<%sf t="shared" si="%d"/>' % (P, g[0])
                    if isinstance(v, tuple):
                        out.append('<%sc%s%s t="e">%s<%sv>%s</%sv></%sc>' % (P, ra, sa, fel, P, v[0], P, P))
                    elif isinstance(v, bool):
                        out.append('<%sc%s%s t="b">%s<%sv>%d</%sv></%sc>' % (P, ra, sa, fel, P, int(v), P, P))
                    elif isinstance(v, str):
                        out.append('<%sc%s%s t="str">%s<%sv>%s</%sv></%sc>' % (P, ra, sa, fel, P, xesc(v), P, P))
                    else:
                        out.append('<%sc%s%s>%s<%sv>%s</%sv></%sc>' % (P, ra, sa, fel, P, repr(float(v)), P, P))
            out.append("</%srow>" % P)
        out.append("</%ssheetData>" % P)
        if sh.merges:
            out.append('<%smergeCells count="%d">' % (P, len(sh.merges)))
            for (r1, c1, r2, c2) in sh.merges:
                out.append('<%smergeCell ref="%s:%s"/>' % (P, a1(r1, c1), a1(r2, c2)))
            out.append("</%smergeCells>" % P)
        tail, srels = X.sheet_tail(si, "xl/worksheets/sheet%d.xml" % (si + 1))
        out.append(tail)
        out.append("</%sworksheet>" % P)
        sheets_xml.append(X.rich_inject(si, "".join(out)))
        sheet_rels.append(srels)
    # shared strings
    sst_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<%ssst %s count="%d" uniqueCount="%d">' % (P, ns, len(sst), len(sst))]
    for kind, sv in sst:
        sst_xml.append("<%ssi>%s</%ssi>" % (P, rich_el(sv) if kind == "rich" else text_el(sv), P))
    sst_xml.append("</%ssst>" % P)
    # styles
    sty = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<%sstyleSheet %s>' % (P, ns)]
    if numfmts:
        sty.append('<%snumFmts count="%d">' % (P, len(numfmts)))
        for code, fid in numfmts.items():
            sty.append('<%snumFmt numFmtId="%d" formatCode="%s"/>' % (P, fid, xml_attr(code)))
        sty.append("</%snumFmts>" % P)
    sty.append('<%sfonts count="1"><%sfont><%ssz val="11"/><%sname val="Calibri"/></%sfont></%sfonts>' % (P, P, P, P, P, P))
    sty.append('<%scellStyleXfs count="1"><%sxf numFmtId="0" fontId="0"/></%scellStyleXfs>' % (P, P, P))
    sty.append('<%scellXfs count="%d">' % (P, len(xfs)))
    for fid in xfs:
        sty.append('<%sxf numFmtId="%d" fontId="0" xfId="0"%s/>' % (P, fid, ' applyNumberFormat="1"' if fid else ""))
    sty.append("</%scellXfs></%sstyleSheet>" % (P, P))
    # workbook
    wbx = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<%sworkbook %s xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' % (P, ns)]
    wbx.append('<%sworkbookPr%s/>' % (P, ' date1904="1"' if spec.is1904 else (' date1904="false"' if r.random() < 0.3 else "")))
    wbx.append("<%ssheets>" % P)
    for i, sh in enumerate(spec.sheets):
        st = "" if sh.state == "visible" else ' state="%s"' % sh.state
        wbx.append('<%ssheet name="%s" sheetId="%d"%s r:id="rId%d"/>' % (P, xml_attr(sh.name), i + 1, st, i + 1))
    wbx.append("</%ssheets>" % P)
    if spec.names:
        wbx.append("<%sdefinedNames>" % P)
        for (name, sheet, val) in spec.names:
            if sheet is None:
                txt = fmt_num(val)
            else:
                r1, c1, r2, c2 = val
                txt = quote_sheet(sheet) + "!" + a1(r1, c1, True, True) + ":" + a1(r2, c2, True, True)
            wbx.append('<%sdefinedName name="%s">%s</%sdefinedName>' % (P, name, xesc(txt), P))
        wbx.append("</%sdefinedNames>" % P)
    X.finish()
    if X.wb_tail:
        wbx.append("<%spivotCaches>%s</%spivotCaches>" % (P, X.wb_tail.replace("<pivotCache ", "<%spivotCache " % P), P))
    wbx.append("</%sworkbook>" % P)
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i in range(len(spec.sheets)):
        tgt = ("/xl/worksheets/sheet%d.xml" if opt_absolute_paths else "worksheets/sheet%d.xml") % (i + 1)
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="%s"/>' % (i + 1, tgt))
    n = len(spec.sheets)
    rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>' % (n + 1))
    rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (n + 2))
    for rid, typ, tgt in X.wb_rels:
        full = ("http://schemas.microsoft.com/office/2006/relationships/vbaProject" if typ == "vbaProject"
                else "http://schemas.openxmlformats.org/officeDocument/2006/relationships/" + typ)
        rels.append('<Relationship Id="%s" Type="%s" Target="%s"/>' % (rid, full, tgt))
    rels.append("</Relationships>")
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>',
          '<Override PartName="/xl/workbook.xml" ContentType="%s"/>' % (
              "application/vnd.ms-excel.sheet.macroEnabled.main+xml" if spec.vba
              else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")] + X.ct
    for i in range(n):
        ct.append('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1))
    ct.append('<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>')
    ct.append('<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>')
    ct.append("</Types>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", "".join(wbx))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        z.writestr("xl/styles.xml", "".join(sty))
        z.writestr("xl/sharedStrings.xml", "".join(sst_xml))
        for i, x in enumerate(sheets_xml):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), x)
            if sheet_rels[i]:
                z.writestr("xl/worksheets/_rels/sheet%d.xml.rels" % (i + 1),
                           '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns='
                           '"http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
                           % "".join(sheet_rels[i]))
        for name, data in X.parts:
            z.writestr(name, data)


# ---------------------------------------------------------------- hand-written BIFF12 (xlsb)

def b12_rec(typ, body=b""):
    out = bytearray()
    if typ < 0x80:
        out.append(typ)
    else:
        out.append((typ & 0x7F) | 0x80)
        out.append((typ >> 7) & 0x7F)
    n = len(body)
    for i in range(4):
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out) + body


def wstr(s):
    u = s.encode("utf-16-le")
    return struct.pack("<I", len(u) // 2) + u


def b12_cell_hdr(col, style):
    return struct.pack("<I", col) + struct.pack("<I", style & 0xFFFFFF)


def raw_xlsb(spec, path, r):
    numfmts = {}
    xfs = [0]

    def xf_for(code):
        if code is None:
            return 0
        if isinstance(code, int):
            fid = code
        else:
            if code not in numfmts:
                numfmts[code] = 164 + len(numfmts)
            fid = numfmts[code]
        if fid not in xfs:
            xfs.append(fid)
        return xfs.index(fid)
    sst = []
    sidx = {}
    sheet_index = {sh.name: i for i, sh in enumerate(spec.sheets)}
    use_sst = r.random() < 0.8
    sheet_bins = []
    for sh in spec.sheets:
        rows = {}
        for (rr, cc), cell in sh.cells.items():
            rows.setdefault(rr, []).append((cc, cell))
        b = bytearray()
        b += b12_rec(0x0081)  # BrtBeginSheet
        b += b12_rec(0x0093, struct.pack("<IIi", 0x000004C9, 0xFFFFFFFF, -1) + struct.pack("<I", 0) + wstr(""))  # BrtWsProp
        if sh.cells:
            ks = sorted(sh.cells)
            b += b12_rec(0x0094, struct.pack("<IIII", min(k[0] for k in ks), max(k[0] for k in ks),
                                             min(k[1] for k in ks), max(k[1] for k in ks)))
        else:
            b += b12_rec(0x0094, struct.pack("<IIII", 0, 0, 0, 0))
        b += b12_rec(0x0085)  # BrtBeginWsViews
        b += b12_rec(0x0089, struct.pack("<HIIIIHHHH", 0x03DC, 0, 0, 0, 64, 0, 100, 0, 0) + struct.pack("<I", 0))  # BrtBeginWsView
        b += b12_rec(0x008A)  # BrtEndWsView
        b += b12_rec(0x0086)  # BrtEndWsViews
        b += b12_rec(0x01E5, struct.pack("<IHHHHH", 0xFFFFFFFF, 8, 300, 0, 0, 0))  # BrtWsFmtInfo
        b += b12_rec(0x0091)  # BrtBeginSheetData
        for rr in sorted(rows):
            b += b12_rec(0x0000, struct.pack("<IIHBBB", rr, 0, 300, 0, 0, 0) + struct.pack("<I", 0))  # BrtRowHdr
            for cc, cell in sorted(rows[rr], key=lambda x: x[0]):
                st = xf_for(fmt_code(cell.get("fmt")))
                t = cell["t"]
                hdr = b12_cell_hdr(cc, st)
                if t == "s":
                    v = cell["v"]
                    if use_sst:
                        if v not in sidx:
                            sidx[v] = len(sst)
                            sst.append(v)
                        b += b12_rec(0x0007, hdr + struct.pack("<I", sidx[v]))
                    else:
                        b += b12_rec(0x0006, hdr + wstr(v))
                elif t in ("n", "d"):
                    v = float(cell["v"])
                    rk = None
                    if v == int(v) and -(1 << 29) <= v < (1 << 29):
                        rk = (int(v) << 2) | 2
                    elif v * 100 == int(v * 100) and -(1 << 29) <= v * 100 < (1 << 29) and r.random() < 0.5:
                        rk = (int(round(v * 100)) << 2) | 3
                    if rk is not None and r.random() < 0.8:
                        b += b12_rec(0x0002, hdr + struct.pack("<i", rk))
                    else:
                        b += b12_rec(0x0005, hdr + struct.pack("<d", v))
                elif t == "b":
                    b += b12_rec(0x0004, hdr + bytes([1 if cell["v"] else 0]))
                elif t == "f":
                    v = cached(cell, sh, spec)
                    rg = b12_rgce(cell["f"], sheet_index)
                    fm = struct.pack("<I", len(rg)) + rg + struct.pack("<I", 0)
                    grbit = struct.pack("<H", 0)
                    if isinstance(v, tuple):
                        code = {"#NULL!": 0, "#DIV/0!": 7, "#VALUE!": 15, "#REF!": 23, "#NAME?": 29, "#NUM!": 36, "#N/A": 42}[v[0]]
                        b += b12_rec(0x000B, hdr + bytes([code]) + grbit + fm)
                    elif isinstance(v, bool):
                        b += b12_rec(0x000A, hdr + bytes([int(v)]) + grbit + fm)
                    elif isinstance(v, str):
                        b += b12_rec(0x0008, hdr + wstr(v) + grbit + fm)
                    else:
                        b += b12_rec(0x0009, hdr + struct.pack("<d", float(v)) + grbit + fm)
            if r.random() < 0.05:
                b += b12_rec(0x0001, b12_cell_hdr(200, 0))  # a styled blank cell
        b += b12_rec(0x0092)  # BrtEndSheetData
        if sh.merges:
            b += b12_rec(0x00B1, struct.pack("<I", len(sh.merges)))
            for (r1, c1, r2, c2) in sh.merges:
                b += b12_rec(0x00B0, struct.pack("<IIII", r1, r2, c1, c2))
            b += b12_rec(0x00B2)
        b += b12_rec(0x0082)  # BrtEndSheet
        sheet_bins.append(bytes(b))
    # workbook.bin
    w = bytearray()
    w += b12_rec(0x0083)  # BrtBeginBook
    w += b12_rec(0x0080, struct.pack("<16s", b"\x00" * 16) + wstr("xl") + wstr("7") + wstr("7") + wstr("27328"))  # BrtFileVersion
    w += b12_rec(0x0099, struct.pack("<II", (1 if spec.is1904 else 0) | 0x20, 0) + wstr("ThisWorkbook"))  # BrtWbProp
    w += b12_rec(0x0087)  # BrtBeginBookViews
    w += b12_rec(0x009E, struct.pack("<iiiiiIIB", 0, 0, 20000, 12000, 600, 0, 0, 0x78))  # BrtBookView
    w += b12_rec(0x0088)  # BrtEndBookViews
    w += b12_rec(0x008F)  # BrtBeginBundleShs
    for i, sh in enumerate(spec.sheets):
        st = {"visible": 0, "hidden": 1, "veryHidden": 2}[sh.state]
        w += b12_rec(0x009C, struct.pack("<II", st, i + 1) + wstr("rId%d" % (i + 1)) + wstr(sh.name))
    w += b12_rec(0x0090)  # BrtEndBundleShs
    xtis = [sh.name for sh in spec.sheets]
    w += b12_rec(0x0161)  # BrtBeginExternals
    w += b12_rec(0x0163)  # BrtSupSelf
    w += b12_rec(0x016A, struct.pack("<I", len(xtis)) + b"".join(struct.pack("<Iii", 0, i, i) for i in range(len(xtis))))
    w += b12_rec(0x0162)  # BrtEndExternals
    for (name, sheet, val) in spec.names:
        if sheet is None:
            rg = b"\x1f" + struct.pack("<d", float(val))
        else:
            r1, c1, r2, c2 = val
            rg = b"\x3b" + struct.pack("<HIIHH", sheet_index[sheet], r1, r2, c1, c2)
        w += b12_rec(0x0027, struct.pack("<IBI", 0, 0, 0xFFFFFFFF) + wstr(name) + struct.pack("<I", len(rg)) + rg
                     + struct.pack("<I", 0) + struct.pack("<I", 0xFFFFFFFF))
    w += b12_rec(0x009D, struct.pack("<IIdIH", 100, 0, 0.001, 0, 0))  # BrtCalcProp
    w += b12_rec(0x0084)  # BrtEndBook
    # styles.bin
    s = bytearray()
    s += b12_rec(0x0116)  # BrtBeginStyleSheet
    s += b12_rec(0x0267, struct.pack("<I", len(numfmts)))
    for code, fid in numfmts.items():
        s += b12_rec(0x002C, struct.pack("<H", fid) + wstr(code))
    s += b12_rec(0x0268)
    s += b12_rec(0x0263, struct.pack("<I", 1))  # BrtBeginFonts
    s += b12_rec(0x002B, struct.pack("<HHHHHBBBB", 220, 0, 400, 0, 0, 2, 0, 0, 0) + b"\x01\x00\x00\x00\x00\x00\x00\x00\x02" + wstr("Calibri"))
    s += b12_rec(0x0264)
    s += b12_rec(0x0272, struct.pack("<I", 1))  # BrtBeginCellStyleXFs
    s += b12_rec(0x002F, struct.pack("<HHHHHBBHH", 0xFFFF, 0, 0, 0, 0, 0, 0, 0, 0))
    s += b12_rec(0x0273)
    s += b12_rec(0x0269, struct.pack("<I", len(xfs)))  # BrtBeginCellXFs
    for fid in xfs:
        s += b12_rec(0x002F, struct.pack("<HHHHHBBHH", 0, fid, 0, 0, 0, 0, 0, 0, 0))
    s += b12_rec(0x026A)
    s += b12_rec(0x0117)  # BrtEndStyleSheet
    # sharedStrings.bin
    ss = bytearray()
    ss += b12_rec(0x009F, struct.pack("<II", len(sst), len(sst)))
    for v in sst:
        ss += b12_rec(0x0013, b"\x00" + wstr(v))
    ss += b12_rec(0x00A0)
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for i in range(len(spec.sheets)):
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.bin"/>' % (i + 1, i + 1))
    n = len(spec.sheets)
    rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.bin"/>' % (n + 1))
    if sst:
        rels.append('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.bin"/>' % (n + 2))
    rels.append("</Relationships>")
    ct = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
          '<Default Extension="bin" ContentType="application/vnd.ms-excel.sheet.binary.macroEnabled.main"/>',
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
          '<Default Extension="xml" ContentType="application/xml"/>']
    for i in range(n):
        ct.append('<Override PartName="/xl/worksheets/sheet%d.bin" ContentType="application/vnd.ms-excel.worksheet"/>' % (i + 1))
    ct.append('<Override PartName="/xl/styles.bin" ContentType="application/vnd.ms-excel.styles"/>')
    if sst:
        ct.append('<Override PartName="/xl/sharedStrings.bin" ContentType="application/vnd.ms-excel.sharedStrings"/>')
    ct.append("</Types>")
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.bin"/></Relationships>')
    import extras
    xparts = []
    for k, im in enumerate(spec.images):
        xparts.append(("xl/media/image%d.%s" % (k + 1, im["ext"]), im["data"]))
    dp = extras.doc_props_parts(spec, r)
    if dp:
        xparts += [("docProps/core.xml", dp[0]), ("docProps/app.xml", dp[1])]
    if spec.vba:
        xparts.append(("xl/vbaProject.bin", extras.vba_project_bin(random.Random(spec.vba_seed), [s_.name for s_ in spec.sheets])))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", root_rels)
        for name, data in xparts:
            z.writestr(name, data)
        z.writestr("xl/workbook.bin", bytes(w))
        z.writestr("xl/_rels/workbook.bin.rels", "".join(rels))
        z.writestr("xl/styles.bin", bytes(s))
        if sst:
            z.writestr("xl/sharedStrings.bin", bytes(ss))
        for i, x in enumerate(sheet_bins):
            z.writestr("xl/worksheets/sheet%d.bin" % (i + 1), x)


# ---------------------------------------------------------------- hand-written ODS

def ods_date(serial, is1904):
    base = dt.datetime(1904, 1, 1) if is1904 else dt.datetime(1899, 12, 30)
    d = base + dt.timedelta(days=serial)
    if d.hour == 0 and d.minute == 0 and d.second == 0 and d.microsecond == 0:
        return d.date().isoformat()
    return d.replace(microsecond=0).isoformat()


def raw_ods(spec, path, r):
    opt_repeat = r.random() < 0.7
    T = ['<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
         'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
         'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
         'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" office:version="1.3">',
         "<office:automatic-styles>",
         '<style:style style:name="ta1" style:family="table"><style:table-properties table:display="true"/></style:style>',
         '<style:style style:name="ta2" style:family="table"><style:table-properties table:display="false"/></style:style>',
         "</office:automatic-styles><office:body><office:spreadsheet>"]
    for sh in spec.sheets:
        style = "ta2" if sh.state != "visible" else "ta1"
        T.append('<table:table table:name="%s" table:style-name="%s">' % (xml_attr(sh.name), style))
        T.append('<table:table-column table:number-columns-repeated="%d"/>' % 30)
        rows = {}
        for (rr, cc), cell in sh.cells.items():
            rows.setdefault(rr, []).append((cc, cell))
        merged_origin = {(m[0], m[1]): m for m in sh.merges}
        covered = set()
        for (r1, c1, r2, c2) in sh.merges:
            for rr in range(r1, r2 + 1):
                for cc in range(c1, c2 + 1):
                    if (rr, cc) != (r1, c1):
                        covered.add((rr, cc))
        maxr = max(list(rows) + [m[2] for m in sh.merges] + [-1])
        cur = 0
        while cur <= maxr:
            if cur not in rows and not any(m[0] <= cur <= m[2] for m in sh.merges):
                # run of empty rows
                n = 1
                while cur + n <= maxr and (cur + n) not in rows and not any(m[0] <= cur + n <= m[2] for m in sh.merges):
                    n += 1
                if opt_repeat and n > 1:
                    T.append('<table:table-row table:number-rows-repeated="%d"><table:table-cell table:number-columns-repeated="30"/></table:table-row>' % n)
                else:
                    for _ in range(n):
                        T.append('<table:table-row><table:table-cell/></table:table-row>')
                cur += n
                continue
            T.append("<table:table-row>")
            cells = dict(rows.get(cur, []))
            mc = max(list(cells) + [c for (rr, c) in covered if rr == cur] + [m[3] for m in sh.merges if m[0] == cur] + [-1])
            c = 0
            while c <= mc:
                if (cur, c) in covered:
                    T.append("<table:covered-table-cell/>")
                    c += 1
                    continue
                cell = cells.get(c)
                if cell is None:
                    n = 1
                    while c + n <= mc and (c + n) not in cells and (cur, c + n) not in covered:
                        n += 1
                    T.append('<table:table-cell table:number-columns-repeated="%d"/>' % n if (opt_repeat and n > 1) else "<table:table-cell/>" * n)
                    c += n
                    continue
                span = ""
                m = merged_origin.get((cur, c))
                if m:
                    span = ' table:number-columns-spanned="%d" table:number-rows-spanned="%d"' % (m[3] - m[1] + 1, m[2] - m[0] + 1)
                t = cell["t"]
                if t == "s":
                    v = cell["v"]
                    paras = v.split("\n")
                    inner = ""
                    for p in paras:
                        if "  " in p and r.random() < 0.7:
                            sp = ' <text:s/>' if r.random() < 0.5 else ' <text:s text:c="1"/>'
                            inner += "<text:p>%s</text:p>" % sp.join(xesc(x) for x in p.split("  "))
                        else:
                            inner += "<text:p>%s</text:p>" % xesc(p)
                    if r.random() < 0.08:
                        inner = "<office:annotation><text:p>note</text:p></office:annotation>" + inner
                    if r.random() < 0.2:
                        T.append('<table:table-cell office:value-type="string" office:string-value="%s"%s><text:p>ignored</text:p></table:table-cell>' % (xml_attr(v), span))
                    else:
                        T.append('<table:table-cell office:value-type="string"%s>%s</table:table-cell>' % (span, inner))
                elif t == "n":
                    v = cell["v"]
                    vt = "float"
                    code = cell.get("fmt") or ""
                    if "%" in code:
                        vt = "percentage"
                    elif "EUR" in code or "$" in code:
                        vt = "currency"
                    extra = ' office:currency="EUR"' if vt == "currency" else ""
                    T.append('<table:table-cell office:value-type="%s"%s office:value="%s"%s><text:p>%s</text:p></table:table-cell>' % (vt, extra, repr(float(v)), span, fmt_num(v)))
                elif t == "d":
                    v = cell["v"]
                    code = cell.get("fmt") or ""
                    if code in ("hh:mm", "h:mm:ss AM/PM", "[h]:mm:ss", "mm:ss.0", "[mm]:ss", "builtin:18",
                                "builtin:19", "builtin:20", "builtin:21", "builtin:45", "builtin:46", "builtin:47"):
                        secs = (v % 1.0) * 86400
                        hh, rem = divmod(int(round(secs)), 3600)
                        mm, ss2 = divmod(rem, 60)
                        T.append('<table:table-cell office:value-type="time" office:time-value="PT%02dH%02dM%02dS"%s><text:p>x</text:p></table:table-cell>' % (hh, mm, ss2, span))
                    else:
                        T.append('<table:table-cell office:value-type="date" office:date-value="%s"%s><text:p>x</text:p></table:table-cell>' % (ods_date(v, spec.is1904), span))
                elif t == "b":
                    b = "true" if cell["v"] else "false"
                    T.append('<table:table-cell office:value-type="boolean" office:boolean-value="%s"%s><text:p>%s</text:p></table:table-cell>' % (b, span, b.upper()))
                elif t == "f":
                    v = cached(cell, sh, spec)
                    ftxt = "of:=" + ods_text(cell["f"])
                    fa = ' table:formula="%s"' % xml_attr(ftxt)
                    if isinstance(v, tuple):
                        T.append('<table:table-cell%s office:value-type="string" office:string-value=""%s><text:p>%s</text:p></table:table-cell>' % (fa, span, xesc(v[0])))
                    elif isinstance(v, bool):
                        T.append('<table:table-cell%s office:value-type="boolean" office:boolean-value="%s"%s><text:p>%s</text:p></table:table-cell>' % (fa, "true" if v else "false", span, "TRUE" if v else "FALSE"))
                    elif isinstance(v, str):
                        T.append('<table:table-cell%s office:value-type="string"%s><text:p>%s</text:p></table:table-cell>' % (fa, span, xesc(v)))
                    else:
                        T.append('<table:table-cell%s office:value-type="float" office:value="%s"%s><text:p>%s</text:p></table:table-cell>' % (fa, repr(float(v)), span, fmt_num(float(v))))
                c += 1
            T.append("</table:table-row>")
            cur += 1
        if opt_repeat and r.random() < 0.5:
            T.append('<table:table-row table:number-rows-repeated="1048000"><table:table-cell table:number-columns-repeated="1024"/></table:table-row>')
        T.append("</table:table>")
    if spec.names:
        T.append("<table:named-expressions>")
        for (name, sheet, val) in spec.names:
            if sheet is None:
                T.append('<table:named-expression table:name="%s" table:base-cell-address="$%s.$A$1" table:expression="of:=%s"/>' % (name, quote_sheet(spec.sheets[0].name), fmt_num(val)))
            else:
                r1, c1, r2, c2 = val
                T.append('<table:named-range table:name="%s" table:base-cell-address="$%s.$A$1" table:cell-range-address="$%s.%s:.%s"/>' % (
                    name, quote_sheet(sheet), quote_sheet(sheet), a1(r1, c1, True, True), a1(r2, c2, True, True)))
        T.append("</table:named-expressions>")
    T.append("</office:spreadsheet></office:body></office:document-content>")
    manifest = ('<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
                '<manifest:file-entry manifest:full-path="/" manifest:version="1.3" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/manifest.xml", manifest, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("content.xml", "".join(T), compress_type=zipfile.ZIP_DEFLATED)
        for k, im in enumerate(spec.images):
            z.writestr("Pictures/%08X%d.%s" % (spec.seed & 0xFFFFFFFF, k, "jpg" if im["ext"] == "jpeg" else im["ext"]),
                       im["data"], compress_type=zipfile.ZIP_STORED)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--big", action="store_true")
    ap.add_argument("--prefix", default="g")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for seed in range(a.first, a.first + a.count):
        spec = make_spec(seed * 7919 + (1 if a.big else 0), big=a.big)
        base = os.path.join(a.out, "%s%04d" % (a.prefix, seed))
        r = random.Random(seed * 31 + 5)
        xw_suffix = "-xw.xlsm" if spec.vba else "-xw.xlsx"
        for suffix, fn in ((xw_suffix, write_xlsxwriter), ("-op.xlsx", write_openpyxl), ("-xlwt.xls", write_xlwt)):
            try:
                fn(spec, base + suffix)
            except Exception as e:  # a writer refusing a spec is fine; skip that file
                print("skip", base + suffix, type(e).__name__, str(e)[:120])
                if os.path.exists(base + suffix):
                    os.remove(base + suffix)
        import biffgen
        raw8 = lambda sp, path, rr: biffgen.write_biff(sp, path, rr, 8)  # noqa: E731
        raw5 = lambda sp, path, rr: biffgen.write_biff(sp, path, rr, 5)  # noqa: E731
        for suffix, fn in (("-raw.xlsm" if spec.vba else "-raw.xlsx", raw_xlsx), ("-b12.xlsb", raw_xlsb), ("-b12b.xlsb", raw_xlsb),
                           ("-raw.ods", raw_ods), ("-raw8.xls", raw8), ("-raw5.xls", raw5)):
            try:
                fn(spec, base + suffix, r)
            except Exception as e:
                print("skip", base + suffix, type(e).__name__, str(e)[:120])
                if os.path.exists(base + suffix):
                    os.remove(base + suffix)


if __name__ == "__main__":
    main()
