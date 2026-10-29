"""extras.py: pictures, VBA projects, tables, pivot caches, hyperlinks and document properties
for the workbook generator (wbgen.py). Pure Python except JPEG, which uses Pillow when present.
"""
import io
import random
import struct
import zlib

# ---------------------------------------------------------------- images


def png_bytes(w, h, r):
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            row += bytes([(x * 7 + r.randint(0, 40)) & 255, (y * 5 + r.randint(0, 40)) & 255, r.randint(0, 255)])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def bmp_bytes(w, h, r):
    rowlen = (w * 3 + 3) & ~3
    pix = bytearray()
    for y in range(h):
        row = bytearray(r.randint(0, 255) for _ in range(w * 3))
        row += b"\x00" * (rowlen - len(row))
        pix += row
    hdr = struct.pack("<2sIHHI", b"BM", 54 + len(pix), 0, 0, 54)
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pix), 2835, 2835, 0, 0)
    return hdr + dib + bytes(pix)


def gif_bytes(w, h, r):
    # 2-colour GIF with an uncompressed-style LZW stream (clear codes keep the code size at 3 bits)
    pal = bytes([r.randint(0, 255) for _ in range(6)])
    data = bytearray()
    codes = []
    for i in range(w * h):
        if i % 2 == 0:
            codes.append(4)  # clear
        codes.append(r.randint(0, 1))
    codes.append(5)  # end
    acc = 0
    nbits = 0
    for c in codes:
        acc |= c << nbits
        nbits += 3
        while nbits >= 8:
            data.append(acc & 255)
            acc >>= 8
            nbits -= 8
    if nbits:
        data.append(acc & 255)
    blocks = bytearray()
    for i in range(0, len(data), 255):
        part = data[i:i + 255]
        blocks += bytes([len(part)]) + part
    return (b"GIF89a" + struct.pack("<HHBBB", w, h, 0x80, 0, 0) + pal
            + b"," + struct.pack("<HHHHB", 0, 0, w, h, 0) + b"\x02" + bytes(blocks) + b"\x00;")


def jpeg_bytes(w, h, r):
    try:
        from PIL import Image
    except ImportError:
        return None
    im = Image.new("RGB", (w, h))
    im.putdata([(r.randint(0, 255), r.randint(0, 255), r.randint(0, 255)) for _ in range(w * h)])
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=r.choice([50, 75, 90]))
    return buf.getvalue()


def random_image(r, kinds=("png", "png", "jpeg", "gif", "bmp")):
    """Return (ext, bytes)."""
    w, h = r.choice([(8, 8), (16, 12), (32, 20), (64, 40)])
    for _ in range(4):
        k = r.choice(kinds)
        if k == "png":
            return "png", png_bytes(w, h, r)
        if k == "bmp":
            return "bmp", bmp_bytes(w, h, r)
        if k == "gif":
            return "gif", gif_bytes(w, h, r)
        if k == "jpeg":
            b = jpeg_bytes(w, h, r)
            if b:
                return "jpeg", b
    return "png", png_bytes(w, h, r)


# ---------------------------------------------------------------- MS-OVBA compression


def ovba_compress(data):
    """MS-OVBA 2.4.1 compression with real copy tokens (greedy longest match)."""
    out = bytearray(b"\x01")
    pos = 0
    n = len(data)
    while pos < n:
        chunk_start = pos
        chunk_end = min(pos + 4096, n)
        body = bytearray()
        while pos < chunk_end:
            flag_pos = len(body)
            body.append(0)
            flags = 0
            for bit in range(8):
                if pos >= chunk_end:
                    break
                dlen = pos - chunk_start
                bit_count = max(4, (dlen - 1).bit_length()) if dlen > 1 else 4
                max_len = (0xFFFF >> bit_count) + 3
                best_len = 0
                best_off = 0
                if dlen > 0:
                    lo = max(chunk_start, pos - (1 << (16 - bit_count)))
                    for cand in range(pos - 1, lo - 1, -1):
                        ln = 0
                        while (ln < max_len and pos + ln < chunk_end and data[cand + ln] == data[pos + ln]):
                            ln += 1
                        if ln > best_len:
                            best_len, best_off = ln, pos - cand
                            if ln == max_len:
                                break
                if best_len >= 3:
                    token = ((best_off - 1) << (16 - bit_count)) | (best_len - 3)
                    body += struct.pack("<H", token)
                    flags |= 1 << bit
                    pos += best_len
                else:
                    body.append(data[pos])
                    pos += 1
            body[flag_pos] = flags
        if len(body) > 4096:  # incompressible: store raw
            raw = bytes(data[chunk_start:chunk_end]).ljust(4096, b"\x00")
            out += struct.pack("<H", 0x3000 | 0x0FFF) + raw
        else:
            out += struct.pack("<H", 0x8000 | 0x3000 | (len(body) + 2 - 3)) + body
    return bytes(out)


# ---------------------------------------------------------------- VBA project


def rec(rid, payload):
    return struct.pack("<HI", rid, len(payload)) + payload


VBA_WORDS = ["Total", "Count", "Value", "Range", "Sheet", "Report", "Update", "Calc", "Item", "Row"]


def vba_source(name, r, enc, document):
    lines = ['Attribute VB_Name = "%s"' % name]
    if document:
        lines += ["Attribute VB_Base = \"0{00020820-0000-0000-C000-000000000046}\"",
                  "Attribute VB_GlobalNameSpace = False", "Attribute VB_Creatable = False",
                  "Attribute VB_PredeclaredId = True", "Attribute VB_Exposed = True",
                  "Attribute VB_TemplateDerived = False", "Attribute VB_Customizable = True"]
    lines.append("Option Explicit")
    for k in range(r.randint(0, 4)):
        fn = r.choice(VBA_WORDS) + r.choice(VBA_WORDS) + str(k)
        lines.append("")
        lines.append("' " + r.choice(["Recalculate totals", "Fill the report", "Clear the sheet",
                                      "Комментарий", "Übertrag prüfen", "Résumé des ventes"]))
        lines.append("Public Sub %s()" % fn)
        lines.append("    Dim i As Long")
        lines.append("    For i = 1 To %d" % r.randint(2, 50))
        lines.append('        Cells(i, %d).Value = i * %d' % (r.randint(1, 9), r.randint(2, 9)))
        lines.append("    Next i")
        if r.random() < 0.5:
            lines.append('    MsgBox "%s"' % r.choice(["Done", "Fertig", "Terminé", "Готово"]))
        lines.append("End Sub")
    if r.random() < 0.3:
        lines += ["", "Function Twice(x As Double) As Double", "    Twice = x * 2", "End Function"]
    text = "\r\n".join(lines) + "\r\n"
    return text.encode(enc, "replace")


def build_vba_project(r, sheet_names):
    """Return (vbaProject.bin bytes as CFB streams list, codepage). Streams are (path tuple, bytes)."""
    cp, enc = r.choice([(1252, "cp1252"), (1252, "cp1252"), (1252, "cp1252"), (1251, "cp1251"), (1250, "cp1250")])
    modules = [("ThisWorkbook", True)] + [("Sheet%d" % (i + 1), True) for i in range(len(sheet_names))]
    for i in range(r.choice([0, 1, 1, 2, 3])):
        modules.append(("Module%d" % (i + 1), False))
    if r.random() < 0.2:
        modules.append(("Class%d" % r.randint(1, 9), False))
    d = bytearray()
    d += rec(0x0001, struct.pack("<I", 3 if r.random() < 0.7 else 1))        # PROJECTSYSKIND
    if r.random() < 0.5:
        d += rec(0x004A, struct.pack("<I", 0x0000006B))                      # PROJECTCOMPATVERSION
    d += rec(0x0002, struct.pack("<I", 0x0409))                              # PROJECTLCID
    d += rec(0x0014, struct.pack("<I", 0x0409))                              # PROJECTLCIDINVOKE
    d += rec(0x0003, struct.pack("<H", cp))                                  # PROJECTCODEPAGE
    pname = r.choice(["VBAProject", "Projekt", "MyMacros"])
    d += rec(0x0004, pname.encode(enc))                                     # PROJECTNAME
    doc = r.choice(["", "Report macros", "Totals"])
    d += rec(0x0005, doc.encode(enc)) + rec(0x0040, doc.encode("utf-16-le"))  # PROJECTDOCSTRING
    d += rec(0x0006, b"") + rec(0x003D, b"")                                 # PROJECTHELPFILEPATH
    d += rec(0x0007, struct.pack("<I", 0))                                   # PROJECTHELPCONTEXT
    d += rec(0x0008, struct.pack("<I", 0))                                   # PROJECTLIBFLAGS
    d += struct.pack("<HIIH", 0x0009, 4, 0x2A5E3F01, 0x0009)                 # PROJECTVERSION (12 bytes)
    d += rec(0x000C, b"") + rec(0x003C, b"")                                 # PROJECTCONSTANTS
    refs = []
    std = (b"*\\G{00020430-0000-0000-C000-000000000046}#2.0#0#C:\\Windows\\System32\\stdole2.tlb#OLE Automation")
    refs.append(("stdole", std))
    if r.random() < 0.5:
        refs.append(("Office", b"*\\G{2DF8D04C-5BFA-101B-BDE5-00AA0044DE52}#2.0#0#C:\\Program Files\\Common Files\\"
                               b"Microsoft Shared\\OFFICE16\\MSO.DLL#Microsoft Office 16.0 Object Library"))
    for name, libid in refs:
        nb = name.encode(enc)
        d += rec(0x0016, nb) + rec(0x003E, name.encode("utf-16-le"))     # REFERENCENAME
        body = struct.pack("<I", len(libid)) + libid + struct.pack("<IH", 0, 0)
        d += struct.pack("<HI", 0x000D, len(body)) + body                # REFERENCEREGISTERED
    if r.random() < 0.3:
        name = "Helpers"
        d += rec(0x0016, name.encode(enc)) + rec(0x003E, name.encode("utf-16-le"))
        absl = b"*\\CC:\\Macros\\helpers.xlam"
        rel = b"*\\Chelpers.xlam"
        body = struct.pack("<I", len(absl)) + absl + struct.pack("<I", len(rel)) + rel + struct.pack("<IH", 1, 0)
        d += struct.pack("<HI", 0x000E, len(body)) + body                # REFERENCEPROJECT
    d += struct.pack("<HIH", 0x000F, 2, len(modules))                     # PROJECTMODULES
    d += struct.pack("<HIH", 0x0013, 2, 0xFFFF)                           # PROJECTCOOKIE
    streams = []
    for name, document in modules:
        nb = name.encode(enc)
        d += rec(0x0019, nb)                                              # MODULENAME
        if r.random() < 0.9:
            d += rec(0x0047, name.encode("utf-16-le"))                    # MODULENAMEUNICODE
        d += rec(0x001A, nb) + rec(0x0032, name.encode("utf-16-le"))      # MODULESTREAMNAME
        d += rec(0x001C, b"") + rec(0x0048, b"")                          # MODULEDOCSTRING
        cache = bytes(r.randint(0, 255) for _ in range(r.choice([0, 0, 120, 333, 1000])))
        d += rec(0x0031, struct.pack("<I", len(cache)))                   # MODULEOFFSET
        d += rec(0x001E, struct.pack("<I", 0))                            # MODULEHELPCONTEXT
        d += rec(0x002C, struct.pack("<H", 0xFFFF))                       # MODULECOOKIE
        d += struct.pack("<HI", 0x0022 if document else 0x0021, 0)        # MODULETYPE
        if r.random() < 0.1:
            d += struct.pack("<HI", 0x0025, 0)                            # MODULEREADONLY
        if not document and r.random() < 0.2:
            d += struct.pack("<HI", 0x0028, 0)                            # MODULEPRIVATE
        d += struct.pack("<HI", 0x002B, 0)                                # terminator
        src = vba_source(name, r, enc, document)
        streams.append((("VBA", name), cache + ovba_compress(src)))
    d += struct.pack("<HI", 0x0010, 0)                                    # dir terminator
    streams.append((("VBA", "dir"), ovba_compress(bytes(d))))
    streams.append((("VBA", "_VBA_PROJECT"), b"\xcc\x61\xff\xff\x00\x03\x00"))
    proj = ["ID=\"{%08X-0000-0000-0000-000000000000}\"" % r.randint(0, 1 << 31)]
    for name, document in modules:
        proj.append(("Document=%s/&H00000000" % name) if document else ("Module=%s" % name))
    proj += ['Name="%s"' % pname, 'HelpContextID="0"', 'VersionCompatible32="393222000"', "", "[Host Extender Info]",
             "&H00000001={3832D640-CF90-11CF-8E43-00A0C911005A};VBE;&H00000000", ""]
    streams.append((("PROJECT",), "\r\n".join(proj).encode(enc, "replace")))
    return streams


def vba_project_bin(r, sheet_names):
    from biffgen import cfb_write_tree
    buf = io.BytesIO()
    cfb_write_tree(buf, build_vba_project(r, sheet_names))
    return buf.getvalue()


# ---------------------------------------------------------------- properties and hyperlinks

PROP_TEXT = ["Quarterly report", "Inventory & stock", "Plan <draft>", "Résumé", "Отчёт", "Q3 \"final\"",
             "Line one\nline two", "  padded  ", "数据表"]


def random_properties(r):
    p = {}
    for k in ("title", "subject", "author", "manager", "company", "category", "keywords", "comments", "status"):
        if r.random() < 0.5:
            p[k] = r.choice(PROP_TEXT)
    return p


def random_url(r):
    return r.choice(["https://example.com/report?id=%d&lang=en" % r.randint(1, 999),
                     "http://example.org/a b/%d" % r.randint(1, 99),
                     "mailto:someone@example.com",
                     "https://example.net/path#frag%d" % r.randint(1, 9),
                     "ftp://files.example.com/data.csv"])


# ---------------------------------------------------------------- hand-written SpreadsheetML parts

from xml.sax.saxutils import escape as _xesc  # noqa: E402

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_DRAWING = "application/vnd.openxmlformats-officedocument.drawing+xml"


def _attr(s):
    return _xesc(s, {'"': "&quot;"})


def _a1(row, col):
    s = ""
    c = col + 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s + str(row + 1)


class RawXlsxExtras:
    """Collects the extra parts of one hand-written xlsx package."""

    def __init__(self, spec, r, P):
        self.spec, self.r, self.P = spec, r, P
        self.parts = []          # (zip name, bytes or str)
        self.ct = []             # content type overrides / defaults
        self.wb_rels = []        # extra workbook relationships (id, type, target)
        self.wb_tail = ""        # extra workbook.xml children after definedNames
        self.media_n = 0
        self.drawing_n = 0
        self.table_n = 0
        self.pivot_n = 0
        self.exts = set()
        self.rich = []           # (ext, data) images placed in cells through rich values
        self.rich_sheet = r.randrange(len(spec.sheets)) if r.random() < 0.2 else None

    def media(self, ext, data):
        self.media_n += 1
        name = "xl/media/image%d.%s" % (self.media_n, ext)
        self.parts.append((name, data))
        self.exts.add(ext)
        return name

    def sheet_tail(self, si, sheet_path):
        """Return (xml after mergeCells, rels xml entries) for sheet si."""
        P, r, spec = self.P, self.r, self.spec
        sh = spec.sheets[si]
        tail = []
        rels = []
        links = [ln for ln in spec.links if ln["sheet"] == si]
        if links:
            tail.append("<%shyperlinks>" % P)
            for k, ln in enumerate(links):
                attrs = ' ref="%s"' % _a1(ln["row"], ln["col"])
                if ln["url"]:
                    rid = "rIdH%d" % k
                    rels.append('<Relationship Id="%s" Type="%s/hyperlink" Target="%s" TargetMode="External"/>'
                                % (rid, REL, _attr(ln["url"])))
                    attrs += ' r:id="%s"' % rid
                if ln["loc"]:
                    attrs += ' location="%s"' % _attr(ln["loc"])
                if ln["text"] and r.random() < 0.7:
                    attrs += ' display="%s"' % _attr(ln["text"])
                if ln["tip"]:
                    attrs += ' tooltip="%s"' % _attr(ln["tip"])
                tail.append("<%shyperlink%s/>" % (P, attrs))
            tail.append("</%shyperlinks>" % P)
        images = [im for im in spec.images if im["sheet"] == si]
        if images:
            self.drawing_n += 1
            dn = self.drawing_n
            drels = []
            anchors = []
            for k, im in enumerate(images):
                mname = self.media(im["ext"], im["data"])
                rid = "rIdI%d" % k
                drels.append('<Relationship Id="%s" Type="%s/image" Target="../media/%s"/>'
                             % (rid, REL, mname.split("/")[-1]))
                kind = r.choice(["twoCellAnchor", "twoCellAnchor", "oneCellAnchor", "absoluteAnchor"])
                pic = ('<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="%d" name="%s" descr="img"/><xdr:cNvPicPr/></xdr:nvPicPr>'
                       '<xdr:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                       '<xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/>'
                       % (k + 2, _attr(im["name"]), rid))
                frm = ("<xdr:from><xdr:col>%d</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>%d</xdr:row>"
                       "<xdr:rowOff>0</xdr:rowOff></xdr:from>" % (im["col"], im["row"]))
                if kind == "twoCellAnchor":
                    to = ("<xdr:to><xdr:col>%d</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>%d</xdr:row>"
                          "<xdr:rowOff>0</xdr:rowOff></xdr:to>" % (im["col"] + 2, im["row"] + 3))
                    anchors.append('<xdr:twoCellAnchor editAs="oneCell">%s%s%s</xdr:twoCellAnchor>' % (frm, to, pic))
                elif kind == "oneCellAnchor":
                    anchors.append('<xdr:oneCellAnchor>%s<xdr:ext cx="914400" cy="457200"/>%s</xdr:oneCellAnchor>' % (frm, pic))
                else:
                    anchors.append('<xdr:absoluteAnchor><xdr:pos x="%d" y="%d"/><xdr:ext cx="914400" cy="457200"/>%s'
                                   '</xdr:absoluteAnchor>' % (r.randint(0, 900000), r.randint(0, 900000), pic))
            dxml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<xdr:wsDr '
                    'xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="%s">%s</xdr:wsDr>'
                    % (REL, "".join(anchors)))
            self.parts.append(("xl/drawings/drawing%d.xml" % dn, dxml))
            self.parts.append(("xl/drawings/_rels/drawing%d.xml.rels" % dn,
                               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
                               'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>'
                               % "".join(drels)))
            self.ct.append('<Override PartName="/xl/drawings/drawing%d.xml" ContentType="%s"/>' % (dn, CT_DRAWING))
            rels.append('<Relationship Id="rIdD1" Type="%s/drawing" Target="../drawings/drawing%d.xml"/>' % (REL, dn))
            tail.append('<%sdrawing r:id="rIdD1"/>' % P)
        t = sh.table
        if t:
            self.table_n += 1
            tn = self.table_n
            hdr = r.choice([1, 1, 1, 0]) if not t["totals"] else 1
            r0 = t["r0"] if hdr else t["r0"] + 1
            r1 = t["r1"] + (1 if t["totals"] else 0)
            cols = "".join('<%stableColumn id="%d" name="%s"/>' % (P, k + 1, _attr(n)) for k, n in enumerate(t["columns"]))
            attrs = ' id="%d" name="%s" displayName="%s" ref="%s:%s"' % (tn, t["name"], _attr(t["name"]), _a1(r0, t["c0"]),
                                                                           _a1(r1, t["c1"]))
            if not hdr:
                attrs += ' headerRowCount="0"'
            if t["totals"]:
                attrs += ' totalsRowCount="1"'
            txml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<%stable %s%s><%sautoFilter ref="%s:%s"/>'
                    '<%stableColumns count="%d">%s</%stableColumns><%stableStyleInfo name="TableStyleMedium2" '
                    'showRowStripes="1"/></%stable>' % (P, 'xmlns%s="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                                                        % (":x" if P else ""), attrs, P, _a1(r0, t["c0"]), _a1(r1, t["c1"]),
                                                        P, len(t["columns"]), cols, P, P, P))
            self.parts.append(("xl/tables/table%d.xml" % tn, txml))
            self.ct.append('<Override PartName="/xl/tables/table%d.xml" ContentType="application/vnd.openxmlformats-'
                           'officedocument.spreadsheetml.table+xml"/>' % tn)
            target = r.choice(["../tables/table%d.xml" % tn, "/xl/tables/table%d.xml" % tn])
            rels.append('<Relationship Id="rIdT1" Type="%s/table" Target="%s"/>' % (REL, target))
            tail.append('<%stableParts count="1"><%stablePart r:id="rIdT1"/></%stableParts>' % (P, P, P))
        if sh.pivot and t:
            rels.append(self.pivot(si, sh))
        return "".join(tail), rels

    def pivot(self, si, sh):
        """Pivot table + cache built from the sheet's table block."""
        r = random.Random(sh.pivot["seed"])
        self.pivot_n += 1
        pn = self.pivot_n
        t = sh.table
        fields = []
        for k, name in enumerate(t["columns"]):
            vals = []
            for row in range(t["r0"] + 1, t["r1"] + 1):
                c = sh.cells.get((row, t["c0"] + k))
                vals.append(None if c is None or c["t"] == "f" else c)
            fields.append((name, vals))
        nrec = t["r1"] - t["r0"]
        defs = []
        recs_cols = []
        for name, vals in fields:
            shared = r.random() < 0.6
            items = []
            idx = {}
            col = []
            for c in vals:
                if c is None:
                    tag, v = "m", None
                elif c["t"] == "s":
                    tag, v = "s", c["v"]
                elif c["t"] == "b":
                    tag, v = "b", "1" if c["v"] else "0"
                elif c["t"] == "d":
                    tag, v = "n", repr(float(c["v"]))
                else:
                    fv = float(c["v"])
                    tag, v = "n", (str(int(fv)) if fv == int(fv) and abs(fv) < 1e15 else repr(fv))
                col.append((tag, v))
                if (tag, v) not in idx:
                    idx[(tag, v)] = len(items)
                    items.append((tag, v))
            if shared:
                inner = "".join('<%s v="%s"/>' % (tg, _attr(v)) if v is not None else "<m/>" for tg, v in items)
                defs.append('<cacheField name="%s" numFmtId="0"><sharedItems count="%d">%s</sharedItems></cacheField>'
                            % (_attr(name), len(items), inner))
                recs_cols.append([("x", idx[tv]) for tv in col])
            else:
                defs.append('<cacheField name="%s" numFmtId="0"><sharedItems/></cacheField>' % _attr(name))
                recs_cols.append(col)
        if r.random() < 0.3:
            defs.append('<cacheField name="Calc" numFmtId="0" formula="%s*2" databaseField="0"/>' % _attr(fields[0][0]))
        if r.random() < 0.3:
            defs.append('<cacheField name="Group1" numFmtId="0" databaseField="0"><fieldGroup base="0"><groupItems '
                        'count="1"><s v="grp"/></groupItems></fieldGroup></cacheField>')
        recs = []
        for i in range(nrec):
            cells = []
            for col in recs_cols:
                tg, v = col[i]
                if tg == "x":
                    cells.append('<x v="%d"/>' % v)
                elif v is None:
                    cells.append("<m/>")
                else:
                    cells.append('<%s v="%s"/>' % (tg, _attr(v)))
            recs.append("<r>%s</r>" % "".join(cells))
        ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="%s"' % REL
        ref = "%s:%s" % (_a1(t["r0"], t["c0"]), _a1(t["r1"], t["c1"]))
        cdef = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<pivotCacheDefinition %s r:id="rId1" '
                'recordCount="%d"><cacheSource type="worksheet"><worksheetSource ref="%s" sheet="%s"/></cacheSource>'
                '<cacheFields count="%d">%s</cacheFields></pivotCacheDefinition>'
                % (ns, nrec, ref, _attr(sh.name), len(defs), "".join(defs)))
        crec = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<pivotCacheRecords %s count="%d">%s'
                '</pivotCacheRecords>' % (ns, nrec, "".join(recs)))
        ptab = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<pivotTableDefinition '
                'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" name="%s" cacheId="%d" '
                'dataCaption="Values"><location ref="A1:B2" firstHeaderRow="1" firstDataRow="1" firstDataCol="1"/>'
                '</pivotTableDefinition>' % (_attr(sh.pivot["name"]), 10 + pn))
        rels_doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships '
                    'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>')
        self.parts.append(("xl/pivotCache/pivotCacheDefinition%d.xml" % pn, cdef))
        self.parts.append(("xl/pivotCache/pivotCacheRecords%d.xml" % pn, crec))
        rec_target = r.choice(["pivotCacheRecords%d.xml" % pn, "xl/pivotCache/pivotCacheRecords%d.xml" % pn])
        self.parts.append(("xl/pivotCache/_rels/pivotCacheDefinition%d.xml.rels" % pn, rels_doc % (
            '<Relationship Id="rId1" Type="%s/pivotCacheRecords" Target="%s"/>' % (REL, rec_target))))
        self.parts.append(("xl/pivotTables/pivotTable%d.xml" % pn, ptab))
        self.parts.append(("xl/pivotTables/_rels/pivotTable%d.xml.rels" % pn, rels_doc % (
            '<Relationship Id="rId1" Type="%s/pivotCacheDefinition" Target="../pivotCache/pivotCacheDefinition%d.xml"/>'
            % (REL, pn))))
        for nm, typ in (("pivotCache/pivotCacheDefinition%d" % pn, "pivotCacheDefinition"),
                        ("pivotCache/pivotCacheRecords%d" % pn, "pivotCacheRecords"),
                        ("pivotTables/pivotTable%d" % pn, "pivotTable")):
            self.ct.append('<Override PartName="/xl/%s.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                           'spreadsheetml.%s+xml"/>' % (nm, typ))
        self.wb_rels.append(("rIdPC%d" % pn, "pivotCacheDefinition", "pivotCache/pivotCacheDefinition%d.xml" % pn))
        self.wb_tail += '<pivotCache cacheId="%d" r:id="rIdPC%d"/>' % (10 + pn, pn)
        return '<Relationship Id="rIdP1" Type="%s/pivotTable" Target="../pivotTables/pivotTable%d.xml"/>' % (REL, pn)

    def rich_inject(self, si, xml):
        """Mark the first cells of sheet si as rich-value image cells (vm attribute)."""
        if si != self.rich_sheet:
            return xml
        P = self.P
        out = xml
        for k in range(self.r.choice([1, 2])):
            tag = '<%sc r="' % P
            pos = out.find(tag)
            n = 0
            while pos >= 0 and n < k:
                pos = out.find(tag, pos + 1)
                n += 1
            if pos < 0:
                break
            out = out[:pos] + '<%sc vm="%d" r="' % (P, k + 1) + out[pos + len(tag):]
            self.rich.append(random_image(self.r))
        return out

    def finish(self):
        """Workbook-level parts: rich-data images, stray media, properties, VBA."""
        spec, r = self.spec, self.r
        if r.random() < 0.15:  # an unanchored image in the media folder
            ext, data = random_image(r)
            self.media(ext, data)
        if spec.props or r.random() < 0.3:
            p = spec.props
            core = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
                    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']
            for k, tag in (("title", "dc:title"), ("subject", "dc:subject"), ("author", "dc:creator"),
                           ("keywords", "cp:keywords"), ("comments", "dc:description"), ("category", "cp:category"),
                           ("status", "cp:contentStatus")):
                if k in p:
                    core.append("<%s>%s</%s>" % (tag, _xesc(p[k]), tag))
            core.append("<cp:lastModifiedBy>%s</cp:lastModifiedBy>" % r.choice(["gen", "", "Ünïcode"]))
            core.append('<dcterms:created xsi:type="dcterms:W3CDTF">2024-0%d-1%dT08:00:00Z</dcterms:created>'
                        % (r.randint(1, 9), r.randint(0, 9)))
            core.append("<cp:revision>%d</cp:revision>" % r.randint(1, 20))
            core.append("</cp:coreProperties>")
            app = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns='
                   '"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">',
                   "<Application>%s</Application>" % r.choice(["Microsoft Excel", "gen"])]
            for k, tag in (("company", "Company"), ("manager", "Manager")):
                if k in p:
                    app.append("<%s>%s</%s>" % (tag, _xesc(p[k]), tag))
            app.append("<AppVersion>16.0300</AppVersion></Properties>")
            self.parts.append(("docProps/core.xml", "".join(core)))
            self.parts.append(("docProps/app.xml", "".join(app)))
        if self.rich:
            rels = []
            rv = []
            relx = []
            for k, (ext, data) in enumerate(self.rich):
                mname = self.media(ext, data)
                rels.append('<Relationship Id="rId%d" Type="%s/image" Target="../media/%s"/>' % (k + 1, REL, mname.split("/")[-1]))
                relx.append('<rel r:id="rId%d"/>' % (k + 1))
                rv.append('<rv s="0"><v>%d</v><v>5</v></rv>' % k)
            self.parts.append(("xl/richData/_rels/richValueRel.xml.rels",
                               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://'
                               'schemas.openxmlformats.org/package/2006/relationships">%s</Relationships>' % "".join(rels)))
            self.parts.append(("xl/richData/richValueRel.xml",
                               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<richValueRels xmlns="http://'
                               'schemas.microsoft.com/office/spreadsheetml/2022/richvaluerel" xmlns:r="%s">%s</richValueRels>'
                               % (REL, "".join(relx))))
            self.parts.append(("xl/richData/rdrichvalue.xml",
                               '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<rvData xmlns="http://schemas.'
                               'microsoft.com/office/spreadsheetml/2017/richdata" count="%d">%s</rvData>' % (len(rv), "".join(rv))))
        if spec.vba:
            self.parts.append(("xl/vbaProject.bin", vba_project_bin(random.Random(spec.vba_seed),
                                                                    [s.name for s in spec.sheets])))
            self.wb_rels.append(("rIdV1", "vbaProject", "vbaProject.bin"))
            self.ct.append('<Default Extension="bin" ContentType="application/vnd.ms-office.vbaProject"/>')
        for ext in sorted(self.exts):
            self.ct.append('<Default Extension="%s" ContentType="image/%s"/>' % (ext, ext))


def doc_props_parts(spec, r):
    """docProps/core.xml and app.xml contents, or None."""
    if not spec.props and r.random() >= 0.3:
        return None
    p = spec.props
    core = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">']
    for k, tag in (("title", "dc:title"), ("subject", "dc:subject"), ("author", "dc:creator"),
                   ("keywords", "cp:keywords"), ("comments", "dc:description"), ("category", "cp:category"),
                   ("status", "cp:contentStatus")):
        if k in p:
            core.append("<%s>%s</%s>" % (tag, _xesc(p[k]), tag))
    core.append("<cp:lastModifiedBy>%s</cp:lastModifiedBy>" % r.choice(["gen", "", "Ünïcode"]))
    core.append('<dcterms:created xsi:type="dcterms:W3CDTF">2024-0%d-1%dT08:00:00Z</dcterms:created>'
                % (r.randint(1, 9), r.randint(0, 9)))
    core.append("<cp:revision>%d</cp:revision>" % r.randint(1, 20))
    core.append("</cp:coreProperties>")
    app = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties xmlns='
           '"http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">',
           "<Application>%s</Application>" % r.choice(["Microsoft Excel", "gen"])]
    for k, tag in (("company", "Company"), ("manager", "Manager")):
        if k in p:
            app.append("<%s>%s</%s>" % (tag, _xesc(p[k]), tag))
    app.append("<AppVersion>16.0300</AppVersion></Properties>")
    return "".join(core), "".join(app)


def art_rec(ver, inst, typ, body):
    return struct.pack("<HHI", (inst << 4) | ver, typ, len(body)) + body


def msodrawinggroup(images, r):
    """OfficeArtDggContainer with a BStore of FBSE+blip entries for the given (ext, data) images."""
    bses = []
    for ext, data in images:
        uid = bytes(r.randint(0, 255) for _ in range(16))
        if ext == "png" or ext == "gif":
            if ext == "gif":
                data = png_bytes(8, 8, r)
            blip = art_rec(0, 0x6E0, 0xF01E, uid + b"\xff" + data)
            bt = 6
        elif ext == "jpeg":
            blip = art_rec(0, 0x46A, 0xF01D, uid + b"\xff" + data)
            bt = 5
        else:  # bmp -> DIB without the file header
            blip = art_rec(0, 0x7A8, 0xF01F, uid + b"\xff" + data[14:])
            bt = 7
        name = b""
        fbse = struct.pack("<BB", bt, bt) + uid + struct.pack("<HIIIBBBB", 0xFF, len(blip), 1, 0, 0, len(name), 0, 0) + name + blip
        bses.append(art_rec(2, bt, 0xF007, fbse))
    bstore = art_rec(0xF, len(bses), 0xF001, b"".join(bses))
    fdgg = art_rec(0, 0, 0xF006, struct.pack("<IIII", 1026, 2, 2, 1) + struct.pack("<II", 1, 2))
    return art_rec(0xF, 0, 0xF000, fdgg + bstore)
