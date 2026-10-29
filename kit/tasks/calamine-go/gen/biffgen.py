"""biffgen.py: hand-written BIFF5 and BIFF8 .xls files (with a Compound File Binary container).

Used by wbgen.py for the -raw5.xls and -raw8.xls variants. Follows [MS-XLS] and [MS-CFB] record
layouts; BIFF5 parts follow the Excel 5/95 layouts described in the OpenOffice.org Excel file format
documentation.
"""
import random
import struct

ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


# ---------------------------------------------------------------- CFB writer

def cfb_write(path, streams):
    """streams: list of (name, bytes) at the root."""
    with open(path, "wb") as f:
        cfb_write_tree(f, [((n,), d) for n, d in streams])


def cfb_write_tree(f, streams):
    """streams: list of (path tuple, bytes); storages are created for path prefixes.
    Version 3, 512-byte sectors, 64-byte mini sectors, 4096-byte mini cutoff."""
    sec = 512
    # directory model
    nodes = [{"name": "Root Entry", "type": 5, "children": [], "data": None}]
    index = {(): 0}
    for path, data in streams:
        for k in range(1, len(path)):
            pre = path[:k]
            if pre not in index:
                index[pre] = len(nodes)
                nodes.append({"name": pre[-1], "type": 1, "children": [], "data": None})
                nodes[index[pre[:-1]]]["children"].append(index[pre])
        index[path] = len(nodes)
        nodes.append({"name": path[-1], "type": 2, "children": [], "data": data})
        nodes[index[path[:-1]]]["children"].append(index[path])
    # mini stream
    ministream = bytearray()
    minifat = []
    for nd in nodes:
        if nd["type"] == 2 and len(nd["data"]) < 4096:
            data = nd["data"]
            nsec = (len(data) + 63) // 64 or 1
            start = len(ministream) // 64
            nd["start"] = start
            ministream += data + b"\x00" * (nsec * 64 - len(data))
            for i in range(nsec):
                minifat.append(start + i + 1 if i < nsec - 1 else ENDOFCHAIN)
    sectors = []
    fat = []

    def alloc(data):
        n = (len(data) + sec - 1) // sec or 1
        first = len(sectors)
        padded = bytes(data) + b"\x00" * (n * sec - len(data))
        for i in range(n):
            sectors.append(padded[i * sec:(i + 1) * sec])
            fat.append(first + i + 1 if i < n - 1 else ENDOFCHAIN)
        return first
    for nd in nodes:
        if nd["type"] == 2 and len(nd["data"]) >= 4096:
            nd["start"] = alloc(nd["data"])
    ms_start = alloc(ministream) if ministream else ENDOFCHAIN
    mf_bytes = b"".join(struct.pack("<I", x) for x in minifat)
    if mf_bytes:
        mf_bytes += struct.pack("<I", FREESECT) * ((sec - len(mf_bytes) % sec) % sec // 4)
    mf_start = alloc(mf_bytes) if minifat else ENDOFCHAIN
    mf_count = (len(mf_bytes) + sec - 1) // sec if minifat else 0

    def key(i):
        n = nodes[i]["name"]
        return (len(n), n.upper())
    entries = []
    right = {}
    child = {}
    for i, nd in enumerate(nodes):
        kids = sorted(nd["children"], key=key)
        if kids:
            child[i] = kids[0]
            for a, b in zip(kids, kids[1:]):
                right[a] = b
    for i, nd in enumerate(nodes):
        u = nd["name"].encode("utf-16-le") + b"\x00\x00"
        e = u + b"\x00" * (64 - len(u))
        e += struct.pack("<HBB", len(u), nd["type"], 1)
        e += struct.pack("<III", NOSTREAM, right.get(i, NOSTREAM), child.get(i, NOSTREAM))
        e += b"\x00" * 16 + b"\x00" * 4 + b"\x00" * 16
        if nd["type"] == 5:
            e += struct.pack("<II", ms_start, len(ministream))
        elif nd["type"] == 2:
            e += struct.pack("<II", nd["start"], len(nd["data"]))
        else:
            e += struct.pack("<II", 0, 0)
        e += b"\x00" * 4
        assert len(e) == 128
        entries.append(e)
    while len(entries) % 4:
        entries.append(b"\x00" * 64 + struct.pack("<HBB", 0, 0, 0) + struct.pack("<III", NOSTREAM, NOSTREAM, NOSTREAM)
                       + b"\x00" * 36 + struct.pack("<II", 0, 0) + b"\x00" * 4)
    dir_start = alloc(b"".join(entries))
    nfat = 1
    while len(sectors) + nfat > nfat * (sec // 4):
        nfat += 1
    fat_start = len(sectors)
    for i in range(nfat):
        fat.append(FATSECT)
        sectors.append(None)
    fat += [FREESECT] * (nfat * (sec // 4) - len(fat))
    fat_bytes = b"".join(struct.pack("<I", x) for x in fat)
    for i in range(nfat):
        sectors[fat_start + i] = fat_bytes[i * sec:(i + 1) * sec]
    assert nfat <= 109
    hdr = bytearray(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1")
    hdr += b"\x00" * 16
    hdr += struct.pack("<HHHHH", 0x003E, 0x0003, 0xFFFE, 9, 6)
    hdr += b"\x00" * 6
    hdr += struct.pack("<I", 0)
    hdr += struct.pack("<I", nfat)
    hdr += struct.pack("<I", dir_start)
    hdr += struct.pack("<I", 0)
    hdr += struct.pack("<I", 4096)
    hdr += struct.pack("<I", mf_start)
    hdr += struct.pack("<I", mf_count)
    hdr += struct.pack("<I", ENDOFCHAIN)
    hdr += struct.pack("<I", 0)
    difat = [fat_start + i for i in range(nfat)] + [FREESECT] * (109 - nfat)
    hdr += b"".join(struct.pack("<I", x) for x in difat)
    assert len(hdr) == 512
    f.write(bytes(hdr))
    for s_ in sectors:
        f.write(s_)


# ---------------------------------------------------------------- BIFF records

def rec(typ, body=b""):
    return struct.pack("<HH", typ, len(body)) + body


MAXREC = 8224


def u16str8(s):
    """XLUnicodeString (BIFF8): cch(2) flags(1) chars."""
    try:
        b = s.encode("latin-1")
        return struct.pack("<HB", len(s), 0) + b
    except UnicodeEncodeError:
        u = s.encode("utf-16-le")
        return struct.pack("<HB", len(u) // 2, 1) + u


def short8(s):
    """ShortXLUnicodeString (BIFF8): cch(1) flags(1) chars."""
    try:
        b = s.encode("latin-1")
        return struct.pack("<BB", len(s), 0) + b
    except UnicodeEncodeError:
        u = s.encode("utf-16-le")
        return struct.pack("<BB", len(u) // 2, 1) + u


def nocch8(s):
    try:
        return b"\x00" + s.encode("latin-1"), len(s)
    except UnicodeEncodeError:
        u = s.encode("utf-16-le")
        return b"\x01" + u, len(u) // 2


def sst_records(strings):
    """SST + CONTINUE records, splitting character data with a fresh flags byte."""
    recs = []
    cur = bytearray(struct.pack("<II", len(strings), len(strings)))
    for s in strings:
        try:
            raw = s.encode("latin-1")
            hi = 0
            unit = 1
        except UnicodeEncodeError:
            raw = s.encode("utf-16-le")
            hi = 1
            unit = 2
        nchar = len(raw) // unit
        if len(cur) + 3 + unit > MAXREC:  # never split a string header
            recs.append(bytes(cur))
            cur = bytearray()
        cur += struct.pack("<HB", nchar, hi)
        pos = 0
        while pos < len(raw):
            room = (MAXREC - len(cur)) // unit * unit
            if room <= 0:
                recs.append(bytes(cur))
                cur = bytearray(bytes([hi]))
                continue
            take = raw[pos:pos + room]
            cur += take
            pos += len(take)
            if pos < len(raw):
                recs.append(bytes(cur))
                cur = bytearray(bytes([hi]))
    recs.append(bytes(cur))
    out = rec(0x00FC, recs[0])
    for r in recs[1:]:
        out += rec(0x003C, r)
    return out


def rk_encode(v):
    """Return the RK value for v, or None if it cannot be stored exactly."""
    if v == int(v) and -(1 << 29) <= v < (1 << 29):
        return ((int(v) << 2) | 2) & 0xFFFFFFFF
    x = v * 100
    if x == int(x) and -(1 << 29) <= x < (1 << 29) and abs(int(x) / 100.0 - v) == 0:
        return ((int(x) << 2) | 3) & 0xFFFFFFFF
    b = struct.pack("<d", v)
    if b[:4] == b"\x00\x00\x00\x00":
        hi = struct.unpack("<I", b[4:])[0]
        if hi & 3 == 0:
            return hi
    return None


ERRS = {"#NULL!": 0x00, "#DIV/0!": 0x07, "#VALUE!": 0x0F, "#REF!": 0x17, "#NAME?": 0x1D, "#NUM!": 0x24, "#N/A": 0x2A}


def rgce(n, biff, sheet_index, enc):
    k, a = n.kind, n.args
    from wbgen import FUNCS, FTAB_ARGC
    if k == "num":
        return b"\x1f" + struct.pack("<d", a[0])
    if k == "int":
        return b"\x1e" + struct.pack("<H", a[0])
    if k == "str":
        if biff == 8:
            body, cch = nocch8(a[0][:255])
            return b"\x17" + bytes([cch]) + body
        b = a[0][:255].encode(enc, "replace")
        return b"\x17" + bytes([len(b)]) + b
    if k == "bool":
        return b"\x1d" + bytes([1 if a[0] else 0])
    if k == "ref":
        sheet, row, col, ar, ac = a
        if biff == 8:
            colw = (col & 0x3FFF) | (0 if ar else 0x4000) | (0 if ac else 0x8000)
            if sheet:
                return b"\x3a" + struct.pack("<HHH", sheet_index[sheet], row, colw)
            return b"\x44" + struct.pack("<HH", row, colw)
        roww = (row & 0x3FFF) | (0 if ar else 0x8000) | (0 if ac else 0x4000)
        if sheet:
            i = sheet_index[sheet]
            return b"\x3a" + struct.pack("<h", -1) + b"\x00" * 8 + struct.pack("<hhH", i, i, roww) + bytes([col & 0xFF])
        return b"\x44" + struct.pack("<H", roww) + bytes([col & 0xFF])
    if k == "area":
        sheet, r1, c1, r2, c2, absf = a
        if biff == 8:
            fl = 0 if absf else 0xC000
            if sheet:
                return b"\x3b" + struct.pack("<HHHHH", sheet_index[sheet], r1, r2, c1 | fl, c2 | fl)
            return b"\x25" + struct.pack("<HHHH", r1, r2, c1 | fl, c2 | fl)
        fl = 0 if absf else 0xC000
        if sheet:
            i = sheet_index[sheet]
            return b"\x3b" + struct.pack("<h", -1) + b"\x00" * 8 + struct.pack("<hhHH", i, i, r1 | fl, r2 | fl) + bytes([c1 & 0xFF, c2 & 0xFF])
        return b"\x25" + struct.pack("<HH", r1 | fl, r2 | fl) + bytes([c1 & 0xFF, c2 & 0xFF])
    if k == "func":
        name, args = a
        idx, fixed = FUNCS[name]
        body = b"".join(rgce(x, biff, sheet_index, enc) for x in args)
        if name == "SUM" and len(args) == 1 and biff == 8:
            return body + b"\x19\x10\x00\x00"  # tAttrSum
        if fixed is not None and FTAB_ARGC.get(idx) == len(args):
            return body + b"\x41" + struct.pack("<H", idx)
        return body + b"\x42" + bytes([len(args)]) + struct.pack("<H", idx)
    if k == "bin":
        from wbgen import BINOPS
        return rgce(a[1], biff, sheet_index, enc) + rgce(a[2], biff, sheet_index, enc) + bytes([BINOPS[a[0]]])
    if k == "neg":
        return rgce(a[0], biff, sheet_index, enc) + b"\x13"
    if k == "pct":
        return rgce(a[0], biff, sheet_index, enc) + b"\x14"
    if k == "paren":
        return rgce(a[0], biff, sheet_index, enc) + b"\x15"
    raise ValueError(k)


def has_3d(n):
    if n.kind in ("ref", "area"):
        return n.args[0] is not None
    for a in n.args:
        if isinstance(a, list):
            if any(has_3d(x) for x in a):
                return True
        elif hasattr(a, "kind") and has_3d(a):
            return True
    return False


def has_kind(n, kind):
    if n.kind == kind:
        return True
    for a in n.args:
        if isinstance(a, list):
            if any(has_kind(x, kind) for x in a):
                return True
        elif hasattr(a, "kind") and has_kind(a, kind):
            return True
    return False


def write_biff(spec, path, r, biff):
    from wbgen import cached, fmt_code
    if biff == 5:
        cp, enc = r.choice([(1252, "cp1252"), (1252, "cp1252"), (1251, "cp1251"), (1250, "cp1250")])
    else:
        cp, enc = (1200, None) if r.random() < 0.85 else (1252, "cp1252")
    use_sst = biff == 8 and r.random() < 0.85
    use_mulrk = r.random() < 0.6

    def bstr(s, n2=True):
        b = s.encode(enc or "cp1252", "replace")[:255 if not n2 else 32767]
        return (struct.pack("<H", len(b)) if n2 else bytes([len(b)])) + b
    # formats and xfs
    fmts = {}
    xfs = [0]

    def xf_for(code):
        if code is None:
            return 15
        if isinstance(code, int):
            fid = code
        else:
            if code not in fmts:
                fmts[code] = 164 + len(fmts)
            fid = fmts[code]
        if fid not in xfs:
            xfs.append(fid)
        return 15 + xfs.index(fid)
    sheet_index = {sh.name: i for i, sh in enumerate(spec.sheets)}
    sst = []
    sidx = {}
    # sheet substreams (cell records first, so formats/strings are known)
    subs = []
    for sh in spec.sheets:
        body = bytearray()
        if biff == 8:
            body += rec(0x0809, struct.pack("<HHHHII", 0x0600, 0x0010, 0x0DBB, 0x07CC, 0, 0x06))
        else:
            body += rec(0x0809, struct.pack("<HHHH", 0x0500, 0x0010, 0x0DBB, 0x07CC))
        keys = sorted(k for k in sh.cells if k[0] < 65536 and k[1] < 256)
        if keys:
            r0 = min(k[0] for k in keys)
            r1 = max(k[0] for k in keys) + 1
            c0 = min(k[1] for k in keys)
            c1 = max(k[1] for k in keys) + 1
        else:
            r0 = r1 = c0 = c1 = 0
        if biff == 8:
            body += rec(0x0200, struct.pack("<IIHHH", r0, r1, c0, c1, 0))
        else:
            body += rec(0x0200, struct.pack("<HHHHH", r0, r1, c0, c1, 0))
        rows = {}
        for k in keys:
            rows.setdefault(k[0], []).append(k[1])
        for row in sorted(rows):
            cols = sorted(rows[row])
            i = 0
            while i < len(cols):
                c = cols[i]
                cell = sh.cells[(row, c)]
                xf = xf_for(fmt_code(cell.get("fmt")))
                t = cell["t"]
                # MULRK runs of adjacent RK-able numbers
                if use_mulrk and t in ("n", "d") and rk_encode(float(cell["v"])) is not None:
                    run = [c]
                    j = i + 1
                    while j < len(cols) and cols[j] == run[-1] + 1:
                        nc = sh.cells[(row, cols[j])]
                        if nc["t"] in ("n", "d") and rk_encode(float(nc["v"])) is not None:
                            run.append(cols[j])
                            j += 1
                        else:
                            break
                    if len(run) > 1:
                        b = struct.pack("<HH", row, run[0])
                        for cc in run:
                            nc = sh.cells[(row, cc)]
                            b += struct.pack("<HI", xf_for(fmt_code(nc.get("fmt"))), rk_encode(float(nc["v"])))
                        b += struct.pack("<H", run[-1])
                        body += rec(0x00BD, b)
                        i = j
                        continue
                if t == "s":
                    v = cell["v"]
                    if use_sst and r.random() < 0.95:
                        if v not in sidx:
                            sidx[v] = len(sst)
                            sst.append(v)
                        body += rec(0x00FD, struct.pack("<HHHI", row, c, xf, sidx[v]))
                    elif biff == 8:
                        body += rec(0x0204, struct.pack("<HHH", row, c, xf) + u16str8(v[:2000]))
                    else:
                        body += rec(0x0204, struct.pack("<HHH", row, c, xf) + bstr(v[:255]))
                elif t in ("n", "d"):
                    v = float(cell["v"])
                    rk = rk_encode(v)
                    if rk is not None and r.random() < 0.7:
                        body += rec(0x027E, struct.pack("<HHHI", row, c, xf, rk))
                    else:
                        body += rec(0x0203, struct.pack("<HHHd", row, c, xf, v))
                elif t == "b":
                    body += rec(0x0205, struct.pack("<HHHBB", row, c, xf, 1 if cell["v"] else 0, 0))
                elif t == "f":
                    v = cached(cell, sh, spec)
                    if biff == 5 and (has_3d(cell["f"]) or has_kind(cell["f"], "str")) and r.random() < 0.8:
                        # keep most BIFF5 books free of 3D refs and string literals: store the value instead
                        if isinstance(v, tuple):
                            body += rec(0x0205, struct.pack("<HHHBB", row, c, xf, ERRS.get(v[0], 0x0F), 1))
                        elif isinstance(v, bool):
                            body += rec(0x0205, struct.pack("<HHHBB", row, c, xf, int(v), 0))
                        elif isinstance(v, str):
                            body += rec(0x0204, struct.pack("<HHH", row, c, xf) + bstr(v[:255]))
                        else:
                            body += rec(0x0203, struct.pack("<HHHd", row, c, xf, float(v)))
                        i += 1
                        continue
                    try:
                        rg = rgce(cell["f"], biff, sheet_index, enc or "cp1252")
                    except Exception:
                        i += 1
                        continue
                    if isinstance(v, tuple):
                        val = struct.pack("<BBBBHH", 2, 0, ERRS.get(v[0], 0x0F), 0, 0, 0xFFFF)
                    elif isinstance(v, bool):
                        val = struct.pack("<BBBBHH", 1, 0, int(v), 0, 0, 0xFFFF)
                    elif isinstance(v, str):
                        val = struct.pack("<BBBBHH", 0 if v else 3, 0, 0, 0, 0, 0xFFFF)
                    else:
                        val = struct.pack("<d", float(v))
                    body += rec(0x0006, struct.pack("<HHH", row, c, xf) + val + struct.pack("<HIH", 0, 0, len(rg)) + rg)
                    if isinstance(v, str) and v:
                        if biff == 8:
                            body += rec(0x0207, u16str8(v[:2000]))
                        else:
                            body += rec(0x0207, bstr(v[:255]))
                i += 1
        if biff == 8 and sh.merges:
            body += rec(0x00E5, struct.pack("<H", len(sh.merges)) + b"".join(
                struct.pack("<HHHH", a, c_, b_, d) for (a, b_, c_, d) in sh.merges))
        body += rec(0x000A)
        subs.append(bytes(body))
    # globals
    def globals_stream(offsets):
        g = bytearray()
        if biff == 8:
            g += rec(0x0809, struct.pack("<HHHHII", 0x0600, 0x0005, 0x0DBB, 0x07CC, 0, 0x06))
        else:
            g += rec(0x0809, struct.pack("<HHHH", 0x0500, 0x0005, 0x0DBB, 0x07CC))
        g += rec(0x0042, struct.pack("<H", cp))
        g += rec(0x0022, struct.pack("<H", 1 if spec.is1904 else 0))
        # fonts are not read by the reader but keep the stream realistic
        for _ in range(4):
            if biff == 8:
                g += rec(0x0031, struct.pack("<HHHHHBBBB", 200, 0, 0x7FFF, 400, 0, 0, 0, 0, 0) + short8("Arial"))
            else:
                g += rec(0x0031, struct.pack("<HHHHHBBBB", 200, 0, 0x7FFF, 400, 0, 0, 0, 0, 0) + bytes([5]) + b"Arial")
        for code, fid in fmts.items():
            if biff == 8:
                g += rec(0x041E, struct.pack("<H", fid) + u16str8(code))
            else:
                g += rec(0x041E, struct.pack("<H", fid) + bytes([len(code)]) + code.encode("cp1252", "replace"))
        # 15 style XFs + 1 default cell XF, then one cell XF per number format
        for i in range(16):
            if biff == 8:
                g += rec(0x00E0, struct.pack("<HHHBBBBIIH", 0, 0, 0xFFF5 if i < 15 else 0x0001, 0x20, 0, 0, 0, 0, 0, 0x20C0))
            else:
                g += rec(0x00E0, struct.pack("<HHHHHHHH", 0, 0, 0xFFF5 if i < 15 else 0x0001, 0x20, 0x20C0, 0, 0, 0))
        for fid in xfs[1:]:
            if biff == 8:
                g += rec(0x00E0, struct.pack("<HHHBBBBIIH", 0, fid, 0x0001, 0x20, 0, 0, 0, 0, 0, 0x20C0))
            else:
                g += rec(0x00E0, struct.pack("<HHHHHHHH", 0, fid, 0x0001, 0x20, 0x20C0, 0, 0, 0))
        for i, sh in enumerate(spec.sheets):
            hs = {"visible": 0, "hidden": 1, "veryHidden": 2}[sh.state]
            if biff == 8:
                g += rec(0x0085, struct.pack("<IBB", offsets[i], hs, 0) + short8(sh.name[:31]))
            else:
                nb = sh.name[:31].encode(enc, "replace")
                g += rec(0x0085, struct.pack("<IBB", offsets[i], hs, 0) + bytes([len(nb)]) + nb)
        if biff == 8:
            n = len(spec.sheets)
            g += rec(0x01AE, struct.pack("<HH", n, 0x0401))  # SupBook (self)
            g += rec(0x0017, struct.pack("<H", n) + b"".join(struct.pack("<Hhh", 0, i, i) for i in range(n)))
        for (name, sheet, val) in spec.names:
            if sheet is None:
                rg = b"\x1f" + struct.pack("<d", float(val))
                itab = 0
            else:
                rr1, cc1, rr2, cc2 = val
                si = sheet_index[sheet]
                if biff == 8:
                    rg = b"\x3b" + struct.pack("<HHHHH", si, rr1, rr2, cc1, cc2)
                else:
                    rg = b"\x3b" + struct.pack("<h", -1) + b"\x00" * 8 + struct.pack("<hhHH", si, si, rr1, rr2) + bytes([cc1 & 0xFF, cc2 & 0xFF])
                itab = 0
            if biff == 8:
                nb, cch = nocch8(name)
            else:
                nb = name.encode("cp1252")
                cch = len(nb)
            g += rec(0x0018, struct.pack("<HBBHHHBBBB", 0, 0, cch, len(rg), 0, itab, 0, 0, 0, 0) + nb + rg)
        if sst:
            g += sst_records(sst)
        if biff == 8 and spec.images:
            from extras import msodrawinggroup
            dg = msodrawinggroup([(im["ext"], im["data"]) for im in spec.images], random.Random(spec.vba_seed + 7))
            g += rec(0x00EB, dg[:MAXREC])
            for k in range(MAXREC, len(dg), MAXREC):
                g += rec(0x003C, dg[k:k + MAXREC])
        g += rec(0x000A)
        return bytes(g)
    g0 = globals_stream([0] * len(spec.sheets))
    offs = []
    pos = len(g0)
    for s in subs:
        offs.append(pos)
        pos += len(s)
    g = globals_stream(offs)
    assert len(g) == len(g0)
    stream = g + b"".join(subs)
    streams = [(("Book" if biff == 5 else "Workbook",), stream)]
    if biff == 8 and spec.vba:
        from extras import build_vba_project
        streams += [(("_VBA_PROJECT_CUR",) + p, d) for p, d in
                    build_vba_project(random.Random(spec.vba_seed), [s.name for s in spec.sheets])]
    with open(path, "wb") as f:
        cfb_write_tree(f, streams)
