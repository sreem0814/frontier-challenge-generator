"""gen/cases_gen.py: candidate cases for the probe (library + client) and the server (wire).

Each case: {"id", "kind": "probe"|"wire", "fam", "nom" (nominal area), ...}
  probe: "op", "args" (list of bytes)
  wire:  "send" (bytes)
Families group a valid base with its mutants (an error result in a family only scores next to a passing
non-error result of the same family; see compute_reward.py).
"""
import gzip
import random
import zlib

CRLF = b"\r\n"


class Gen:
    def __init__(self, seed, prefix):
        self.r = random.Random(seed)
        self.prefix = prefix
        self.cases = []
        self.n = 0
        self.fam = 0

    def new_fam(self):
        self.fam += 1
        return f"{self.prefix}f{self.fam}"

    def probe(self, fam, nom, op, *args):
        self.n += 1
        a = [x if isinstance(x, bytes) else str(x).encode() for x in args]
        self.cases.append({"id": f"{self.prefix}{self.n}", "kind": "probe", "fam": fam, "nom": nom, "op": op,
                           "args": a})

    def wire(self, fam, nom, send):
        self.n += 1
        self.cases.append({"id": f"{self.prefix}{self.n}", "kind": "wire", "fam": fam, "nom": nom, "send": send})

    # ---- random helpers
    def ch(self, seq):
        return self.r.choice(seq)

    def word(self, alpha=b"abcdefghijklmnopqrstuvwxyz0123456789", lo=1, hi=8):
        return bytes(self.r.choice(alpha) for _ in range(self.r.randint(lo, hi)))

    def mutate(self, b, k=1):
        """byte-level mutation of b (insert / delete / replace / duplicate a slice)"""
        b = bytearray(b)
        for _ in range(k):
            op = self.r.randrange(5)
            i = self.r.randrange(len(b) + 1)
            if op == 0:
                b[i:i] = bytes([self.ch(b" \t\r\n:;,=\"%-+/?#&\x00\x7f\x80\xff0aZ")])
            elif op == 1 and b:
                del b[min(i, len(b) - 1)]
            elif op == 2 and b:
                b[min(i, len(b) - 1)] = self.ch(b" \t\r\n:;,=\"%-+/?#&\x00\x7f\x80\xff0aZ")
            elif op == 3 and b:
                j = min(len(b), i + self.r.randint(1, 6))
                b[i:i] = b[i:j]
            else:
                b[i:i] = self.ch([b"\r\n", b"  ", b"\t", b"%", b"%2", b"%zz", b"\\", b"\"", b";", b","])
        return bytes(b)


TOKCH = b"!#$%&'*+-.^_`|~abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
HNAMES = [b"Host", b"User-Agent", b"Accept", b"X-Custom", b"X-A", b"Content-Type", b"Cookie", b"Cache-Control",
          b"X-Forwarded-For", b"Authorization", b"If-None-Match", b"Referer", b"x-lower", b"X_Under"]
VALS = [b"value", b"a b c", b"", b"  padded  ", b"\"quoted\"", b"text/html; charset=utf-8", b"\xc3\xa9t\xc3\xa9",
        b"1, 2, 3", b"a=b; c=d", b"*/*", b"\ttabbed\t", b"x" * 40]


def hdr_line(g):
    n = g.ch(HNAMES) if g.r.random() < 0.6 else g.word(TOKCH, 1, 12)
    v = g.ch(VALS) if g.r.random() < 0.6 else g.word(b"abc XYZ09-_.,;=/\"", 0, 20)
    sep = g.ch([b": ", b":", b":  ", b":\t", b": "])
    return n + sep + v


# ------------------------------------------------------------------------------------------------- H
def gen_H(g, scale):
    for _ in range(40 * scale):
        fam = g.new_fam()
        base = hdr_line(g)
        g.probe(fam, "H", "hdr", base)
        for _ in range(3):
            g.probe(fam, "H", "hdr", g.mutate(base, g.r.randint(1, 2)))
    special = [b"Name: value", b"Name:value", b"Name : value", b" Name: value", b"Name:", b"Name: ", b":value",
               b"Name value", b"Na me: v", b"Name: v\r\n", b"Name: a\x00b", b"Name: a\x7fb", b"Name: a\x80b",
               b"Name: \tv\t", b"Name: v  ", b"Name:: v", b"N\xc3\xa9: v", b"Name: a\rb", b"Name: a\nb",
               b"Content-Length: 5", b"x: " + b"y" * 9000]
    fam = g.new_fam()
    for s in special:
        g.probe(fam, "H", "hdr", s)
    alpha = b"aZ09-_.!~*'()%:/?#[]@$&+,;= \t\"<>\\{}|^`\x00\x01\x7f\x80\xc3\xff"
    for _ in range(60 * scale):
        fam = g.new_fam()
        s = g.word(alpha, 0, 12)
        g.probe(fam, "H", "fields", s, g.word(alpha, 0, 8))
    for _ in range(20 * scale):
        fam = g.new_fam()
        code = g.ch([b"200", b"404", b"500", b"101", b"204", b"999", b"099", b"20", b"2000", b"abc", b"-1"])
        ver = g.ch([b"HTTP/1.1", b"HTTP/1.0", b"HTTP/2", b"HTTP/1.1", b"http/1.1", b"HTTP/1.10", b"HTTP/", b"ICY"])
        reason = g.ch([b" OK", b" Not Found", b"", b" ", b" Multi Word Reason", b"  OK", b" \xc3\xa9"])
        end = g.ch([b"\r\n", b"\n", b"", b"\r\n", b" \r\n"])
        g.probe(fam, "H", "status", ver + b" " + code + reason + end)
        g.probe(fam, "H", "status", g.mutate(ver + b" " + code + reason + end))
    for _ in range(40 * scale):
        fam = g.new_fam()
        hs = [hdr_line(g) for _ in range(g.r.randint(0, 6))]
        eol = g.ch([b"\r\n", b"\r\n", b"\r\n", b"\n"])
        block = b"".join(h + eol for h in hs) + eol + g.ch([b"", b"BODY", b"rest\r\n"])
        g.probe(fam, "H", "readhdr", block)
        for _ in range(2):
            g.probe(fam, "H", "readhdr", g.mutate(block, g.r.randint(1, 3)))
        g.probe(fam, "H", "resphead", b"HTTP/1.1 200 OK\r\n" + block)
        g.probe(fam, "H", "resphead", g.ch([b"HTTP/1.0 301 Moved\r\n", b"HTTP/1.1 100 Continue\r\n",
                                            b"HTTP/1.1 999\r\n", b"HTTP/1.1 20 OK\r\n"]) + block)
    fam = g.new_fam()
    g.probe(fam, "H", "readhdr", b"".join(b"X-H%d: v\r\n" % i for i in range(99)) + b"\r\n")
    g.probe(fam, "H", "readhdr", b"".join(b"X-H%d: v\r\n" % i for i in range(100)) + b"\r\n")
    g.probe(fam, "H", "readhdr", b"".join(b"X-H%d: v\r\n" % i for i in range(101)) + b"\r\n")
    g.probe(fam, "H", "readhdr", b"X: " + b"a" * 8180 + b"\r\n\r\n")
    g.probe(fam, "H", "readhdr", b"X: " + b"a" * 8200 + b"\r\n\r\n")
    g.probe(fam, "H", "readhdr", b"X: " + b"a" * 40000 + b"\r\n\r\n")
    for _ in range(30 * scale):
        fam = g.new_fam()
        parts = []
        for _ in range(g.r.randint(1, 6)):
            parts.append(g.word(b"abcdef \t\x00\xff:", 0, g.ch([3, 15, 16, 17, 40])))
            parts.append(g.ch([b"\r\n", b"\n", b"\r", b"\r\r\n", b"\n\r"]))
        g.probe(fam, "H", "lines", b"".join(parts[:-1] if g.r.random() < 0.3 else parts))
    tes = [b"chunked", b"Chunked", b"gzip, chunked", b"chunked, gzip", b"identity", b"gzip", b"chunked ",
           b"chunked;q=1", b" chunked", b"x-chunked", b"CHUNKED", b"deflate,chunked", b""]
    cls = [b"5", b"5, 5", b"5,6", b"005", b"abc", b"-1", b" 5 ", b"18446744073709551616", b"5,", b",5"]
    for _ in range(25 * scale):
        fam = g.new_fam()
        lines = []
        for _ in range(g.r.randint(0, 2)):
            lines.append(b"Transfer-Encoding: " + g.ch(tes))
        for _ in range(g.r.randint(0, 2)):
            lines.append(b"Content-Length: " + g.ch(cls))
        lines.append(b"X-Other: 1")
        g.r.shuffle(lines)
        g.probe(fam, "H", "te", b"\n".join(lines))


# ------------------------------------------------------------------------------------------------- B
def chunked_body(g, data, style=None):
    style = style or {}
    out = b""
    i = 0
    while i < len(data):
        n = min(len(data) - i, g.r.randint(1, 12))
        size = (b"%x" if g.r.random() < 0.7 else b"%X") % n
        if g.r.random() < 0.1:
            size = b"0" + size
        ext = g.ch([b"", b"", b"", b";ext=1", b";a;b=\"q\"", b" ;x", b"; x=y"]) if style.get("ext", True) else b""
        out += size + ext + CRLF + data[i:i + n] + CRLF
        i += n
    trailers = style.get("trailers", b"")
    out += b"0" + CRLF + trailers + CRLF
    return out


def gen_B(g, scale):
    for _ in range(80 * scale):
        fam = g.new_fam()
        data = g.word(b"abcdefghij\r\n\x00\xff", 0, 60)
        tr = g.ch([b"", b"", b"X-T: 1\r\n", b"X-T: 1\r\nX-U: two\r\n", b"Content-Length: 3\r\n",
                   b"Bad Trailer\r\n", b"X-T:\r\n"])
        body = chunked_body(g, data, {"trailers": tr})
        src = g.ch([b"", b"Trailer: X-T", b"Trailer: X-T, X-U", b"Trailer: x-u"])
        sz = g.ch([b"64", b"1", b"3,5,7", b"4096", b"2,1"])
        g.probe(fam, "B", "chunk", body + g.ch([b"", b"NEXT"]), sz, src)
        for _ in range(3):
            g.probe(fam, "B", "chunk", g.mutate(body, g.r.randint(1, 3)), sz, src)
    fam = g.new_fam()
    for s in [b"0\r\n\r\n", b"5\r\nhello\r\n0\r\n\r\n", b"5\r\nhello\r\n", b"-5\r\nhello\r\n0\r\n\r\n",
              b"ffffffffffffffffff\r\nx\r\n0\r\n\r\n", b"5 \r\nhello\r\n0\r\n\r\n", b"5\nhello\n0\n\n",
              b"5\r\nhelloXX0\r\n\r\n", b"0x5\r\nhello\r\n0\r\n\r\n", b"\r\n5\r\nhello\r\n0\r\n\r\n",
              b"5;" + b"e" * 5000 + b"\r\nhello\r\n0\r\n\r\n", b"+5\r\nhello\r\n0\r\n\r\n",
              b"7fffffffffffffff\r\nx", b"5\r\nhel"]:
        g.probe(fam, "B", "chunk", s, b"3", b"")
    for _ in range(60 * scale):
        fam = g.new_fam()
        data = g.word(b"abcdefghijklmnop\x00\n", 0, 50)
        mode = g.r.randrange(4)
        maxlen = g.ch([b"100000", b"10", b"30", b"0"])
        dec = g.ch([b"0", b"1"])
        if mode == 0:
            hdrs = b"Content-Length: %d" % len(data)
            raw = data + g.ch([b"", b"EXTRA"])
        elif mode == 1:
            hdrs = b"Transfer-Encoding: chunked"
            raw = chunked_body(g, data, {"trailers": g.ch([b"", b"X-T: v\r\n"])})
        elif mode == 2:
            hdrs = b"X-None: 1"
            raw = data
        else:
            hdrs = b"Content-Length: %d\nContent-Encoding: gzip" % 0
            comp = gzip.compress(data, mtime=0)
            hdrs = b"Content-Length: %d\nContent-Encoding: %s" % (len(comp), g.ch([b"gzip", b"deflate", b"br",
                                                                                     b"x-unknown"]))
            raw = comp if b"gzip" in hdrs else zlib.compress(data)
        g.probe(fam, "B", "content", hdrs, raw, maxlen, dec, g.ch([b"0", b"1"]))
        g.probe(fam, "B", "content", g.mutate(hdrs), raw, maxlen, dec, b"0")
        g.probe(fam, "B", "content", hdrs, g.mutate(raw, 2), maxlen, dec, b"0")
    for _ in range(40 * scale):
        fam = g.new_fam()
        data = g.word(b"0123456789abcdef", 0, 70)
        mode = g.ch([b"length", b"chunked", b"none"])
        raw = chunked_body(g, data) if mode == b"chunked" else data
        ln = len(data) + g.ch([0, 0, 0, -3, 5])
        mx = g.ch([1000, 20, 64])
        g.probe(fam, "B", "bodyreader", raw, mode, max(0, ln), mx)
        g.probe(fam, "B", "bodyreader", g.mutate(raw, 2), mode, max(0, ln), mx)


# ------------------------------------------------------------------------------------------------- Q
URL_CH = b"abcXYZ019-._~!$&'()*+,;=:@/?#[]% \"<>\\^`{|}\x00\x7f\xc3\xa9\xff"


def gen_Q(g, scale):
    schemes = [b"http://", b"https://", b"HTTP://", b"ftp://", b"", b"//", b"http:/", b"ws://"]
    hosts = [b"example.com", b"127.0.0.1", b"[::1]", b"[fe80::1%25eth0]", b"localhost", b"EXAMPLE.com", b"a.b-c.d",
             b"user@host", b"[::1", b"ho st", b""]
    ports = [b"", b":80", b":8080", b":0", b":65535", b":65536", b":abc", b":", b":-1"]
    paths = [b"", b"/", b"/a/b", b"/a%20b", b"/a b", b"/%zz", b"/\xc3\xa9", b"/a/../b", b"/a?x", b"/a#f"]
    queries = [b"", b"?x=1", b"?x=1&y=2", b"?", b"?a=%41", b"?a b=c d"]
    for _ in range(80 * scale):
        fam = g.new_fam()
        u = g.ch(schemes) + g.ch(hosts) + g.ch(ports) + g.ch(paths) + g.ch(queries) + g.ch([b"", b"", b"#frag"])
        g.probe(fam, "Q", "url", u)
        g.probe(fam, "Q", "url", g.mutate(u))
    for _ in range(40 * scale):
        fam = g.new_fam()
        base = b"http://h.example:8080" + g.ch([b"/", b"/a/b/c", b"/a/b/", b"/x?q=1", b""])
        loc = g.ch([b"/abs", b"rel", b"../up", b"./here", b"?q=2", b"#f", b"//other.example/p", b"https://x/y",
                    b"", b"a b", b"/p%20q", b"../../../../x", b"http://[::1]:9/z"])
        g.probe(fam, "Q", "relloc", loc, base)
        g.probe(fam, "Q", "relloc", g.mutate(loc), base)
    for _ in range(150 * scale):
        fam = g.new_fam()
        s = g.word(URL_CH, 0, 16)
        if g.r.random() < 0.4:
            s = s.replace(b"%", b"%" + g.ch([b"41", b"2F", b"2f", b"20", b"00", b"c3%a9", b"z", b"4", b"FF", b"2B"]))
        g.probe(fam, "Q", "enc", s)
    for _ in range(80 * scale):
        fam = g.new_fam()
        parts = []
        for _ in range(g.r.randint(0, 5)):
            k = g.word(b"abk%+ =2041", 0, 5)
            v = g.word(b"abv%+ =&2041\xc3\xa9", 0, 6)
            parts.append(k + (g.ch([b"=", b"=", b"", b"=="]) + v))
        q = g.ch([b"&", b"&", b"&&", b";"]).join(parts)
        g.probe(fam, "Q", "query", q)
        g.probe(fam, "Q", "query", g.mutate(q))
    for _ in range(40 * scale):
        fam = g.new_fam()
        path = g.ch([b"/p", b"/p?a=1", b"/p?", b"/p#x", b"", b"/p q"])
        params = b"\n".join(g.word(b"ab &=+%\xc3\xa9/?", 1, 5) + b"=" + g.word(b"xy &=+%\xc3\xa9/?#", 0, 6)
                            for _ in range(g.r.randint(0, 4)))
        g.probe(fam, "Q", "append", path, params)


# ------------------------------------------------------------------------------------------------- M
def mp_part(g, name=None, filename=None, ctype=None, data=None, extra=b""):
    name = name if name is not None else g.word(b"abcxyz_-", 1, 6)
    disp = b"Content-Disposition: " + g.ch([b"form-data", b"form-data", b"Form-Data", b"FORM-DATA"]) + \
        b"; name=\"" + name + b"\""
    if filename is not None:
        disp += b"; filename=\"" + filename + b"\""
    lines = [disp]
    if ctype:
        lines.append(b"Content-Type: " + ctype)
    if extra:
        lines.append(extra)
    if g.r.random() < 0.3:
        g.r.shuffle(lines)
    data = data if data is not None else g.word(b"abc 123\r\n-\x00", 0, 30)
    return b"\r\n".join(lines) + b"\r\n\r\n" + data


def mp_body(g, boundary, parts, preamble=b"", epilogue=b"", close=True):
    out = preamble
    for p in parts:
        out += b"--" + boundary + b"\r\n" + p + b"\r\n"
    if close:
        out += b"--" + boundary + b"--" + epilogue
    return out


def rand_parts(g):
    parts = []
    for _ in range(g.r.randint(1, 4)):
        kind = g.r.randrange(4)
        if kind == 0:
            parts.append(mp_part(g))
        elif kind == 1:
            parts.append(mp_part(g, filename=g.ch([b"a.txt", b"x y.bin", b"", b"C:\\dir\\f.txt", b"a;b.txt",
                                                   b"\xc3\xa9.txt"]),
                                 ctype=g.ch([b"text/plain", b"application/octet-stream", b"image/png"])))
        elif kind == 2:
            parts.append(mp_part(g, extra=g.ch([b"X-Part: 1", b"Content-Transfer-Encoding: binary",
                                                 b"content-type: text/x"])))
        else:
            n = g.word(b"abc", 1, 4)
            parts.append(b"Content-Disposition: form-data; name=\"" + n + b"\"; filename*=" +
                         g.ch([b"UTF-8''%C3%A9t%C3%A9.txt", b"utf-8''a%20b", b"ISO-8859-1''x", b"UTF-8''"]) +
                         b"\r\n\r\n" + g.word(b"xyz", 0, 10))
    return parts


def gen_M(g, scale):
    for _ in range(50 * scale):
        fam = g.new_fam()
        b = g.word(b"abcXYZ0129'()+_,-./:=?", 1, 30)
        ct = g.ch([b"multipart/form-data; boundary=", b"multipart/form-data;boundary=",
                   b"Multipart/Form-Data; Boundary=", b"multipart/form-data; charset=utf-8; boundary=",
                   b"multipart/mixed; boundary=", b"multipart/form-data; boundary=\""]) + b
        if ct.endswith(b"\"" + b) or b"=\"" in ct:
            ct += b"\""
        g.probe(fam, "M", "boundary", ct)
        g.probe(fam, "M", "boundary", g.mutate(ct))
    fam = g.new_fam()
    for ct in [b"multipart/form-data", b"multipart/form-data; boundary=", b"multipart/form-data; boundary=" + b"a" * 70,
               b"multipart/form-data; boundary=" + b"a" * 71, b"multipart/form-data; boundary=a b",
               b"multipart/form-data; boundary=\"a b\"", b"multipart/form-data; boundary=ab ",
               b"multipart/form-data; boundary=ab; boundary=cd", b"text/plain; boundary=x"]:
        g.probe(fam, "M", "boundary", ct)
    for _ in range(50 * scale):
        fam = g.new_fam()
        ps = []
        for _ in range(g.r.randint(1, 4)):
            k = g.ch([b"name", b"filename", b"filename*", b"Name", b"x"])
            v = g.word(b"ab c;\\\"=.", 0, 8)
            ps.append(k + g.ch([b"=\"" + v + b"\"", b"=" + v, b"=\"" + v, b""]))
        s = g.ch([b"; ", b";", b" ; "]).join(ps)
        g.probe(fam, "M", "dispo", s)
        g.probe(fam, "M", "dispo", g.mutate(s))
    for _ in range(80 * scale):
        fam = g.new_fam()
        boundary = g.ch([b"XyZ", b"----WebKitFormBoundary7MA4YWxkTrZu0gW", b"a'b(c)", b"b"])
        parts = rand_parts(g)
        body = mp_body(g, boundary, parts, preamble=g.ch([b"", b"", b"preamble\r\n"]),
                       epilogue=g.ch([b"", b"\r\n", b"\r\nepilogue"]))
        sz = g.ch([b"", b"1", b"7", b"3,11,2", b"64"])
        g.probe(fam, "M", "form", boundary, body, sz)
        for _ in range(3):
            g.probe(fam, "M", "form", boundary, g.mutate(body, g.r.randint(1, 2)), sz)
        g.probe(fam, "M", "form", boundary, mp_body(g, boundary, parts, close=False), sz)
    for _ in range(50 * scale):
        fam = g.new_fam()
        items = []
        for _ in range(g.r.randint(0, 3)):
            items.append(b"\x1f".join([g.word(b"ab\"\r\n\\ %", 1, 6), g.word(b"content\r\n", 0, 10),
                                       g.ch([b"", b"f.txt", b"a\"b.txt", b"x\r\ny", b"\xc3\xa9.bin", b"a\\b"]),
                                       g.ch([b"", b"text/plain", b"image/png"])]))
        boundary = g.ch([b"BOUNDARY", b"xYz-09", b"----abc"])
        g.probe(fam, "M", "mpser", b"\x1e".join(items), boundary, g.ch([b"1", b"0"]),
                g.word(b"ab\"\\\r\n%;", 0, 8))
    for _ in range(40 * scale):
        fam = g.new_fam()
        g.probe(fam, "M", "enc", g.ch([b"../../etc/passwd", b"a/b\\c.txt", b"..", b".", b"x\x00y", b"  a  ",
                                       b"C:\\x\\y.txt", b"a:b", b"\xc3\xa9/\xc3\xa9"]) + g.word(b"./\\ab", 0, 4))


# ------------------------------------------------------------------------------------------------- R
def gen_R(g, scale):
    for _ in range(150 * scale):
        fam = g.new_fam()
        specs = []
        for _ in range(g.r.randint(1, 4)):
            a, b = g.r.randint(0, 60), g.r.randint(0, 60)
            specs.append(g.ch([b"%d-%d" % (min(a, b), max(a, b)), b"%d-" % a, b"-%d" % b, b"%d-%d" % (max(a, b), min(a, b)),
                               b"-0", b"0-0", b"%d-%d" % (a, a)]))
        h = g.ch([b"bytes=", b"bytes=", b"Bytes=", b"bytes =", b"items="]) + g.ch([b",", b",", b", "]).join(specs)
        ln = g.ch([b"10", b"30", b"61", b"100", b"0", b"1"])
        g.probe(fam, "R", "range", h, ln)
        g.probe(fam, "R", "range", g.mutate(h), ln)
    fam = g.new_fam()
    for h in [b"bytes=0-0", b"bytes=-1", b"bytes=0-", b"bytes=", b"bytes=-", b"bytes=1-2,", b"bytes=,1-2",
              b"bytes=a-b", b"bytes=1-2-3", b"bytes= 1-2", b"bytes=99999999999999999999-",
              b"bytes=0-1,1-2,2-3,3-4", b"bytes=0-5,0-5,0-5,0-5", b"bytes=" + b",".join(b"%d-%d" % (i, i) for i in range(1025))]:
        g.probe(fam, "R", "range", h, b"50")
    for _ in range(40 * scale):
        fam = g.new_fam()
        rs = b";".join(b"%d,%d" % (g.ch([-1, 0, 3, 10, 100]), g.ch([-1, 0, 5, 9, 99])) for _ in range(g.r.randint(0, 3)))
        g.probe(fam, "R", "rangehdr", rs)
    for _ in range(120 * scale):
        fam = g.new_fam()
        specs = []
        for _ in range(g.r.randint(2, 4)):
            a = g.r.randint(0, 40)
            specs.append(g.ch([b"%d-%d" % (a, a + g.r.randint(0, 9)), b"-%d" % g.r.randint(1, 9), b"%d-" % a]))
        g.probe(fam, "R", "mranges", b"bytes=" + b",".join(specs), g.ch([b"50", b"45", b"100"]),
                g.ch([b"text/plain", b"application/octet-stream", b""]))


# ------------------------------------------------------------------------------------------------- N
def gen_N(g, scale):
    types = [b"text/html", b"application/json", b"*/*", b"text/*", b"image/png", b"application/xml", b"TEXT/Plain"]
    for _ in range(100 * scale):
        fam = g.new_fam()
        items = []
        for _ in range(g.r.randint(1, 5)):
            t = g.ch(types)
            if g.r.random() < 0.6:
                t += g.ch([b";q=0.5", b"; q=0.9", b";q=1", b";q=0", b";q=1.0", b";q=0.123", b";q=1.5", b";q=abc",
                           b";level=1", b";level=1;q=0.3", b";q=0.8;x=y", b";Q=0.2", b";q=.5", b";q=0.1234"])
            items.append(t)
        s = g.ch([b",", b", ", b" ,"]).join(items)
        g.probe(fam, "N", "accept", s)
        g.probe(fam, "N", "accept", g.mutate(s))
    for _ in range(60 * scale):
        fam = g.new_fam()
        s = g.ch(types) + b"".join(g.ch([b"; charset=utf-8", b";charset=\"utf-8\"", b"; a=\"x\\\"y\"", b"; b=\"c;d\"",
                                          b"; Name=Val", b";", b"; k", b"; k=", b"; =v"])
                                   for _ in range(g.r.randint(0, 3)))
        g.probe(fam, "N", "media", s)
        g.probe(fam, "N", "media", g.mutate(s))
    for _ in range(50 * scale):
        fam = g.new_fam()
        s = g.ch([b"gzip", b"br", b"*", b"zstd", b"text/html", b""]) + g.ch([b"", b";q=0.5", b"; q=1", b";q=0",
                                                                           b";q=1.001", b";q=0.0001", b";q=x",
                                                                           b";level=2;q=0.4", b" ; q=0.7"])
        g.probe(fam, "N", "quality", s)
        g.probe(fam, "N", "quality", g.mutate(s))
    encs = [b"gzip", b"br", b"zstd", b"deflate", b"identity", b"*", b"GZIP", b"x-gzip", b"compress"]
    for _ in range(80 * scale):
        fam = g.new_fam()
        items = []
        for _ in range(g.r.randint(0, 4)):
            e = g.ch(encs)
            if g.r.random() < 0.5:
                e += g.ch([b";q=0", b";q=0.5", b";q=1", b";q=0.001", b"; q=0.9", b";q=0.0"])
            items.append(e)
        ae = b", ".join(items)
        ct = g.ch([b"text/plain", b"text/html", b"application/json", b"image/png", b"application/octet-stream",
                   b"application/javascript", b"text/event-stream", b"image/svg+xml"])
        g.probe(fam, "N", "encoding", b"Accept-Encoding: " + ae, ct)
        g.probe(fam, "N", "encoding", b"Accept-Encoding: " + g.mutate(ae), ct)
    for _ in range(50 * scale):
        fam = g.new_fam()
        params = []
        for _ in range(g.r.randint(1, 5)):
            k = g.ch([b"realm", b"nonce", b"qop", b"opaque", b"algorithm", b"stale", b"Realm"])
            v = g.ch([b"\"x\"", b"\"a,b\"", b"\"q\\\"uote\"", b"auth", b"\"auth,auth-int\"", b"MD5", b"\"\""])
            params.append(k + b"=" + v)
        h = g.ch([b"Digest ", b"Basic ", b"digest ", b"Bearer ", b"Digest"]) + g.ch([b", ", b","]).join(params)
        proxy = g.ch([b"0", b"1"])
        name = b"Proxy-Authenticate" if (proxy == b"1") ^ (g.r.random() < 0.2) else b"WWW-Authenticate"
        g.probe(fam, "N", "wwwauth", name + b": " + h, proxy)
        g.probe(fam, "N", "wwwauth", name + b": " + g.mutate(h), proxy)
    for _ in range(40 * scale):
        fam = g.new_fam()
        g.probe(fam, "N", "media", b"\"" + g.word(b"ab\\\" ,;", 0, 10) + b"\"" + g.word(b"x\"\\", 0, 3))


# ------------------------------------------------------------------------------------------------- client
SEP = b"\x00\x00CONN\x00\x00"


def resp(status=b"200 OK", headers=(), body=b"", ver=b"HTTP/1.1"):
    return ver + b" " + status + CRLF + b"".join(h + CRLF for h in headers) + CRLF + body


def gen_client(g, scale):
    # B/H: response framing as seen by the client
    for _ in range(60 * scale):
        fam = g.new_fam()
        data = g.word(b"abcdefgh\r\n\x00", 0, 50)
        mode = g.r.randrange(5)
        if mode == 0:
            r = resp(headers=[b"Content-Length: %d" % len(data), b"X-A: 1"], body=data)
            nom = "H"
        elif mode == 1:
            r = resp(headers=[b"Transfer-Encoding: chunked"],
                     body=chunked_body(g, data, {"trailers": g.ch([b"", b"X-T: 1\r\n"])}))
            nom = "B"
        elif mode == 2:
            r = resp(headers=[b"Connection: close"], body=data)
            nom = "B"
        elif mode == 3:
            r = resp(status=g.ch([b"204 No Content", b"304 Not Modified"]), headers=[b"Content-Length: 4"], body=b"")
            nom = "H"
        else:
            r = resp(headers=[b"Transfer-Encoding: chunked", b"Trailer: X-T"],
                     body=chunked_body(g, data, {"trailers": b"X-T: 1\r\nX-Other: 2\r\n"}))
            nom = "B"
        kind = g.ch([b"get", b"get", b"get_recv", b"stream", b"head"])
        g.probe(fam, nom, "cli", kind, b"/p", b"", b"", r, b"", b"", b"")
        for _ in range(2):
            g.probe(fam, nom, "cli", kind, b"/p", b"", b"", g.mutate(r, g.r.randint(1, 2)), b"", b"", b"")
    fam = g.new_fam()
    for r in [b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nshort", b"HTTP/1.1 200\r\nContent-Length: 2\r\n\r\nok",
              b"HTTP/1.0 200 OK\r\n\r\nbody until close", b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok",
              b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 3\r\n\r\nokk",
              b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 3\r\n\r\n3\r\nabc\r\n0\r\n\r\n",
              b"HTTP/1.1 200 OK\r\nBad Header\r\n\r\n", b"garbage\r\n\r\n", b"", b"HTTP/1.1 200 OK\n\nlf only",
              b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\n\r\n" + b"x" * 5000,
              b"HTTP/1.1 200 OK\r\nX: " + b"y" * 9000 + b"\r\nContent-Length: 0\r\n\r\n"]:
        for kind in [b"get", b"stream"]:
            g.probe(fam, "H", "cli", kind, b"/p", b"", b"", r, b"maxlen" if b"5000" in r else b"", b"", b"")
    # decompression
    for _ in range(20 * scale):
        fam = g.new_fam()
        data = g.word(b"hello world ", 1, 80)
        comp = gzip.compress(data, mtime=0)
        r = resp(headers=[b"Content-Encoding: gzip", b"Content-Length: %d" % len(comp)], body=comp)
        g.probe(fam, "B", "cli", b"get", b"/z", b"", b"", r, g.ch([b"", b"nodecompress"]), b"", b"")
        g.probe(fam, "B", "cli", b"get", b"/z", b"", b"", resp(headers=[b"Content-Encoding: gzip",
                                                                       b"Transfer-Encoding: chunked"],
                                                              body=chunked_body(g, comp)), b"", b"", b"")
    # Q: request targets, params, redirects
    ok = resp(headers=[b"Content-Length: 2"], body=b"ok")
    for _ in range(50 * scale):
        fam = g.new_fam()
        path = b"/" + g.word(URL_CH.replace(b"#", b""), 0, 12)
        params = b"\n".join(g.word(b"ab &=+%\xc3\xa9/", 1, 5) + b"=" + g.word(b"xy &=+%\xc3\xa9/?#", 0, 6)
                            for _ in range(g.r.randint(0, 3)))
        g.probe(fam, "Q", "cli", b"get_params", path, b"", params, ok, g.ch([b"", b"nopathencode"]), b"", b"")
        g.probe(fam, "Q", "cli", b"post_params", b"/form", b"", params, ok, b"", b"", b"")
    for _ in range(30 * scale):
        fam = g.new_fam()
        loc = g.ch([b"/next", b"next", b"../up/x", b"?q=1", b"http://127.0.0.1:{PORT}/abs", b"/sp ace",
                    b"/%7Euser", b"//127.0.0.1:{PORT}/pr", b"/\xc3\xa9"])
        code = g.ch([b"301 Moved Permanently", b"302 Found", b"303 See Other", b"307 Temporary Redirect",
                     b"308 Permanent Redirect"])
        # "Connection: close": without it the client may reuse the first connection for the redirect while the
        # peer's close is still in flight, which makes the reference itself nondeterministic
        r = resp(status=code, headers=[b"Location: " + loc, b"Content-Length: 0", b"Connection: close"]) + SEP + ok
        kind = g.ch([b"get", b"post"])
        g.probe(fam, "Q", "cli", kind, b"/a/b/c", b"", b"body", r, b"follow", b"text/plain", b"")
    # M: multipart uploads
    for _ in range(40 * scale):
        fam = g.new_fam()
        items = []
        for _ in range(g.r.randint(1, 3)):
            items.append(b"\x1f".join([g.word(b"ab\" %\\", 1, 6), g.word(b"content\r\n", 0, 10),
                                       g.ch([b"", b"f.txt", b"a\"b.txt", b"\xc3\xa9.bin"]),
                                       g.ch([b"", b"text/plain", b"image/png"])]))
        g.probe(fam, "M", "cli", g.ch([b"post_form", b"put_form"]), b"/up", b"", b"\x1e".join(items), ok, b"", b"",
                g.ch([b"BOUNDARY123", b"xyz", b"bad boundary", b""]))
    # B: request bodies the client frames
    for _ in range(30 * scale):
        fam = g.new_fam()
        data = g.word(b"abcdef0123", 0, 60)
        g.probe(fam, "B", "cli", b"post_chunked", b"/c", b"", data, ok, g.ch([b"", b"compress"]), b"text/plain",
                g.ch([b"1", b"5,3", b"64", b"0,4"]))
        g.probe(fam, "B", "cli", b"post_provider", b"/c", b"", data, ok, b"", b"application/x-a", b"")
        g.probe(fam, "B", "cli", g.ch([b"post", b"put", b"patch", b"delete"]), b"/c",
                g.ch([b"", b"X-A: b", b"Content-Type: x/y"]), data, ok, g.ch([b"", b"compress"]), b"text/plain", b"")
    # R: Range request headers
    for _ in range(50 * scale):
        fam = g.new_fam()
        rs = b";".join(b"%d,%d" % (g.ch([-1, 0, 3, 10]), g.ch([-1, 0, 5, 99])) for _ in range(g.r.randint(1, 3)))
        body = b"0123456789"
        r = resp(status=b"206 Partial Content", headers=[b"Content-Range: bytes 0-9/100", b"Content-Length: 10"],
                 body=body)
        g.probe(fam, "R", "cli", b"get_ranges", b"/r", b"", rs, r, b"", b"", b"")
    # N: client headers
    for _ in range(15 * scale):
        fam = g.new_fam()
        g.probe(fam, "N", "cli", b"get", b"/n", g.ch([b"Accept-Encoding: identity", b"Accept: text/html", b"X-Y: z",
                                                     b"Host: other.example"]), b"", ok, b"", b"", b"")


# ------------------------------------------------------------------------------------------------- server
def req(method=b"GET", target=b"/echo", ver=b"HTTP/1.1", headers=(b"Host: h",), body=b""):
    return method + b" " + target + b" " + ver + CRLF + b"".join(h + CRLF for h in headers) + CRLF + body


def gen_server(g, scale):
    # H: request line and header block
    methods = [b"GET", b"POST", b"PUT", b"DELETE", b"OPTIONS", b"PATCH", b"HEAD", b"get", b"FOO", b"G\x00T", b"CONNECT"]
    targets = [b"/echo", b"/echo/a/b", b"/echo?x=1", b"/echo?a=1&a=2&b=%20c", b"http://h/echo?q", b"*", b"/echo#f",
               b"/echo/%7E%2Fx", b"/echo/a b", b"echo", b"/echo/\xc3\xa9", b"/echo?" + b"a" * 100, b"//echo",
               b"/echo/../echo", b"/echo?x=%zz", b"/echo?+plus+=%2B"]
    vers = [b"HTTP/1.1", b"HTTP/1.0", b"HTTP/1.1", b"HTTP/2.0", b"HTTP/1.2", b"HTTP/11", b"http/1.1", b"HTTP/1.1 "]
    for _ in range(60 * scale):
        fam = g.new_fam()
        m = g.ch(methods[:7])
        tgt = g.ch(targets) if g.r.random() < 0.3 else g.ch(targets[:4] + targets[7:8])
        ver = g.ch(vers) if g.r.random() < 0.15 else g.ch([b"HTTP/1.1", b"HTTP/1.0"])
        line = m + b" " + tgt + b" " + ver
        hs = [b"Host: " + (g.ch([b"h", b"example.com:80", b"[::1]:8080", b"bad host", b"", b"a_b"])
                           if g.r.random() < 0.2 else g.ch([b"h", b"example.com:80", b"[::1]:8080"]))]
        hs += [g.ch(HNAMES[:10]) + b": " + g.ch(VALS[:9]) if g.r.random() < 0.8 else hdr_line(g)
               for _ in range(g.r.randint(0, 4))]
        body = b""
        if m in (b"POST", b"PUT", b"PATCH"):
            body = g.word(b"abc", 0, 10)
            hs.append(b"Content-Length: %d" % len(body))
        r = line + CRLF + b"".join(h + CRLF for h in hs) + CRLF + body
        g.wire(fam, "H", r)
        for _ in range(3):
            g.wire(fam, "H", g.mutate(r, g.r.randint(1, 2)))
    fam = g.new_fam()
    for r in [b"GET /echo HTTP/1.1\r\n\r\n", b"GET /echo\r\n\r\n", b"GET  /echo HTTP/1.1\r\nHost: h\r\n\r\n",
              b"GET /echo HTTP/1.1\nHost: h\n\n", b"\r\nGET /echo HTTP/1.1\r\nHost: h\r\n\r\n",
              b"GET /echo HTTP/1.1\r\nHost: h\r\nHost: i\r\n\r\n", b"GET /echo HTTP/1.1\r\nHost: h\r\n x: folded\r\n\r\n",
              b"GET /" + b"e" * 9000 + b" HTTP/1.1\r\nHost: h\r\n\r\n",
              b"GET /echo HTTP/1.1\r\nHost: h\r\n" + b"".join(b"X-%d: v\r\n" % i for i in range(120)) + b"\r\n",
              b"GET /echo HTTP/1.1\r\nHost: h\r\nX: " + b"v" * 9000 + b"\r\n\r\n",
              b"GET /echo HTTP/1.1\r\nHost: h\r\n", b"GET /echo HTTP/1.1\r\nHost: h\r\nX : y\r\n\r\n",
              b"GET /echo HTTP/1.0\r\n\r\n", b"GET /echo HTTP/1.1\r\nHost: h\r\nConnection: close\r\n\r\nGET /echo HTTP/1.1\r\nHost: h\r\n\r\n",
              b"GET /echo HTTP/1.1\r\nHost: h\r\n\r\nGET /echo?second HTTP/1.1\r\nHost: h\r\n\r\n",
              b"GET /echo HTTP/1.0\r\nConnection: keep-alive\r\n\r\nGET /echo?b HTTP/1.0\r\n\r\n",
              b"OPTIONS * HTTP/1.1\r\nHost: h\r\n\r\n", b"HEAD /data/10 HTTP/1.1\r\nHost: h\r\n\r\n",
              b"HEAD /chunked/10 HTTP/1.1\r\nHost: h\r\n\r\n", b"GET /nope HTTP/1.1\r\nHost: h\r\n\r\n",
              b"DELETE /data/3 HTTP/1.1\r\nHost: h\r\n\r\n", b"GET /redirect HTTP/1.1\r\nHost: h\r\n\r\n"]:
        g.wire(fam, "H", r)
    # B: request bodies
    for _ in range(80 * scale):
        fam = g.new_fam()
        data = g.word(b"abcdef 012\r\n\x00", 0, 40)
        mode = g.r.randrange(6)
        tgt = g.ch([b"/echo", b"/reader"])
        if mode == 0:
            r = req(b"POST", tgt, headers=(b"Host: h", b"Content-Length: %d" % len(data)), body=data)
        elif mode == 1:
            r = req(b"POST", tgt, headers=(b"Host: h", b"Transfer-Encoding: chunked"),
                    body=chunked_body(g, data, {"trailers": g.ch([b"", b"X-T: 1\r\n"])}))
        elif mode == 2:
            r = req(b"POST", tgt, headers=(b"Host: h", b"Transfer-Encoding: chunked", b"Trailer: X-T"),
                    body=chunked_body(g, data, {"trailers": b"X-T: 1\r\nX-Not: 2\r\n"}))
        elif mode == 3:
            comp = gzip.compress(data, mtime=0)
            r = req(b"POST", tgt, headers=(b"Host: h", b"Content-Encoding: gzip", b"Content-Length: %d" % len(comp)),
                    body=comp)
        elif mode == 4:
            r = req(b"POST", tgt, headers=(b"Host: h", b"Expect: 100-continue", b"Content-Length: %d" % len(data)),
                    body=data)
        else:
            r = req(b"PUT", tgt, headers=(b"Host: h", b"Content-Length: %d" % len(data)), body=data) + \
                req(b"POST", tgt, headers=(b"Host: h", b"Transfer-Encoding: chunked"), body=chunked_body(g, data))
        g.wire(fam, "B", r)
        for _ in range(3):
            g.wire(fam, "B", g.mutate(r, g.r.randint(1, 2)))
    fam = g.new_fam()
    big = b"z" * 70000
    for r in [req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: 70000"), body=big),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Transfer-Encoding: chunked"),
                  body=b"%x\r\n" % len(big) + big + b"\r\n0\r\n\r\n"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: abc"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: -1"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: 3", b"Content-Length: 3"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: 3", b"Content-Length: 4"), body=b"abcd"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: 3, 3"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: 3", b"Transfer-Encoding: chunked"),
                  body=b"3\r\nabc\r\n0\r\n\r\n"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Transfer-Encoding: gzip"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Transfer-Encoding: chunked, gzip"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Transfer-Encoding: gzip, chunked"), body=b"3\r\nabc\r\n0\r\n\r\n"),
              req(b"POST", b"/echo", headers=(b"Host: h",), body=b"no length"),
              req(b"POST", b"/echo", ver=b"HTTP/1.0", headers=(), body=b"no length 1.0"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Length: 10"), body=b"short"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Encoding: br", b"Content-Length: 3"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Encoding: unknown", b"Content-Length: 3"), body=b"abc"),
              req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Type: application/x-www-form-urlencoded",
                                              b"Content-Length: 21"), body=b"a=1&b=%20x&c=+y&a=two"),
              req(b"GET", b"/echo?q=1", headers=(b"Host: h", b"Content-Length: 4"), body=b"data")]:
        g.wire(fam, "B", r)
    for _ in range(25 * scale):
        fam = g.new_fam()
        body = b"&".join(g.word(b"ab%2B+=", 1, 4) + b"=" + g.word(b"xy%20+&", 0, 5) for _ in range(g.r.randint(1, 4)))
        g.wire(fam, "Q", req(b"POST", b"/echo", headers=(b"Host: h", b"Content-Type: application/x-www-form-urlencoded",
                                                         b"Content-Length: %d" % len(body)), body=body))
    # Q: targets and query strings
    for _ in range(60 * scale):
        fam = g.new_fam()
        path = b"/echo" + g.ch([b"", b"/", b"/x"]) + g.word(b"ab%2F%20+.~-\xc3\xa9", 0, 8)
        q = b"&".join(g.word(b"ab%41+=;", 1, 4) + g.ch([b"=", b"", b"=="]) + g.word(b"xy%20+;,/?", 0, 5)
                      for _ in range(g.r.randint(0, 4)))
        r = req(b"GET", path + (b"?" + q if q or g.r.random() < 0.3 else b""))
        g.wire(fam, "Q", r)
        g.wire(fam, "Q", g.mutate(r))
    # M: multipart bodies to /echo (buffered) and /reader (streaming)
    for _ in range(60 * scale):
        fam = g.new_fam()
        boundary = g.ch([b"XyZ", b"----WebKitFormBoundary7MA4YWxkTrZu0gW", b"b"])
        parts = rand_parts(g)
        body = mp_body(g, boundary, parts, epilogue=g.ch([b"", b"\r\n"]))
        ct = b"Content-Type: " + g.ch([b"multipart/form-data; boundary=", b"multipart/form-data; boundary=\"",
                                       b"multipart/form-data;boundary="]) + boundary
        if ct.count(b"\"") == 1:
            ct += b"\""
        tgt = g.ch([b"/echo", b"/reader"])
        framing = g.r.randrange(2)

        def mk(b):
            if framing == 0:
                return req(b"POST", tgt, headers=(b"Host: h", ct, b"Content-Length: %d" % len(b)), body=b)
            return req(b"POST", tgt, headers=(b"Host: h", ct, b"Transfer-Encoding: chunked"), body=chunked_body(g, b))
        g.wire(fam, "M", mk(body))
        for _ in range(3):
            g.wire(fam, "M", mk(g.mutate(body, g.r.randint(1, 2))))
        g.wire(fam, "M", mk(mp_body(g, boundary, parts, close=False)))
    # R: ranges over every response kind
    for _ in range(220 * scale):
        fam = g.new_fam()
        n = g.ch([0, 1, 10, 50, 100, 3000])
        tgt = g.ch([b"/data/%d" % n, b"/provider/%d" % n, b"/chunked/%d" % n, b"/static/a.txt", b"/static/c.bin",
                    b"/static/empty.txt", b"/nolength/%d" % n, b"/echo"])
        specs = []
        for _ in range(g.r.randint(1, 3)):
            a = g.r.randint(0, 120)
            specs.append(g.ch([b"%d-%d" % (a, a + g.r.randint(0, 30)), b"-%d" % g.r.randint(0, 40), b"%d-" % a]))
        rh = b"Range: " + g.ch([b"bytes=", b"bytes=", b"bytes=", b"Bytes=", b"units="]) + b",".join(specs)
        hs = [b"Host: h", rh]
        if g.r.random() < 0.3:
            hs.append(b"If-Range: " + g.ch([b"\"d%d\"" % n, b"\"other\"", b"W/\"6553f100-64\"",
                                            b"Tue, 14 Nov 2023 22:13:20 GMT", b"Mon, 01 Jan 2024 00:00:00 GMT",
                                            b"garbage"]))
        method = g.ch([b"GET", b"GET", b"GET", b"HEAD"])
        g.wire(fam, "R", req(method, tgt, headers=tuple(hs)))
        g.wire(fam, "R", req(method, tgt, headers=tuple(hs[:1] + [g.mutate(rh)] + hs[2:])))
    # N: negotiation, conditional requests, static files
    for _ in range(80 * scale):
        fam = g.new_fam()
        kind = g.r.randrange(3)
        if kind == 0:
            items = []
            for _ in range(g.r.randint(0, 3)):
                items.append(g.ch([b"gzip", b"br", b"zstd", b"deflate", b"identity", b"*"]) +
                             g.ch([b"", b";q=0", b";q=0.5", b";q=1"]))
            r = req(b"GET", g.ch([b"/text/200", b"/text/2000", b"/data/500", b"/static/b.html", b"/static/data.json",
                                  b"/chunked/300", b"/text/10"]),
                    headers=(b"Host: h", b"Accept-Encoding: " + b", ".join(items)))
        elif kind == 1:
            types = [b"text/html", b"application/json", b"*/*", b"text/*;q=0.5", b"image/png;q=0", b"a/b;level=1"]
            r = req(b"GET", b"/accept", headers=(b"Host: h", b"Accept: " + b", ".join(
                g.ch(types) for _ in range(g.r.randint(1, 4)))))
        else:
            cond = g.ch([b"If-None-Match: W/\"6553f100-64\"", b"If-None-Match: \"6553f100-64\"", b"If-None-Match: *",
                         b"If-None-Match: \"x\", W/\"6553f100-64\"", b"If-Modified-Since: Tue, 14 Nov 2023 22:13:20 GMT",
                         b"If-Modified-Since: Wed, 15 Nov 2023 00:00:00 GMT", b"If-Modified-Since: garbage",
                         b"If-Modified-Since: Tuesday, 14-Nov-23 22:13:20 GMT", b"If-None-Match: \"nomatch\""])
            r = req(g.ch([b"GET", b"HEAD"]), g.ch([b"/static/a.txt", b"/static/b.html", b"/static/dir",
                                                    b"/static/dir/", b"/static/sp%20ace.txt", b"/static/../x",
                                                    b"/static/%2e%2e/x", b"/static/missing"]),
                    headers=(b"Host: h", cond))
        g.wire(fam, "N", r)
        g.wire(fam, "N", g.mutate(r))


def generate(seed, prefix, scale=1):
    g = Gen(seed, prefix)
    for f in (gen_H, gen_B, gen_Q, gen_M, gen_R, gen_N, gen_client, gen_server):
        f(g, scale)
    return g.cases
