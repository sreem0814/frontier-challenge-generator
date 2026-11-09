"""gen/strip.py: make the starting httplib.h from the upstream v0.62.0 header.

Every function in TARGETS keeps its declaration and signature; its body becomes a stub that fails
(returns false / an error / an empty value). FormDataParser keeps its public members only.

usage: python3 -I gen/strip.py <upstream httplib.h> <out httplib.h> [--keep AREA,AREA] [--report]
--keep restores whole areas from upstream (used to measure core_share).
"""
import re
import sys

STUB_NOTE = "/* removed from this tree */"

# (area, unique start text of the definition's first line, occurrence, stub statement)
TARGETS = [
    # H: line reading, request line, status line, header fields
    ("H", "inline bool stream_line_reader::getline() {", 0, "return false;"),
    ("H", "inline void stream_line_reader::append(char c)", 0, "(void)c;"),
    ("H", "inline void stream_line_reader::append(const char *data, size_t size)", 0, "(void)data; (void)size;"),
    ("H", "inline bool parse_header(const char *beg, const char *end, T fn) {", 0, "(void)beg; (void)end; (void)fn; return false;"),
    ("H", "inline bool parse_trailers(stream_line_reader &line_reader, Headers &dest,", 0, "(void)line_reader; (void)dest; (void)src_headers; return false;"),
    ("H", "inline bool read_headers(Stream &strm, Headers &headers) {", 0, "(void)strm; (void)headers; return false;"),
    ("H", "inline bool parse_status_line(const char *line, std::string &version,", 0, None),
    ("H", "inline bool read_response_head(Stream &strm, int &status, Headers &headers) {", 0, None),
    ("H", "inline bool is_token_char(char c) {", 0, "(void)c; return false;"),
    ("H", "inline bool is_token(const std::string &s) {", 0, "(void)s; return false;"),
    ("H", "inline bool is_field_name(const std::string &s) {", 0, "(void)s; return false;"),
    ("H", "inline bool is_vchar(char c) {", 0, "(void)c; return false;"),
    ("H", "inline bool is_obs_text(char c) {", 0, "(void)c; return false;"),
    ("H", "inline bool is_field_vchar(char c) {", 0, "(void)c; return false;"),
    ("H", "inline bool is_field_content(const std::string &s) {", 0, "(void)s; return false;"),
    ("H", "inline bool is_field_value(const std::string &s) {", 0, "(void)s; return false;"),
    ("H", "inline bool is_field_valid(const std::string &name, const std::string &value) {", 0, "(void)name; (void)value; return false;"),
    ("H", "inline bool is_request_target(const std::string &s) {", 0, "(void)s; return false;"),
    ("H", "inline bool is_host(const std::string &s) {", 0, "(void)s; return false;"),
    ("H", "inline bool has_conflicting_content_length(const Headers &headers) {", 0, "(void)headers; return false;"),
    ("H", "inline bool is_chunked_transfer_encoding(const Headers &headers) {", 0, "(void)headers; return false;"),
    ("H", "inline bool Server::parse_request_line(", 0, None),
    ("H", "inline bool ClientImpl::read_response_line(Stream &strm, const Request &req,", 0, None),
    ("H", "inline ssize_t write_request_line(Stream &strm, const std::string &method,", 0, None),
    ("H", "inline ssize_t write_response_line(Stream &strm, int status) {", 0, "(void)strm; (void)status; return -1;"),
    ("H", "inline ssize_t write_headers(Stream &strm, const Headers &headers) {", 0, "(void)strm; (void)headers; return -1;"),
    # B: message body framing (Content-Length, chunked, close-delimited), both directions
    ("B", "inline ReadContentResult read_content_with_length(", 0, None),
    ("B", "read_content_without_length(Stream &strm, size_t payload_max_length,", 0, None),
    ("B", "inline ReadContentResult read_content_chunked(Stream &strm, T &x,", 0, None),
    ("B", "bool prepare_content_receiver(T &x, int &status,", 0, None),
    ("B", "bool read_content(Stream &strm, T &x, size_t payload_max_length, int &status,", 0, None),
    ("B", "inline bool Server::read_content(Stream &strm, Request &req, Response &res) {", 0, "(void)strm; (void)req; (void)res; return false;"),
    ("B", "inline bool Server::read_content_core(", 0, None),
    ("B", "inline ssize_t ChunkedDecoder::read_payload(", 0, None),
    ("B", "inline bool ChunkedDecoder::parse_trailers_into(", 0, None),
    ("B", "inline ssize_t detail::BodyReader::read(char *buf, size_t len) {", 0, "(void)buf; (void)len; return -1;"),
    ("B", "inline bool write_content_with_progress(Stream &strm,", 0, None),
    ("B", "write_content_without_length(Stream &strm,", 0, None),
    ("B", "write_content_chunked(Stream &strm, const ContentProvider &content_provider,", 0, None),
    ("B", "inline void set_framing_headers(const Request &req, Response &res,", 0, None),
    # Q: URLs, query strings and percent-encoding
    ("Q", "inline bool parse_url(const std::string &url, UrlComponents &uc) {", 0, "(void)url; (void)uc; return false;"),
    ("Q", "inline std::string resolve_relative_location(const std::string &location,", 0, None),
    ("Q", "inline std::string encode_path(const std::string &s) {", 0, "(void)s; return std::string();"),
    ("Q", "inline std::string params_to_query_str(const Params &params) {", 0, "(void)params; return std::string();"),
    ("Q", "inline void divide_query_pair(const char *b, const char *e, std::string &key,", 0, None),
    ("Q", "inline void parse_query_text(const char *data, std::size_t size,", 0, None),
    ("Q", "inline std::string normalize_query_string(const std::string &query) {", 0, "(void)query; return std::string();"),
    ("Q", "inline std::string encode_request_target(const std::string &uri,", 0, None),
    ("Q", "inline std::string encode_uri_component(const std::string &value) {", 0, "(void)value; return std::string();"),
    ("Q", "inline std::string encode_uri(const std::string &value) {", 0, "(void)value; return std::string();"),
    ("Q", "inline std::string decode_uri_component(const std::string &value) {", 0, "(void)value; return std::string();"),
    ("Q", "inline std::string decode_uri(const std::string &value) {", 0, "(void)value; return std::string();"),
    ("Q", "inline std::string encode_path_component(const std::string &component) {", 0, "(void)component; return std::string();"),
    ("Q", "inline std::string decode_path_component(const std::string &component) {", 0, "(void)component; return std::string();"),
    ("Q", "inline std::string encode_query_component(const std::string &component,", 0, None),
    ("Q", "inline std::string decode_query_component(const std::string &component,", 0, None),
    ("Q", "inline std::string append_query_params(const std::string &path,", 0, None),
    # M: multipart/form-data (server-side streaming parser, client-side serializer)
    ("M", "inline bool parse_multipart_boundary(const std::string &content_type,", 0, None),
    ("M", "inline void parse_disposition_params(const std::string &s, Params &params) {", 0, "(void)s; (void)params;"),
    ("M", "inline bool is_multipart_boundary_chars_valid(const std::string &boundary) {", 0, "(void)boundary; return false;"),
    ("M", "inline std::string escape_multipart_field(const std::string &s,", 0, None),
    ("M", "serialize_multipart_formdata_item_begin(const T &item,", 0, None),
    ("M", "inline std::string serialize_multipart_formdata_item_end() {", 0, "return std::string();"),
    ("M", "serialize_multipart_formdata_finish(const std::string &boundary) {", 0, "(void)boundary; return std::string();"),
    ("M", "serialize_multipart_formdata(const UploadFormDataItems &items,", 0, None),
    ("M", "inline size_t get_multipart_content_length(const UploadFormDataItems &items,", 0, None),
    ("M", "make_multipart_content_provider(const UploadFormDataItems &items,", 0, None),
    ("M", "inline std::string sanitize_filename(const std::string &filename) {", 0, "(void)filename; return std::string();"),
    # R: byte ranges (Range parsing, 206/416, multipart/byteranges, If-Range)
    ("R", "inline void coalesce_ranges(Ranges &ranges, size_t content_length) {", 0, "(void)ranges; (void)content_length;"),
    ("R", "inline bool range_error(Request &req, Response &res) {", 0, "(void)req; (void)res; return false;"),
    ("R", "get_range_offset_and_length(Range r, size_t content_length) {", 0, None),
    ("R", "inline std::string make_content_range_header_field(", 0, None),
    ("R", "bool process_multipart_ranges_data(const Request &req,", 0, None),
    ("R", "inline void make_multipart_ranges_data(const Request &req, Response &res,", 0, None),
    ("R", "inline size_t get_multipart_ranges_data_length(const Request &req,", 0, None),
    ("R", "write_multipart_ranges_data(Stream &strm, const Request &req, Response &res,", 0, None),
    ("R", "inline void Server::apply_ranges(const Request &req, Response &res,", 0, None),
    ("R", "inline bool Server::check_if_range(Request &req, const std::string &etag,", 0, None),
    ("R", "make_range_header(const Ranges &ranges) {", 0, "(void)ranges; return std::make_pair(std::string(), std::string());"),
    # N: content negotiation, quoted strings, conditional requests
    ("N", "extract_media_type(const std::string &content_type,", 0, None),
    ("N", "inline bool parse_quality(const char *b, const char *e, std::string &token,", 0, None),
    ("N", "inline EncodingType encoding_type(const Request &req,\n                                  const std::string &content_type) {", 0, None),
    ("N", "inline std::string remove_quoted_strings(const std::string &s) {", 0, "(void)s; return std::string();"),
    ("N", "inline bool parse_accept_header(const std::string &s,", 0, None),
    ("N", "inline std::string unescape_quoted_pairs(const std::string &s) {", 0, "(void)s; return std::string();"),
    ("N", "inline std::string escape_quoted_pairs(const std::string &s) {", 0, "(void)s; return std::string();"),
    ("N", "inline bool parse_www_authenticate(const Response &res,", 0, None),
    ("N", "inline bool Server::check_if_not_modified(const Request &req, Response &res,", 0, None),
]

# Stubs for multi-line heads whose parameter names we fill in by return type.
RET_STUB = [
    (re.compile(r"\bReadContentResult\b"), "return ReadContentResult::Error;"),
    (re.compile(r"\bssize_t\b"), "return -1;"),
    (re.compile(r"\bstd::pair<size_t, size_t>"), "return std::make_pair(size_t(0), size_t(0));"),
    (re.compile(r"\bsize_t\b"), "return 0;"),
    (re.compile(r"\bstd::string\b"), "return std::string();"),
    (re.compile(r"\bContentProvider\b"), "return ContentProvider();"),
    (re.compile(r"\bEncodingType\b"), "return EncodingType::None;"),
    (re.compile(r"\bbool\b"), "return false;"),
    (re.compile(r"\bvoid\b"), ""),
]


def skip_literal(t, i):
    """t[i] is a quote; return the index after the literal."""
    q = t[i]
    i += 1
    while t[i] != q:
        if t[i] == "\\":
            i += 1
        i += 1
    return i + 1


def match_brace(t, i):
    """t[i] == '{'; return the index of the matching '}'."""
    depth = 0
    while True:
        c = t[i]
        if c in "\"'":
            # raw strings are not used inside the targeted bodies
            if c == "'" and i > 0 and (t[i - 1].isalnum()):   # digit separator like 1'000
                i += 1
                continue
            i = skip_literal(t, i)
            continue
        if t.startswith("//", i):
            i = t.index("\n", i)
            continue
        if t.startswith("/*", i):
            i = t.index("*/", i) + 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1


def body_open(t, i):
    """From the start of a definition head, return the index of the '{' that opens its body."""
    paren = 0
    while True:
        c = t[i]
        if c == "(":
            paren += 1
        elif c == ")":
            paren -= 1
        elif c == "{" and paren == 0:
            return i
        elif c in "\"'" and paren:
            i = skip_literal(t, i)
            continue
        i += 1


def head_start(t, i):
    """Back up from a match to the start of its line, and over a 'template <...>' / return-type line."""
    s = t.rfind("\n", 0, i) + 1
    while True:
        p = t.rfind("\n", 0, s - 1) + 1
        prev = t[p:s - 1]
        if prev.startswith("template") or prev in ("inline bool", "inline std::string", "inline void") \
                or (prev.startswith("inline ") and not prev.rstrip().endswith((";", "}", "{"))):
            s = p
            continue
        return s


def strip(text, keep=()):
    removed = {}
    edits = []
    for area, start, occ, stub in TARGETS:
        if area in keep:
            continue
        idx = -1
        while True:
            idx = text.index(start, idx + 1)
            if text.rfind("\n", 0, idx) + 1 != idx and not text[text.rfind("\n", 0, idx) + 1:idx].startswith(("inline", "template", "bool")):
                continue
            ob = body_open(text, idx)
            if ";" not in text[idx:ob]:
                break
        hs = head_start(text, idx)
        cb = match_brace(text, ob)
        head = text[hs:ob]
        if stub is None:
            for rx, s in RET_STUB:
                ret_part = head.split("(")[0]
                if rx.search(ret_part):
                    stub = s
                    break
        edits.append((ob, cb, stub, area, text[ob + 1:cb]))
    edits.sort()
    for a, b in zip(edits, edits[1:]):
        assert a[1] < b[0], "overlapping targets"
    out, pos = [], 0
    for ob, cb, stub, area, body in edits:
        out.append(text[pos:ob + 1])
        out.append(f"\n  {STUB_NOTE}\n  {stub}\n" if stub else f"\n  {STUB_NOTE}\n")
        pos = cb
        removed[area] = removed.get(area, 0) + sum(1 for l in body.split("\n") if l.strip())
    out.append(text[pos:])
    return "".join(out), removed


RANGE_TRY = """#ifdef CPPHTTPLIB_NO_EXCEPTIONS
inline bool parse_range_header(const std::string &s, Ranges &ranges) {
#else
inline bool parse_range_header(const std::string &s, Ranges &ranges) try {
#endif
"""


def strip_range_header(text):
    a = text.index(RANGE_TRY)
    end_marker = "} catch (...) { return false; }\n#endif\n"
    b = text.index(end_marker, a) + len(end_marker)
    body = text[a + len(RANGE_TRY):b]
    n = sum(1 for l in body.split("\n") if l.strip()) - 5
    stub = ("inline bool parse_range_header(const std::string &s, Ranges &ranges) {\n"
            f"  {STUB_NOTE}\n  (void)s; (void)ranges;\n  return false;\n}}\n")
    return text[:a] + stub + text[b:], n


FDP_START = "class FormDataParser {\npublic:\n  FormDataParser() = default;\n"
FDP_STUB = """class FormDataParser {
public:
  FormDataParser() = default;

  void set_boundary(std::string &&boundary) {
    %s
    (void)boundary;
  }

  bool is_valid() const { return false; }

  bool parse(const char *buf, size_t n, const FormDataHeader &header_callback,
             const ContentReceiver &content_callback) {
    (void)buf; (void)n; (void)header_callback; (void)content_callback;
    return false;
  }
};
""" % STUB_NOTE


def strip_form_parser(text):
    a = text.index(FDP_START)
    b = text.index("\n};\n", a) + 4
    n = sum(1 for l in text[a:b].split("\n") if l.strip())
    return text[:a] + FDP_STUB + text[b:], n - 12


def main():
    src, dst = sys.argv[1], sys.argv[2]
    keep = ()
    if "--keep" in sys.argv:
        keep = tuple(sys.argv[sys.argv.index("--keep") + 1].split(","))
    text = open(src).read()
    text, removed = strip(text, keep)
    if "R" not in keep:
        text, n = strip_range_header(text)
        removed["R"] = removed.get("R", 0) + n
    if "M" not in keep:
        text, n = strip_form_parser(text)
        removed["M"] = removed.get("M", 0) + n
    open(dst, "w").write(text)
    if "--report" in sys.argv:
        print(json_dump(removed))


def json_dump(d):
    import json
    return json.dumps({"total": sum(d.values()), **dict(sorted(d.items()))})


if __name__ == "__main__":
    main()
