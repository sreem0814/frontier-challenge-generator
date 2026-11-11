"""Build the case list (inputs and flatc command lines) for one split.

    python3 casegen.py <seed> <scale> <out.json> [--corpus /w/up/tests]

Each case: {"id", "b": bucket, "files": {relpath: text}, "argv": [...], "pre": [...]}; "pre" steps run the
reference flatc at freeze time to produce derived inputs (binaries, binary schemas) that become input files of
the final case. freeze.py runs every case with the reference, records the expected outcome and drops cases
the stub would pass.
"""
import copy
import glob
import json
import os
import random
import sys

import protogen
import schemagen as sg

LANGS = {
    "cpp": ["--gen-object-api", "--gen-mutable", "--gen-compare", "--gen-name-strings", "--reflect-names",
            "--reflect-types", "--scoped-enums", "--no-prefix", "--gen-nullable", "--gen-generated",
            "--bfbs-gen-embed", "--no-includes", "--gen-all", "--cpp-std=c++17", "--cpp-std=c++0x",
            "--no-emit-min-max-enum-values", "--cpp-field-case-style", "--gen-absl-hash",
            "--force-empty"],
    "python": ["--gen-object-api", "--python-typing", "--gen-onefile", "--python-no-type-prefix-suffix",
               "--gen-all"],
    "rust": ["--gen-object-api", "--rust-serialize", "--gen-all", "--rust-module-root-file", "--gen-name-strings"],
    "ts": ["--gen-object-api", "--gen-all", "--ts-no-import-ext", "--gen-mutable", "--ts-omit-entrypoint"],
    "go": ["--gen-object-api", "--gen-onefile"],
    "java": ["--gen-object-api", "--gen-generated", "--gen-mutable", "--java-checkerframework",
             "--gen-nullable"],
    "csharp": ["--gen-object-api", "--gen-onefile", "--cs-global-alias", "--gen-mutable"],
    "swift": ["--gen-object-api", "--gen-json-emit", "--swift-implementation-only", "--gen-mutable"],
    "dart": ["--gen-object-api"],
    "kotlin": ["--gen-jvmstatic"],
    "kotlin-kmp": [],
    "php": [],
    "lobster": [],
    "jsonschema": [],
    "nim": [],
}
LANG_W = {"cpp": 6, "python": 3, "rust": 3, "ts": 3, "go": 2, "java": 2, "csharp": 2, "swift": 2, "dart": 1,
          "kotlin": 1, "kotlin-kmp": 1, "php": 1, "lobster": 1, "jsonschema": 2, "nim": 1}


class Gen:
    def __init__(self, seed, scale, corpus):
        self.r = random.Random(seed)
        self.seed = seed
        self.scale = scale
        self.cases = []
        self.n = 0
        self.corpus = self.load_corpus(corpus) if corpus else []

    def add(self, b, files, argv, pre=None, note=""):
        self.n += 1
        c = {"id": "c%05d" % self.n, "b": b, "files": files, "argv": argv}
        if pre:
            c["pre"] = pre
        if note:
            c["note"] = note
        self.cases.append(c)

    # ------------------------------------------------------------ inputs

    def load_corpus(self, root):
        """Upstream test schemas with the files they include, as {name: text} worlds."""
        out = []
        skip = ("prototest", "fuzzer", "bazel", "nim", "swift", "ts/", "rust_", "dart", "union_underlying")
        for p in sorted(glob.glob(os.path.join(root, "**", "*.fbs"), recursive=True)):
            rel = os.path.relpath(p, root)
            if any(s in rel for s in skip):
                continue
            files = {}
            base = os.path.dirname(p)
            todo = [(os.path.basename(p), p)]
            ok = True
            while todo:
                name, path = todo.pop()
                if name in files:
                    continue
                try:
                    txt = open(path, encoding="utf-8").read()
                except (OSError, UnicodeDecodeError):
                    ok = False
                    break
                files[name] = txt
                for ln in txt.splitlines():
                    ln = ln.strip()
                    if ln.startswith("include ") and '"' in ln:
                        inc = ln.split('"')[1]
                        cand = [os.path.join(base, inc), os.path.join(root, inc),
                                os.path.join(root, "include_test", inc), os.path.join(base, "include_test", inc)]
                        hit = [c for c in cand if os.path.isfile(c)]
                        if not hit:
                            ok = False
                            break
                        todo.append((inc, hit[0]))
            if ok and sum(len(t) for t in files.values()) < 60000:
                out.append({"main": os.path.basename(p), "files": files, "rel": rel})
        return out

    def world(self, size=None):
        w = sg.mk_world(self.r, size=size)
        files = sg.emit_world(w, self.r)
        return w, files

    def schema_input(self, allow_corpus=True):
        """(files, main, world-or-None)"""
        if allow_corpus and self.corpus and self.r.random() < 0.18:
            c = self.r.choice(self.corpus)
            return dict(c["files"]), c["main"], None
        w, files = self.world()
        return files, "schema.fbs", w

    # ------------------------------------------------------------ buckets

    def bfbs_case(self):
        files, main, _w = self.schema_input()
        flags = []
        q = self.r.random()
        if q < 0.45:
            flags = ["--bfbs-comments", "--bfbs-builtins"]
        elif q < 0.6:
            flags = ["--bfbs-comments"]
        elif q < 0.7:
            flags = ["--bfbs-builtins"]
        if self.r.random() < 0.25:
            flags += ["--bfbs-filenames", "."]
        if self.r.random() < 0.1:
            flags += [self.r.choice(["--cpp", "--python", "--ts", "--rust", "--java"])]
        self.add("schema_bfbs", files, ["-b", "--schema"] + flags + ["-o", "out", main])

    def codegen_case(self):
        files, main, w = self.schema_input()
        langs = list(LANG_W)
        lang = self.r.choices(langs, [LANG_W[x] for x in langs])[0]
        opts = []
        for o in LANGS[lang]:
            if self.r.random() < 0.3:
                opts.append(o)
                if o == "--cpp-field-case-style":
                    opts.append(self.r.choice(["upper", "lower", "unchanged"]))
        if "--cs-gen-json-serializer" in opts and "--gen-object-api" not in opts:
            opts.append("--gen-object-api")
        extra = []
        if w is not None and any(d["kind"] == "service" for d in w["defs"]) and lang in (
                "cpp", "go", "python", "java", "swift", "ts") and self.r.random() < 0.6:
            extra.append("--grpc")
        if self.r.random() < 0.08:
            extra.append("--no-warnings")
        argv = ["--" + lang] + opts + extra + ["-o", "out", main]
        if self.r.random() < 0.08 and lang in ("cpp", "ts", "python"):
            # two generators in one run
            other = self.r.choice([x for x in ("cpp", "ts", "python", "rust", "jsonschema") if x != lang])
            argv = ["--" + other] + argv
        self.add("codegen", files, argv)

    def json_case(self):
        w, files = self.world(size=self.r.choice([2, 3, 4, 6, 8]))
        strict = self.r.random() < 0.2
        data = sg.gen_json(w, self.r, strict=strict)
        flags = []
        if strict:
            flags.append("--strict-json")
        if self.r.random() < 0.15:
            flags.append("--force-defaults")
        if self.r.random() < 0.1:
            flags.append("--size-prefixed")
        if self.r.random() < 0.1:
            flags.append("--allow-non-utf8")
        if self.r.random() < 0.08:
            flags.append("--natural-utf8")
        if self.r.random() < 0.12:
            flags.append("--unknown-json")
            data = data.replace("{", '{"zz_unknown_%d": [1, {"a": "b"}, null], ' % self.r.randint(0, 9), 1) \
                if data.lstrip().startswith("{") and len(data.strip()) > 2 else data
        if w["files"][0].get("root_type") is None or self.r.random() < 0.05:
            tabs = [d for d in w["defs"] if d["kind"] == "table"]
            flags += ["--root-type", self.r.choice(tabs)["q"]]
        name = self.r.choice(["data.json", "doc.json", "input.json"])
        files[name] = data
        self.add("json_binary", files, ["-b"] + flags + ["-o", "out", "schema.fbs", name])

    def flex_case(self):
        v = sg.rand_any_json(self.r, 0)
        if not isinstance(v, list):
            v = sg.Obj([("value", v)])
        text = sg.dump_json(v, self.r, self.r.random() < 0.9)
        files = {"flex.json": text + "\n"}
        flags = ["--flexbuffers"]
        if self.r.random() < 0.2:
            flags.append("--strict-json")
        self.add("json_binary", files, ["-b"] + flags + ["-o", "out", "flex.json"])

    def json_text_case(self):
        w, files = self.world(size=self.r.choice([2, 3, 4, 6]))
        data = sg.gen_json(w, self.r)
        files["data.json"] = data
        rt = []
        if w["files"][0].get("root_type") is None:
            tabs = [d for d in w["defs"] if d["kind"] == "table"]
            rt = ["--root-type", w["root"]["q"]]
        q = self.r.random()
        flags = [f for f in ["--strict-json", "--defaults-json", "--natural-utf8", "--json-nested-bytes"]
                 if self.r.random() < 0.3]
        if q < 0.45:
            # binary -> JSON: the binary comes from the reference
            sp = self.r.random() < 0.1
            pre = [{"argv": ["-b"] + rt + (["--size-prefixed"] if sp else []) + ["-o", "pre", "schema.fbs",
                                                                                   "data.json"],
                    "take": {"pre/data.%s" % (w["files"][0].get("file_extension") or "bin"): "data.bin"}}]
            raw = ["--raw-binary"] if (not w["files"][0].get("file_identifier") or self.r.random() < 0.5) else []
            argv = ["--json"] + flags + rt + raw + (["--size-prefixed"] if sp else []) + \
                   ["-o", "out", "schema.fbs", "--", "data.bin"]
            del files["data.json"]
            files["data.json@pre"] = data
            self.add("json_text", files, argv, pre=pre)
        elif q < 0.85:
            # JSON -> JSON
            self.add("json_text", files, ["--json"] + flags + rt + ["-o", "out", "schema.fbs", "data.json"])
        else:
            pre = [{"argv": ["-b"] + rt + ["-o", "pre", "schema.fbs", "data.json"],
                    "take": {"pre/data.%s" % (w["files"][0].get("file_extension") or "bin"): "data.bin"}}]
            files["data.json@pre"] = files.pop("data.json")
            argv = ["--annotate", "schema.fbs"] + rt + ["-o", "out", "--", "data.bin"]
            self.add("json_text", files, argv, pre=pre)

    def proto_case(self):
        r = self.r
        files = {}
        imports = []
        if r.random() < 0.2:
            t, _ = protogen.gen_proto(r)
            files["imported.proto"] = t
            imports.append("imported.proto")
        t, _types = protogen.gen_proto(r, imports)
        if r.random() < 0.18:
            t = protogen.proto_mutate(r, t)
        files["model.proto"] = t
        flags = []
        if r.random() < 0.3:
            flags.append("--oneof-union")
        if r.random() < 0.3:
            flags.append("--keep-proto-id")
            if r.random() < 0.5:
                flags += ["--proto-id-gap", r.choice(["nop", "warn", "error"])]
        if r.random() < 0.15:
            flags += ["--proto-namespace-suffix", r.choice(["fbs", "flat", "gen.v1"])]
        if r.random() < 0.1:
            flags.append("--no-warnings")
        if imports and r.random() < 0.5:
            flags.append("--gen-all")
        self.add("proto", files, ["--proto"] + flags + ["-o", "out", "model.proto"])

    def bfbs_input_case(self):
        w, files = self.world(size=self.r.choice([2, 3, 4, 6, 8]))
        pre_flags = ["--bfbs-comments", "--bfbs-builtins"] if self.r.random() < 0.6 else []
        if self.r.random() < 0.3:
            pre_flags += ["--bfbs-filenames", "."]
        pre = [{"argv": ["-b", "--schema"] + pre_flags + ["-o", "pre", "schema.fbs"],
                "take": {"pre/schema.bfbs": "model.bfbs"}}]
        src = {k + "@pre": v for k, v in files.items()}
        q = self.r.random()
        if q < 0.55:
            lang = self.r.choice(["cpp", "cpp", "python", "ts", "rust", "java", "csharp", "go", "swift",
                                  "jsonschema", "dart", "kotlin", "php"])
            opts = [o for o in LANGS[lang] if self.r.random() < 0.25 and o not in ("--bfbs-gen-embed",
                                                                                 "--cpp-field-case-style")]
            self.add("bfbs_input", src, ["--" + lang] + opts + ["-o", "out", "model.bfbs"], pre=pre)
        elif q < 0.8:
            data = sg.gen_json(w, self.r)
            src["data.json"] = data
            rt = [] if w["files"][0].get("root_type") is not None else ["--root-type", w["root"]["q"]]
            self.add("bfbs_input", src, ["-b"] + rt + ["-o", "out", "model.bfbs", "data.json"], pre=pre)
        else:
            self.add("bfbs_input", src, ["-b", "--schema"] + (["--bfbs-comments"] if self.r.random() < 0.5
                                                               else []) + ["-o", "out", "model.bfbs"], pre=pre)

    def conform_case(self):
        w, files = self.world(size=self.r.choice([2, 3, 4, 6]))
        base = files
        w2 = evolve(self.r, w)
        new = sg.emit_world(w2, self.r)
        allf = {"base/" + k: v for k, v in base.items()}
        allf.update({"new/" + k: v for k, v in new.items()})
        if self.r.random() < 0.25:
            pre = [{"argv": ["-b", "--schema", "-o", "pre", "base/schema.fbs"],
                    "take": {"pre/schema.bfbs": "base.bfbs"}}]
            allf = {k + ("@pre" if k.startswith("base/") else ""): v for k, v in allf.items()}
            self.add("conform", allf, ["--conform", "base.bfbs", "new/schema.fbs"], pre=pre)
        else:
            self.add("conform", allf, ["--conform", "base/schema.fbs", "new/schema.fbs"])

    def diag_case(self):
        q = self.r.random()
        if q < 0.6:
            w, files = self.world(size=self.r.choice([1, 2, 3, 4, 6]))
            txt = files["schema.fbs"]
            files["schema.fbs"] = mutate_schema(self.r, txt, w)
            lang = self.r.choice(["-b", "-b", "--cpp", "--rust", "--python", "--ts", "--go", "--java", "--swift",
                                  "--csharp", "--dart", "--lobster", "--php", "--jsonschema", "--kotlin"])
            argv = [lang] + (["--schema"] if lang == "-b" else []) + ["-o", "out", "schema.fbs"]
            if self.r.random() < 0.05:
                argv.insert(1, "--warnings-as-errors")
            self.add("diag", files, argv)
        elif q < 0.85:
            w, files = self.world(size=self.r.choice([2, 3, 4]))
            data = sg.gen_json(w, self.r)
            data = mutate_json(self.r, data, w)
            files["data.json"] = data
            rt = [] if w["files"][0].get("root_type") is not None else ["--root-type", w["root"]["q"]]
            extra = ["--strict-json"] if self.r.random() < 0.2 else []
            self.add("diag", files, ["-b"] + extra + rt + ["-o", "out", "schema.fbs", "data.json"])
        else:
            # warnings and language feature checks on valid schemas
            w, files = self.world(size=self.r.choice([3, 4, 6, 8]))
            lang = self.r.choice(["--go", "--python", "--lobster", "--dart", "--php", "--kotlin", "--java",
                                  "--csharp", "--lua"])
            argv = [lang, "-o", "out", "schema.fbs"]
            if self.r.random() < 0.3:
                argv.insert(1, "--warnings-as-errors")
            if self.r.random() < 0.2:
                argv.insert(1, "--require-explicit-ids")
            self.add("diag", files, argv)

    def build(self):
        s = self.scale
        plan = [(self.bfbs_case, 420), (self.codegen_case, 560), (self.json_case, 420), (self.flex_case, 60),
                (self.json_text_case, 330), (self.proto_case, 300), (self.bfbs_input_case, 220),
                (self.conform_case, 220), (self.diag_case, 700)]
        for fn, n in plan:
            for _ in range(max(1, int(round(n * s)))):
                fn()
        return self.cases


# ---------------------------------------------------------------- mutations

def mutate_schema(r, txt, w):
    lines = txt.split("\n")
    fields = [i for i, l in enumerate(lines) if ":" in l and l.strip().endswith(";") and not l.strip().startswith(
        ("//", "root_type", "file_", "include", "namespace", "attribute"))]
    tdefs = [d for d in w["defs"] if d["kind"] == "table"]
    sdefs = [d for d in w["defs"] if d["kind"] == "struct"]
    edefs = [d for d in w["defs"] if d["kind"] == "enum"]
    ops = []

    def op_undefined():
        i = r.choice(fields)
        a, b = lines[i].split(":", 1)
        lines[i] = a + ": " + r.choice(["Missing", "ns.Missing", "[Missing]", "Unknown.Type"]) + ";"

    def op_dup_field():
        i = r.choice(fields)
        lines.insert(i + 1, lines[i])

    def op_drop_semicolon():
        i = r.choice(fields)
        lines[i] = lines[i].rstrip(";")

    def op_struct_bad():
        idx = [i for i, l in enumerate(lines) if l.startswith("struct ")]
        if not idx:
            return op_token()
        lines.insert(idx[0] + 1, r.choice(["  s: string;", "  v: [int];", "  o: int = null;", "  d: int (deprecated);",
                                           "  t: %s;" % (tdefs[0]["q"] if tdefs else "Nope"), "  k: int = 5;",
                                           "  a: [int:0];", "  z: bool (key);"]))

    def op_table_bad():
        idx = [i for i, l in enumerate(lines) if l.startswith("table ")]
        if not idx:
            return op_token()
        cand = ["  a: [int:3];", "  b: [[int]];", "  c: int (required);", "  d: string = 5;", "  e: byte = 300;",
                "  f: ubyte = -1;", "  g: float = abc;", "  h: [ubyte] (nested_flatbuffer: \"Nope\");",
                "  i: [int] (flexbuffer);", "  j: string (hash: \"fnv1a_32\");",
                "  k: uint (hash: \"md5\");", "  l: int (id: -1);", "  m: int (unknown_attr);",
                "  n: int (force_align: 8);", "  o: [string] = [\"a\"];", "  p: int (key); q: int (key);",
                "  r: int = null (required);", "  s: bool = 2;", "  t: [int] (vector64, offset64);",
                "  u: string (offset64);", "  v: double = 1e400;", "  w: int (deprecated, deprecated);",
                "  x: int = 0x;", "  y: short = 0x8000;", "  z: long = 9223372036854775808;",
                "  aa: ulong = -0;", "  bb: int = 1.5;", "  cc: float = 0x1p;", "  dd: string (shared, key);",
                "  ee: [ubyte] (nested_flatbuffer: \"%s\", flexbuffer);" % (tdefs[0]["q"] if tdefs else "X"),
                "  ff: int (cpp_type: \"T\");", "  gg: string = \"x\" (required);", "  hh: int = +;",
                "  ii : int = 1 2;", "  jj: int (id: 99999);", "  kk: [int] = [];", "  ll: string = \"\";"]
        if edefs:
            e = r.choice(edefs)
            cand += ["  ee2: %s = Nope;" % e["q"], "  ee3: %s = 123456;" % e["q"], "  ee4: [%s] = []; " % e["q"],
                     "  ee5: %s (key);" % e["q"]]
        lines.insert(r.choice(idx) + 1, r.choice(cand))

    def op_enum_bad():
        if not [l for l in lines if l.startswith("enum ")]:
            lines.insert(0, r.choice(["enum E : float { A }", "enum E : byte { A = 200 }", "enum E : int { }",
                                      "enum E : ubyte (bit_flags) { A = 9 }", "enum E : int { A = 2, B = 1 }",
                                      "enum E : int { A, A }", "enum E { A }", "enum E : string { A }",
                                      "enum E : int (bit_flags) { A }", "union U { }", "union U { int }",
                                      "enum E : ubyte (force_align: 4) { A }", "union U : byte { X }"]))
            return
        idx = [i for i, l in enumerate(lines) if l.startswith("enum ")]
        i = r.choice(idx)
        q = r.random()
        if q < 0.3:
            lines[i] = lines[i].replace(":", ": float", 1).replace(": float " + lines[i].split(":")[1].split()[0],
                                                                    ": float", 1)
        elif q < 0.6:
            lines.insert(i + 1, "  Dup%d = -9999999999," % r.randint(0, 9))
        else:
            lines.insert(i + 1, "  " + r.choice(["A = 1, A = 2,", "Z = 5, Y = 3,", "= 4,", "Q = R,"]))

    def op_root_bad():
        lines.append(r.choice(["root_type Missing;", "root_type %s;" % (sdefs[0]["q"] if sdefs else "int"),
                               'file_identifier "ABC";', 'file_identifier "ABCDE";', "root_type;",
                               'file_extension "";', "root_type %s.%s;" % ("x", "Y")]))

    def op_token():
        pos = r.randrange(len(txt) + 1)
        junk = r.choice(["@", "{", "}", ";", "\"unterminated", "/*", "table", "0x", "'", "\\", "\u00e9", "( id: )",
                         "namespace ;", "include \"nope.fbs\";", "attribute;", "rpc_service S { M(X):Y; }",
                         "struct S {}", "table {}", "enum : int {}", "\t\x01", "union U { A }", "namespace a..b;"])
        return txt[:pos] + junk + txt[pos:]

    def op_order():
        lines.insert(r.randrange(len(lines)), r.choice(['include "late.fbs";', "native_include 3;",
                                                        "attribute \"priority\";", "namespace 3;"]))

    def op_service():
        lines.append(r.choice(["rpc_service S { Call(Missing):Missing; }",
                               "rpc_service S { Call(%s):%s; }" % ((sdefs[0]["q"],) * 2 if sdefs else ("int", "int")),
                               "rpc_service S { }", "rpc_service S { A(T)T; }",
                               "rpc_service S { A(%s):%s (streaming: \"maybe\"); }" % ((tdefs[0]["q"],) * 2
                                                                                      if tdefs else ("X", "X"))]))

    ops = [op_undefined, op_dup_field, op_drop_semicolon, op_struct_bad, op_table_bad, op_table_bad, op_table_bad,
           op_enum_bad, op_root_bad, op_token, op_token, op_order, op_service]
    if not fields:
        ops = [op_token, op_enum_bad, op_root_bad, op_table_bad]
    op = r.choice(ops)
    res = op()
    if isinstance(res, str):
        return res
    return "\n".join(lines)


def mutate_json(r, data, w):
    q = r.random()
    if q < 0.2:
        return data.replace("{", '{"no_such_field": 1, ', 1)
    if q < 0.35:
        pos = r.randrange(len(data) + 1)
        return data[:pos] + r.choice(["}", "]", ",", ":", "\"", "tru", "0x", "[", "{", "\\u12", "@"]) + data[pos:]
    if q < 0.5:
        return data.replace(": ", ": " + r.choice(["\"str\"", "[1]", "{}", "1e999", "99999999999999999999",
                                                     "-1", "true", "null", "\"\\ud800\""]) + " , \"x\": ", 1)
    if q < 0.6:
        return data + r.choice(["{}", "x", "\n// trailing\n", ","])
    if q < 0.7:
        return data.replace("_type\": \"", "_type\": \"Nope", 1) if "_type" in data else data[:-3]
    if q < 0.8:
        return r.choice(["", "[]", "null", "{", "{\"a\":}", "42", "\"s\""])
    if q < 0.9:
        # deep nesting and large vectors
        return data.replace("[]", "[" + ",".join(["0"] * r.randint(50, 300)) + "]", 1) if "[]" in data else \
            "{" * 70 + "}" * 70
    return data.replace("\"", "'", 2)


def evolve(r, w):
    """A changed copy of a world for the conform check: compatible or not."""
    w2 = copy.deepcopy(w)
    w2["c"].r = r
    tabs = [d for d in w2["defs"] if d["kind"] == "table" and d["fields"]]
    enums = [d for d in w2["defs"] if d["kind"] == "enum" and d["values"]]
    structs = [d for d in w2["defs"] if d["kind"] == "struct"]
    unions = [d for d in w2["defs"] if d["kind"] == "union"]
    for _ in range(r.choice([1, 1, 1, 2, 3])):
        q = r.random()
        if q < 0.2 and tabs:
            t = r.choice(tabs)
            f = sg.gen_field_named(w2["c"], t)
            f["type"] = ("scalar", r.choice(list(sg.SCALARS)))
            t["fields"].append(f)          # compatible: appended
        elif q < 0.3 and tabs:
            t = r.choice(tabs)
            f = sg.gen_field_named(w2["c"], t)
            f["type"] = ("string",)
            t["fields"].insert(r.randrange(len(t["fields"]) + 1), f)
        elif q < 0.4 and tabs:
            t = r.choice(tabs)
            t["fields"].pop(r.randrange(len(t["fields"])))
        elif q < 0.5 and tabs:
            t = r.choice(tabs)
            f = r.choice(t["fields"])
            f["type"] = ("scalar", r.choice(list(sg.SCALARS)))
            f.pop("default", None)
        elif q < 0.58 and tabs:
            t = r.choice(tabs)
            f = r.choice(t["fields"])
            f["name"] = f["name"] + "_renamed"
        elif q < 0.66 and tabs:
            t = r.choice(tabs)
            f = r.choice(t["fields"])
            if f["type"][0] == "scalar" and sg.SCALARS[f["type"][1]][0] in "iu":
                f["default"] = str(r.randint(1, 9))
            else:
                f["attrs"] = list(f["attrs"]) + [("deprecated", None)]
        elif q < 0.74 and enums:
            e = r.choice(enums)
            last = e["values"][-1]
            if not e.get("flags"):
                e["values"].append({"name": "Added" + str(r.randint(0, 99)), "doc": [], "attrs": [],
                                    "v": last["v"] + 1})
            else:
                e["values"].pop()
        elif q < 0.8 and enums:
            e = r.choice(enums)
            v = r.choice(e["values"])
            v["name"] = v["name"] + "Renamed"
        elif q < 0.86 and structs:
            s = r.choice(structs)
            s["fields"].append({"name": "extra" + str(r.randint(0, 9)), "doc": [], "attrs": [],
                                "type": ("scalar", "int")})
        elif q < 0.92 and unions:
            u = r.choice(unions)
            if u["members"] and r.random() < 0.5:
                u["members"].pop(0)
            elif tabs:
                t = r.choice(tabs)
                if t not in [m["t"] for m in u["members"]]:
                    u["members"].append({"t": t, "alias": None, "doc": []})
        elif tabs:
            t = r.choice(tabs)
            f = r.choice(t["fields"])
            f["attrs"] = [a for a in f["attrs"] if a[0] != "deprecated"] + ([("required", None)]
                                                                            if r.random() < 0.5 else [])
    return w2


def main():
    seed, scale, out = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
    corpus = sys.argv[sys.argv.index("--corpus") + 1] if "--corpus" in sys.argv else None
    g = Gen(seed, scale, corpus)
    cases = g.build()
    with open(out, "w") as f:
        json.dump(cases, f)
    counts = {}
    for c in cases:
        counts[c["b"]] = counts.get(c["b"], 0) + 1
    print(len(cases), counts, "corpus", len(g.corpus))


if __name__ == "__main__":
    main()
