"""Replace the implementation files of the four components with compiling stubs.

usage: python3 -I make_stubs.py <tree>

Each listed .cpp keeps its licence header, its #include lines and the signature of every externally visible
function, constructor and destructor; every body becomes a placeholder that returns an error or an empty value.
File-local helpers (static functions, anonymous namespaces, local types, tables) are dropped.
"""
import re
import sys

tree = sys.argv[1]
FILES = """
src/lib/core/TLVCircularBuffer.cpp src/lib/core/TLVDebug.cpp src/lib/core/TLVReader.cpp src/lib/core/TLVTags.cpp
src/lib/core/TLVUpdater.cpp src/lib/core/TLVUtilities.cpp src/lib/core/TLVVectorWriter.cpp src/lib/core/TLVWriter.cpp
src/transport/raw/MessageHeader.cpp
src/setup_payload/Base38Encode.cpp src/setup_payload/Base38Decode.cpp
src/setup_payload/ManualSetupPayloadGenerator.cpp src/setup_payload/ManualSetupPayloadParser.cpp
src/setup_payload/QRCodeSetupPayloadGenerator.cpp src/setup_payload/QRCodeSetupPayloadParser.cpp
src/setup_payload/SetupPayload.cpp src/setup_payload/AdditionalDataPayloadParser.cpp
src/lib/support/jsontlv/TlvJson.cpp src/lib/support/jsontlv/TlvToJson.cpp src/lib/support/jsontlv/JsonToTlv.cpp
src/lib/support/jsontlv/TextFormat.cpp
""".split()

# functions that upstream compiles only under options this build leaves off, or that take file-local types
DROP = ["operator<<", "TLVWriterPutcharCB", "KeyContext", "ForTest"]

RET = [
    (r"^CHIP_ERROR$", "return CHIP_ERROR_NOT_IMPLEMENTED;"),
    (r"^void$", ""),
    (r"^bool$", "return false;"),
    (r"\*$", "return nullptr;"),
    (r"^(u?int(8|16|32|64)_t|size_t|int|unsigned|uint)$", "return 0;"),
    (r"^TLVType$", "return kTLVType_NotSpecified;"),
    (r"^TLVElementType$", "return TLVElementType::NotSpecified;"),
    (r"StringBuilderBase &$", "return out;"),
]


def strip_comments_keep_layout(src):
    """Blank out comments (keeping newlines) so brace matching ignores them."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join(c if c == "\n" else " " for c in src[i:j]))
            i = j
        elif src[i] in "\"'":
            q = src[i]
            j = i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


def stub_file(path):
    src = open(path).read()
    clean = strip_comments_keep_layout(src)
    lines = src.split("\n")
    clines = clean.split("\n")
    # licence header: the first comment block
    m = re.match(r"\s*/\*.*?\*/\n", src, re.S)
    header = m.group(0) if m else ""
    includes = [l for l in lines if l.startswith("#include") or l.startswith("#if") or l.startswith("#endif")
                or l.startswith("#else") or l.startswith("#define") or l.startswith("#pragma")]
    # keep only the include block and preprocessor guards that wrap includes
    includes = [l for l in includes if l.startswith("#include")]
    out = [header.rstrip("\n"), ""] + includes + [""]
    ns_stack = []
    i = 0
    pending_sig = []
    anon_depth = 0
    local_types = []
    while i < len(clines):
        cl = clines[i].rstrip()
        s = cl.strip()
        if re.match(r"^namespace\s*\{", s) or s == "namespace":
            anon_depth += 1
            ns_stack.append("anon")
            i += 1
            continue
        mns = re.match(r"^namespace\s+([\w:]+)\s*\{", s)
        if mns:
            ns_stack.append(mns.group(1))
            if anon_depth == 0:
                out.append(f"namespace {mns.group(1)} {{")
            i += 1
            pending_sig = []
            continue
        if re.match(r"^\}\s*(//.*)?;?$", s) and cl.startswith("}") and ns_stack and not pending_sig:
            k = ns_stack.pop()
            if k == "anon":
                anon_depth -= 1
            elif anon_depth == 0:
                out.append(f"}} // namespace {k}")
            i += 1
            continue
        if cl == "{":
            # a body at column 0: function, or a type definition
            sig = " ".join(x.strip() for x in pending_sig).strip()
            depth, j = 0, i
            while True:
                depth += clines[j].count("{") - clines[j].count("}")
                if depth == 0:
                    break
                j += 1
            end_line = clines[j].strip()
            is_func = "(" in sig and not sig.startswith(("struct", "class", "enum", "union"))
            mt = re.match(r"^(struct|class|union)\s+(\w+)", sig)
            if mt:
                local_types.append(mt.group(2))
            if any(f"{t}::" in sig or f"{t} " in sig.split("(")[0] for t in local_types):
                is_func = False
            sig = re.sub(r"\bNO_INLINE\s+", "", sig)
            keep = is_func and anon_depth == 0 and not re.match(r"^(static|template|inline)\b", sig) and \
                not any(d in sig for d in DROP)
            if keep:
                body = stub_body(sig)
                out.append(sig)
                out.append("{")
                if body:
                    out.append("    " + body)
                out.append("}")
                out.append("")
            i = j + 1
            pending_sig = []
            continue
        if "{" in s and s.endswith("}") and s.count("{") == s.count("}") and anon_depth == 0 and not s.startswith("namespace"):
            # a one-line definition such as a constructor with an empty body
            sig = " ".join([x.strip() for x in pending_sig] + [lines[i].strip()])
            sig = sig[:sig.index("{")].strip()
            sig = re.sub(r"\bNO_INLINE\s+", "", sig)
            if "(" in sig and not re.match(r"^(static|template|inline)\b", sig) and not any(d in sig for d in DROP) \
                    and not any(f"{t}::" in sig for t in local_types):
                body = stub_body(sig) if ") :" not in sig and "):" not in sig else ""
                out.append(sig)
                out.append("{")
                if body:
                    out.append("    " + body)
                out.append("}")
                out.append("")
            pending_sig = []
            i += 1
            continue
        if s == "" or s.startswith("#"):
            pending_sig = []
            i += 1
            continue
        if s.endswith("= default;") and "::" in s and anon_depth == 0:
            out.append(" ".join([x.strip() for x in pending_sig] + [s]))
            out.append("")
            pending_sig = []
            i += 1
            continue
        if s.endswith(";") and not pending_sig:
            # declarations, using-directives and constants at namespace scope
            if anon_depth == 0 and re.match(r"^(using|constexpr|const|static constexpr|extern)\b", s) and "(" not in s:
                if s.startswith("using"):
                    out.append(s)
            i += 1
            continue
        if s.endswith(";") and pending_sig:
            pending_sig = []
            i += 1
            continue
        pending_sig.append(lines[i] if cl.strip() else "")
        i += 1
    text = "\n".join(out).rstrip() + "\n"
    open(path, "w").write(text)


def stub_body(sig):
    name_part = sig.split("(")[0].strip()
    m = re.match(r"^(.*?)([\w:~]+)$", name_part)
    ret = m.group(1).strip() if m else ""
    ret = re.sub(r"\b(DLL_EXPORT|extern|virtual)\b", "", ret).strip()
    if ret == "" or "::~" in name_part:
        return ""
    for pat, body in RET:
        if re.search(pat, ret):
            return body
    return "return {};"


for rel in FILES:
    stub_file(f"{tree}/{rel}")
print("stubbed", len(FILES), "files")
