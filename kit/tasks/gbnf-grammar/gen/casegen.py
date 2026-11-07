"""casegen.py: generates the grammar and JSON-schema cases (authoring tool; never ships).

  casegen.py stage1 --seed S --scale X --prefix P --dir DIR
      DIR/specs.json      every case's inputs
      DIR/walk.txt        walker requests (random accepted strings per grammar)
      DIR/lconv.txt       L cases for the reference runner (reference grammar text per schema)
  casegen.py stage2 --dir DIR
      reads DIR/walk.out and DIR/lconv.out, adds mutated strings, writes
      DIR/cases.txt       the case file for case_runner
      DIR/lmatch.txt      M cases (reference grammar + strings) for the reference matcher: labels of L strings
      DIR/lstrings.json   {case id: [hex strings]}
"""
import argparse
import json
import os
import random
import sys

# ------------------------------------------------------------------ helpers


def hx(s):
    return s.encode("utf-8", "surrogatepass").hex() if isinstance(s, str) else s.hex()


def unhx(h):
    return bytes.fromhex(h)


NAMES = ["expr", "term", "factor", "item", "list", "ws", "value", "pair", "key", "num", "digit", "word", "ident",
         "sep", "tail", "head", "body", "atom", "seq", "opt", "block", "line", "char", "esc", "str", "obj", "arr",
         "elem", "field", "Name", "X", "q", "a1", "b-2", "rule-x", "kw", "op", "sign", "frac", "exp"]
LIT_CHARS = list("abcxyzQRS0179 _-.,:;!?=+*/()[]{}<>@#$%&") + ["\"", "\\", "\n", "\t", "é", "ß", "λ", "中", "€", "😀", "ñ"]


class GrammarGen:
    """Random GBNF text in the dialect llama.cpp parses."""

    def __init__(self, rng, tokens=False, n_vocab=32000):
        self.r = rng
        self.tokens = tokens
        self.n_vocab = n_vocab

    def lit_char(self, in_class=False):
        r = self.r
        c = r.choice(LIT_CHARS)
        roll = r.random()
        if roll < 0.06:
            return "\\x%02x" % r.choice([0x41, 0x7A, 0x30, 0x20, 0x2D, 0x5D, 0x7E])
        if roll < 0.10:
            return "\\u%04X" % r.choice([0x00E9, 0x03B1, 0x4E2D, 0x20AC, 0x0041, 0x00FF])
        if roll < 0.12:
            return "\\U%08x" % r.choice([0x1F600, 0x10348, 0x00061])
        if c == "\"":
            return "\\\"" if not in_class or r.random() < 0.5 else "\""
        if c == "\\":
            return "\\\\"
        if c == "\n":
            return "\\n"
        if c == "\t":
            return "\\t" if r.random() < 0.7 else "\\r"
        if in_class and c in "]-^":
            return "\\" + c
        if in_class and c == "[":
            return "\\[" if r.random() < 0.5 else "["
        return c

    def literal(self):
        n = self.r.choice([0, 1, 1, 2, 2, 3, 4])
        return "\"" + "".join(self.lit_char() for _ in range(n)) + "\""

    def char_class(self):
        r = self.r
        neg = r.random() < 0.25
        items = []
        for _ in range(r.choice([1, 1, 2, 3])):
            if r.random() < 0.5:
                lo, hi = r.choice([("a", "z"), ("0", "9"), ("A", "F"), ("a", "f"), ("α", "ω"), ("\\x20", "\\x7e"),
                                   ("\\u0400", "\\u04FF"), ("b", "d"), ("1", "5")])
                items.append(lo + "-" + hi)
            else:
                items.append(self.lit_char(in_class=True))
        if r.random() < 0.08:
            items.append("-")  # a trailing dash is a plain character
        return "[" + ("^" if neg else "") + "".join(items) + "]"

    def repeat(self, s):
        r = self.r
        roll = r.random()
        if roll < 0.55:
            return s
        if roll < 0.65:
            return s + "*"
        if roll < 0.75:
            return s + "+"
        if roll < 0.85:
            return s + "?"
        a = r.randint(0, 3)
        kind = r.random()
        if kind < 0.35:
            return s + "{%d}" % max(a, 1)
        if kind < 0.6:
            return s + "{%d,}" % a
        return s + "{%d,%d}" % (a, a + r.randint(0, 3))

    def element(self, rule_idx, n_rules, first, depth):
        r = self.r
        roll = r.random()
        if self.tokens and roll < 0.12:
            tid = r.randint(1, self.n_vocab - 1)
            return ("!" if r.random() < 0.4 else "") + "<[%d]>" % tid
        if roll < 0.35:
            lit = self.literal()
            return self.repeat(lit) if lit != "\"\"" else lit
        if roll < 0.6:
            return self.repeat(self.char_class())
        if roll < 0.66:
            return self.repeat(".")
        if roll < 0.82 and n_rules > 1:
            # references only point forward (recursion is added as a guarded tail in sequence()), so the
            # grammar has no left recursion
            if rule_idx + 1 >= n_rules:
                return self.repeat(self.char_class())
            j = r.randint(rule_idx + 1, n_rules - 1)
            return self.repeat("@%d@" % j)
        if depth < 2:
            sep = r.choice([" ", " ", "\n  "])
            inner = self.alternates(rule_idx, n_rules, depth + 1, nested=True)
            return self.repeat("(" + sep + inner + sep.replace("\n  ", "\n") + ")")
        return self.literal()

    def sequence(self, rule_idx, n_rules, depth, first_ok=True):
        r = self.r
        n = r.choice([1, 1, 2, 2, 3, 4])
        out = []
        for k in range(n):
            out.append(self.element(rule_idx, n_rules, k == 0 and first_ok, depth))
        if depth == 0 and r.random() < 0.15:
            # right recursion behind a non-empty terminal: x ::= "a" ... x?
            j = r.randint(0, rule_idx)
            out = [r.choice(["\"" + self.lit_char() + "\"", self.char_class()])] + out + \
                  ["@%d@" % j + r.choice(["", "?", "?"])]
        return " ".join(out)

    def alternates(self, rule_idx, n_rules, depth=0, nested=False):
        n = self.r.choice([1, 1, 2, 2, 3])
        alts = [self.sequence(rule_idx, n_rules, depth) for _ in range(n)]
        if self.r.random() < 0.06:
            alts.insert(0, "")  # an empty alternative (first: a trailing "|" would continue on the next line)
        sep = " | " if not nested or self.r.random() < 0.7 else "\n    | "
        return sep.join(alts)

    def grammar(self, n_rules=None):
        r = self.r
        if n_rules is None:
            n_rules = r.choice([1, 2, 2, 3, 3, 4, 5, 6])
        names = ["root"] + r.sample([n for n in NAMES if n != "root"], n_rules - 1)
        bodies = [self.alternates(i, n_rules) for i in range(n_rules)]
        lines = []
        order = list(range(n_rules))
        if r.random() < 0.3:
            r.shuffle(order)
        for i in order:
            body = bodies[i]
            for j in range(n_rules):
                body = body.replace("@%d@" % j, names[j])
            ws = r.choice([" ", " ", "  ", "\t"])
            line = names[i] + ws + "::=" + ws + body
            if r.random() < 0.1:
                line += "  # " + r.choice(["note", "comment ::= x", "trailing"])
            lines.append(line)
        if r.random() < 0.15:
            lines.insert(r.randint(0, len(lines)), "# " + r.choice(["a comment", "rules below", "x ::= y"]))
        nl = "\r\n" if r.random() < 0.08 else "\n"
        text = nl.join(lines)
        if r.random() < 0.5:
            text += nl
        if r.random() < 0.1:
            text = nl + text
        return text

    def broken(self):
        """A grammar text with one defect (parse error, undefined rule, left recursion or missing root)."""
        r = self.r
        g = self.grammar()
        kind = r.choice(["unterminated", "noassign", "undefined", "badescape", "leftrec", "noroot", "badrep",
                         "unclosed", "stray", "hexshort", "nothing", "emptyclass"])
        if kind == "unterminated":
            return g + "\nextra ::= \"abc"
        if kind == "noassign":
            return g + "\nlonely \"x\""
        if kind == "undefined":
            return g.replace("root ::=", "root ::= missing-rule ", 1) if "root ::=" in g else g + "\nroot ::= nope"
        if kind == "badescape":
            return g + "\nesc-rule ::= \"\\q\""
        if kind == "leftrec":
            return r.choice(["root ::= root \"a\" | \"b\"", "root ::= x \"a\"\nx ::= root | \"c\"",
                             "root ::= e\ne ::= \"\"? e \"+\" | [0-9]", "root ::= a\na ::= b? a \"z\" | \"y\"\nb ::= \"q\""])
        if kind == "noroot":
            return g.replace("root", "start")
        if kind == "badrep":
            return g + "\nrep ::= \"a\"{" + r.choice(["x}", "2", "1,x}", "}", ",3}"])
        if kind == "unclosed":
            return g + "\ngrp ::= (\"a\" | \"b\""
        if kind == "stray":
            return g + "\nbad ::= \"a\" " + r.choice(["]", ")", "}", "*"])
        if kind == "hexshort":
            return g + "\nhx ::= \"\\x4\""
        if kind == "emptyclass":
            return g + "\nec ::= ["
        return r.choice(["", "   ", "# only a comment\n", "root ::= *"])


# ------------------------------------------------------------------ regex patterns for "pattern"

class RegexGen:
    def __init__(self, rng):
        self.r = rng

    def atom(self, depth):
        r = self.r
        roll = r.random()
        if roll < 0.35:
            return "".join(r.choice("abcxyz019-_ :@") for _ in range(r.randint(1, 3)))
        if roll < 0.45:
            return r.choice(["\\.", "\\-", "\\(", "\\)", "\\[", "\\+", "\\?", "\\*", "\\|", "\\{", "\\$", "\\^"])
        if roll < 0.70:
            return r.choice(["[a-z]", "[0-9]", "[A-Fa-f0-9]", "[^ ]", "[a-c_]", "[xyz]", "[\\-+]", "[^\\]]",
                             "[\\x41-\\x5A]", "[äöü]"])
        if roll < 0.78:
            return "."
        if depth < 2:
            inner = self.alt(depth + 1)
            return ("(?:" if r.random() < 0.3 else "(") + inner + ")"
        return "q"

    def quant(self, a):
        r = self.r
        roll = r.random()
        if roll < 0.55:
            return a
        return a + r.choice(["*", "+", "?", "{2}", "{1,3}", "{0,2}", "{2,}", "{,2}", "{3}"])

    def seq(self, depth):
        return "".join(self.quant(self.atom(depth)) for _ in range(self.r.randint(1, 3)))

    def alt(self, depth=0):
        return "|".join(self.seq(depth) for _ in range(self.r.choice([1, 1, 1, 2, 3])))

    def pattern(self):
        r = self.r
        p = "^" + self.alt() + "$"
        roll = r.random()
        if roll < 0.04:
            return p[1:]  # not anchored: unsupported, any string
        if roll < 0.07:
            return "^(?=a)" + p[1:]  # lookahead: unsupported
        if roll < 0.10:
            return "^(ab" + p[1:]  # unbalanced: invalid, the conversion fails
        if roll < 0.12:
            return "^\\d+$"  # unsupported escape
        return p


# ------------------------------------------------------------------ JSON schemas

PROP_NAMES = ["id", "name", "age", "tags", "a", "b", "c", "x-y", "with space", "ünï", "q\"uote", "back\\slash",
              "1st", "type", "items", "$x", "nested", "value", "list", "flag", "count", "z"]
STR_VALUES = ["", "a", "hello", "with \"quote\"", "back\\slash", "new\nline", "tab\tx", "ünïcödé", "😀", "x y",
              "null", "true", "123"]


class SchemaGen:
    def __init__(self, rng):
        self.r = rng
        self.rx = RegexGen(rng)

    def json_value(self, depth=0):
        r = self.r
        roll = r.random()
        if roll < 0.35:
            return r.choice(STR_VALUES)
        if roll < 0.55:
            return r.choice([0, 1, -1, 42, 3.5, -0.25, 1e20, 123456789, 2.0])
        if roll < 0.65:
            return r.choice([True, False])
        if roll < 0.72:
            return None
        if depth < 2 and roll < 0.86:
            return [self.json_value(depth + 1) for _ in range(r.randint(0, 2))]
        if depth < 2:
            return {r.choice(PROP_NAMES): self.json_value(depth + 1) for _ in range(r.randint(0, 2))}
        return "deep"

    def int_bounds(self, s):
        r = self.r
        choice = r.random()
        vals = [0, 1, -1, 5, 9, 10, 99, 100, 101, 255, 999, 1000, -10, -99, -100, 12345, -5000, 7, 42, 3, 2147483647,
                -2147483648, 9007199254740991]
        if choice < 0.35:
            s["minimum"] = r.choice(vals)
        elif choice < 0.45:
            s["exclusiveMinimum"] = r.choice(vals + [2.5, -0.5])
        if r.random() < 0.6:
            lo = s.get("minimum", s.get("exclusiveMinimum", -1000))
            if r.random() < 0.8:
                v = int(lo) + r.choice([0, 1, 5, 9, 10, 99, 100, 1234, 99999])
            else:
                v = r.choice(vals)
            if r.random() < 0.2:
                s["exclusiveMaximum"] = v + 1
            elif r.random() < 0.1:
                s["maximum"] = v + 0.75
            else:
                s["maximum"] = v

    def leaf(self):
        r = self.r
        t = r.choice(["string", "string", "integer", "integer", "integer", "number", "boolean", "null", "enum",
                      "const", "pattern", "pattern", "format"])
        if t == "string":
            s = {"type": "string"}
            if r.random() < 0.5:
                s["minLength"] = r.choice([0, 1, 2, 3])
            if r.random() < 0.5:
                s["maxLength"] = s.get("minLength", 0) + r.choice([0, 1, 3, 8])
            return s
        if t == "integer":
            s = {"type": "integer"}
            if r.random() < 0.75:
                self.int_bounds(s)
            return s
        if t == "number":
            s = {"type": "number"}
            if r.random() < 0.2:
                s["minimum"] = 0
            return s
        if t in ("boolean", "null"):
            return {"type": t}
        if t == "enum":
            vals = []
            for _ in range(r.randint(1, 4)):
                v = self.json_value()
                if v not in vals:
                    vals.append(v)
            s = {"enum": vals}
            if r.random() < 0.3:
                s["type"] = "string"
            return s
        if t == "const":
            return {"const": self.json_value()}
        if t == "pattern":
            s = {"type": "string", "pattern": self.rx.pattern()}
            if r.random() < 0.15:
                del s["type"]
            return s
        fmt = r.choice(["date", "time", "date-time", "uuid", "uuid4", "email", "uri"])
        s = {"type": "string", "format": fmt}
        if r.random() < 0.1:
            del s["type"]
        return s

    def node(self, depth, defs):
        r = self.r
        if depth >= 3:
            return self.leaf()
        roll = r.random()
        if roll < 0.32:
            return self.leaf()
        if roll < 0.52:
            return self.obj(depth, defs)
        if roll < 0.64:
            s = {"type": "array"}
            if r.random() < 0.85:
                s["items"] = self.node(depth + 1, defs)
            if r.random() < 0.5:
                s["minItems"] = r.choice([0, 1, 2, 3])
            if r.random() < 0.5:
                s["maxItems"] = s.get("minItems", 0) + r.choice([0, 1, 2, 4])
            if r.random() < 0.1:
                del s["type"]
            return s
        if roll < 0.69:
            key = r.choice(["prefixItems", "items"])
            s = {"type": "array", key: [self.node(depth + 1, defs) for _ in range(r.randint(1, 3))]}
            return s
        if roll < 0.78:
            key = r.choice(["anyOf", "oneOf"])
            return {key: [self.node(depth + 1, defs) for _ in range(r.randint(2, 3))]}
        if roll < 0.83:
            types = r.sample(["string", "integer", "number", "boolean", "null", "object", "array"], r.randint(2, 3))
            s = {"type": types}
            if "string" in types and r.random() < 0.5:
                s["maxLength"] = r.randint(1, 5)
            if "integer" in types and r.random() < 0.5:
                s["minimum"] = r.randint(-5, 5)
            return s
        if roll < 0.90 and defs is not None:
            name = r.choice(["Pos", "Item", "node", "Tag", "addr", "a b"])
            if name not in defs["map"]:
                defs["map"][name] = None
                defs["map"][name] = self.node(depth + 1, defs)
            return {"$ref": "#/%s/%s" % (defs["key"], name)}
        if roll < 0.95:
            parts = [self.obj(depth + 1, defs, small=True) for _ in range(r.randint(1, 2))]
            if r.random() < 0.4 and defs is not None:
                name = "Base"
                if name not in defs["map"]:
                    defs["map"][name] = self.obj(depth + 1, None, small=True)
                parts.append({"$ref": "#/%s/%s" % (defs["key"], name)})
            if r.random() < 0.25:
                parts.append({"anyOf": [self.obj(depth + 1, None, small=True), self.obj(depth + 1, None, small=True)]})
            if r.random() < 0.2:
                parts = [{"enum": ["a", "b", "c"]}, {"enum": ["b", "c", 1]}]
            s = {"allOf": parts}
            if r.random() < 0.5:
                s["type"] = "object"
            return s
        return {}

    def obj(self, depth, defs, small=False):
        r = self.r
        s = {"type": "object"} if r.random() < 0.85 else {}
        n = r.randint(0, 2 if small else 4)
        props = {}
        for name in r.sample(PROP_NAMES, n):
            props[name] = self.node(depth + 1, defs)
        if props or r.random() < 0.5:
            s["properties"] = props
        if props and r.random() < 0.7:
            s["required"] = r.sample(list(props), r.randint(0, len(props)))
        roll = r.random()
        if roll < 0.25:
            s["additionalProperties"] = False
        elif roll < 0.35:
            s["additionalProperties"] = True
        elif roll < 0.45:
            s["additionalProperties"] = self.leaf()
        if not s:
            s = {"type": "object"}
        return s

    def schema(self):
        r = self.r
        defs = {"key": r.choice(["$defs", "definitions"]), "map": {}}
        root = self.node(0, defs)
        if defs["map"]:
            root = dict(root)
            root[defs["key"]] = {k: (v if v is not None else {"type": "string"}) for k, v in defs["map"].items()}
        if r.random() < 0.05:
            # a recursive schema: a list node pointing at itself
            root = {"$defs": {"node": {"type": "object", "properties": {"v": {"type": "integer", "minimum": 0},
                                                                      "next": {"anyOf": [{"$ref": "#/$defs/node"},
                                                                                         {"type": "null"}]}},
                                       "required": ["v"]}}, "$ref": "#/$defs/node"}
        return root

    def broken(self):
        r = self.r
        return r.choice([
            {"type": "wat"}, {"type": "string", "minLength": -1}, {"type": "array", "maxItems": "3"},
            {"$ref": "https://example.com/s.json"}, {"$ref": "#/$defs/missing"}, {"anyOf": []},
            {"type": []}, {"enum": []}, {"type": "object", "properties": [1, 2]},
            {"type": "string", "pattern": "^(ab$"}, {"type": "string", "pattern": "^a)b$"},
            {"type": "string", "pattern": "^[abc$"}, {"type": "string", "pattern": "^*a$"},
            {"type": "integer", "minimum": "x"}, {"type": 5}, {"oneOf": {"type": "string"}},
            {"type": "object", "additionalProperties": 3}, {"type": "string", "format": 7},
            {"type": "object", "properties": {"a": {"type": "nope"}}},
            {"type": "array", "items": [{"type": "string"}, 4]},
            {"$ref": 12}, {"type": "string", "pattern": 5},
        ])


# ------------------------------------------------------------------ string mutations

def mutate(rng, s):
    if not s:
        return rng.choice(["x", " ", "\"", "{", "0"])
    i = rng.randrange(len(s))
    roll = rng.random()
    junk = rng.choice(list("ax0 \"\\{}[],:-.eE+") + ["é", "\n", "\t", "😀"])
    if roll < 0.25:
        return s[:i] + s[i + 1:]
    if roll < 0.45:
        return s[:i] + junk + s[i:]
    if roll < 0.65:
        return s[:i] + junk + s[i + 1:]
    if roll < 0.75 and len(s) > 1:
        return s[:i] + s[i + 1:i + 2] + s[i:i + 1] + s[i + 2:] if i + 1 < len(s) else s[:-1]
    if roll < 0.88:
        return s[:i]
    return s + junk


def json_mutations(rng, s):
    """Value-level edits of a JSON text: numbers and lengths at the edges, whitespace, duplicated items."""
    out = []
    try:
        v = json.loads(s)
    except ValueError:
        return out

    def walk(x):
        if isinstance(x, bool) or x is None:
            return rng.choice([not x if isinstance(x, bool) else 0, "null", None])
        if isinstance(x, int):
            return x + rng.choice([-1, 1, 10, -100, 1000, 0.5])
        if isinstance(x, float):
            return rng.choice([int(x), x * 10, -x])
        if isinstance(x, str):
            return rng.choice([x + "z", x[:-1], x * 2, x.upper(), 5])
        if isinstance(x, list):
            if x and rng.random() < 0.5:
                y = list(x)
                k = rng.randrange(len(y))
                y[k] = walk(y[k])
                return y
            return x + x[:1] if x else [1]
        if isinstance(x, dict):
            y = dict(x)
            if y and rng.random() < 0.4:
                k = rng.choice(list(y))
                del y[k]
            elif y and rng.random() < 0.6:
                k = rng.choice(list(y))
                y[k] = walk(y[k])
            else:
                y[rng.choice(PROP_NAMES)] = 1
            return y
        return x

    for _ in range(3):
        try:
            m = walk(v)
            out.append(json.dumps(m, ensure_ascii=rng.random() < 0.5, separators=rng.choice([(",", ":"), (", ", ": ")])))
        except (TypeError, ValueError, OverflowError):
            pass
    return out


# ------------------------------------------------------------------ stage 1

def stage1(a):
    rng = random.Random(a.seed)
    sc = a.scale
    cnt = {k: max(2, int(round(v * sc))) for k, v in
           {"P": 300, "M": 500, "S": 250, "T": 300, "D": 380, "X": 520, "L": 700}.items()}
    gg = GrammarGen(rng)
    sg = SchemaGen(rng)
    specs = []
    pfx = a.prefix

    for i in range(cnt["P"]):
        items = [gg.grammar() for _ in range(rng.randint(1, 3))]
        items.insert(rng.randint(0, len(items)), gg.broken() if rng.random() < 0.6 else gg.grammar())
        specs.append({"id": f"{pfx}p{i:04d}", "bucket": "gbnf_parse", "kind": "P", "G": items})
    for i in range(cnt["M"]):
        root = "root"
        g = gg.grammar()
        if rng.random() < 0.08:
            root = "alt-start"
            g = g + "\nalt-start ::= root (\",\" root)*\n"
        specs.append({"id": f"{pfx}m{i:04d}", "bucket": "gbnf_match", "kind": "M", "G": g, "R": root})
    for i in range(cnt["S"]):
        specs.append({"id": f"{pfx}s{i:04d}", "bucket": "gbnf_stacks", "kind": "S", "G": gg.grammar(), "R": "root"})
    vocabs = [("llama-spm", 32000), ("llama-bpe", 128256), ("phi-3", 32064), ("deepseek-coder", 32256), ("falcon", 65024)]
    for i in range(cnt["T"]):
        vname, nv = rng.choice(vocabs)
        tg = GrammarGen(rng, tokens=rng.random() < 0.35, n_vocab=min(nv, 32000))
        sp = {"id": f"{pfx}t{i:04d}", "bucket": "gbnf_tokens", "kind": "T", "V": vname, "G": tg.grammar(),
              "R": "root", "L": 0, "TP": [], "TT": [], "ops": []}
        roll = rng.random()
        if roll < 0.3:
            sp["L"] = 1
            sp["TP"] = rng.sample(["[\\s\\S]*?(<call>)[\\s\\S]*", "^(\\{)[\\s\\S]*$", "[\\s\\S]*?(TOOL:)[\\s\\S]*",
                                   "^[\\s\\S]*?(```json\\n)[\\s\\S]*", "(\\d\\d)"], rng.randint(0, 2))
            if rng.random() < 0.5 or not sp["TP"]:
                sp["TT"] = [rng.randint(1, min(nv, 32000) - 1) for _ in range(rng.randint(1, 2))]
        ops = []
        for _ in range(rng.randint(1, 4)):
            o = rng.random()
            if o < 0.4:
                ops.append(["N", str(rng.randint(2, 8)), str(rng.randint(1, 10 ** 9))])
            elif o < 0.55:
                ops.append(["A"])
            elif o < 0.65:
                ops.append(["C"])
            elif o < 0.8 and sp["TT"]:
                ops.append(["K", str(rng.choice(sp["TT"]))])
            else:
                ops.append(["Z", None])  # text filled in stage 2 from a walk
        sp["ops"] = ops
        specs.append(sp)
    for i in range(cnt["D"]):
        items = [sg.schema() for _ in range(rng.randint(1, 3))]
        if rng.random() < 0.5:
            items.insert(rng.randint(0, len(items)), sg.broken())
        specs.append({"id": f"{pfx}d{i:04d}", "bucket": "schema_doc", "kind": "D", "J": items})
    for i in range(cnt["X"]):
        sp = {"id": f"{pfx}x{i:04d}", "bucket": "schema_text", "kind": "X", "J": [sg.schema()]}
        if rng.random() < 0.25:
            sp["J"].append(sg.broken())
        if rng.random() < 0.3:
            sp["F"] = [rng.choice(STR_VALUES + ["a\rb", "-]", "\\\"", "x\n\r\"\\y"]) for _ in range(rng.randint(1, 3))]
        if rng.random() < 0.2:
            b = []
            for _ in range(rng.randint(1, 4)):
                if rng.random() < 0.5:
                    b.append(["BR", rng.choice(["root", "item", "my rule", "x.y", "value", "space", "a_b", "item"]),
                              rng.choice(["\"a\" item?", "[0-9]+", "space \"x\"", "\"q\"", "item item"])])
                else:
                    b.append(["BS", rng.choice(["root", "args", "tool-call", "value", "x y"]), sg.schema()])
            sp["B"] = b
            sp["BD"] = 1 if rng.random() < 0.3 else 0
        specs.append(sp)
    for i in range(cnt["L"]):
        specs.append({"id": f"{pfx}l{i:04d}", "bucket": "schema_lang", "kind": "L", "J": sg.schema()})

    os.makedirs(a.dir, exist_ok=True)
    with open(os.path.join(a.dir, "specs.json"), "w") as f:
        json.dump({"seed": a.seed, "specs": specs}, f)
    with open(os.path.join(a.dir, "walk.txt"), "w") as f:
        for sp in specs:
            if sp["kind"] in ("M", "S", "T"):
                n = {"M": 10, "S": 3, "T": 3}[sp["kind"]]
                f.write(f"CASE {sp['id']}\nG {hx(sp['G'])}\nR {hx(sp['R'])}\nW {n} {rng.randint(1, 10 ** 9)}\nEND\n")
    with open(os.path.join(a.dir, "lconv.txt"), "w") as f:
        for sp in specs:
            if sp["kind"] == "L":
                f.write(f"CASE {sp['id']} schema_lang L\nJ {hx(json.dumps(sp['J']))}\nEND\n")


# ------------------------------------------------------------------ stage 2

def read_frames(path):
    data = open(path, "rb").read()
    res, pos = {}, 0
    while pos < len(data):
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split(b" ")
        pos = nl + 1
        if head[0] == b"C":
            n = int(head[3])
            res[head[1].decode()] = data[pos:pos + n]
            pos += n
        else:
            res[head[1].decode()] = None
    return res


def stage2(a):
    d = a.dir
    spec = json.load(open(os.path.join(d, "specs.json")))
    rng = random.Random(spec["seed"] * 7 + 1)
    walks = {}
    with open(os.path.join(d, "walk.out")) as f:
        for line in f:
            w = line.split()
            if w and w[0] == "W":
                walks[w[1]] = [unhx(h).decode("utf-8") for h in w[2:]]
    lconv = read_frames(os.path.join(d, "lconv.out"))
    lstrings = {}
    out = []
    lmatch = []
    for sp in spec["specs"]:
        k = sp["kind"]
        head = f"CASE {sp['id']} {sp['bucket']} {k}\n"
        if k == "P":
            out.append(head + "".join(f"G {hx(g)}\n" for g in sp["G"]) + "END\n")
        elif k == "M":
            pos = list(dict.fromkeys(walks.get(sp["id"], [])))
            strs = list(pos)
            for s in pos[:8]:
                strs.append(mutate(rng, s))
            if not pos:
                strs += ["", "a", "abc", "0", "\"x\""]
            strs = list(dict.fromkeys(strs))[:16]
            out.append(head + f"G {hx(sp['G'])}\nR {hx(sp['R'])}\n" + "".join(f"S {hx(s)}\n" for s in strs) + "END\n")
        elif k == "S":
            pos = walks.get(sp["id"], [])
            s = max(pos, key=len) if pos else "abc"
            if rng.random() < 0.3 and s:
                s = mutate(rng, s)
            out.append(head + f"G {hx(sp['G'])}\nR {hx(sp['R'])}\nS {hx(s[:40])}\nEND\n")
        elif k == "T":
            lines = [f"V {hx(sp['V'])}", f"G {hx(sp['G'])}", f"R {hx(sp['R'])}", f"L {sp['L']}"]
            lines += [f"TP {hx(p)}" for p in sp["TP"]] + [f"TT {t}" for t in sp["TT"]]
            pos = walks.get(sp["id"], []) or ["hello"]
            for op in sp["ops"]:
                if op[0] == "Z":
                    text = rng.choice(pos)
                    if sp["L"]:
                        text = rng.choice(["blah ", "", "x <call>", "TOOL:", "```json\n", "12"]) + text
                    lines.append(f"Z {hx(text)}")
                else:
                    lines.append(" ".join(op))
            out.append(head + "\n".join(lines) + "\nEND\n")
        elif k == "D":
            out.append(head + "".join(f"J {hx(json.dumps(j))}\n" for j in sp["J"]) + "END\n")
        elif k == "X":
            body = "".join(f"J {hx(json.dumps(j))}\n" for j in sp["J"])
            body += "".join(f"F {hx(x)}\n" for x in sp.get("F", []))
            for b in sp.get("B", []):
                body += f"{b[0]} {hx(b[1])} {hx(b[2] if b[0] == 'BR' else json.dumps(b[2]))}\n"
            if sp.get("B"):
                body += f"BD {sp['BD']}\n"
            out.append(head + body + "END\n")
        elif k == "L":
            out.append(head + f"J {hx(json.dumps(sp['J']))}\nEND\n")
            fr = lconv.get(sp["id"])
            strs = []
            if fr is not None and fr.startswith(b"OK\n"):
                g = fr[3:].decode("utf-8")
                pos = list(dict.fromkeys(walks.get(sp["id"], [])))
                strs = list(pos)
                for s in pos[:6]:
                    strs.append(mutate(rng, s))
                    strs += json_mutations(rng, s)[:2]
                strs = list(dict.fromkeys(strs))[:24]
                lmatch.append(f"CASE {sp['id']} schema_lang M\nG {hx(g)}\nR {hx('root')}\n" +
                              "".join(f"S {hx(s)}\n" for s in strs) + "END\n")
            lstrings[sp["id"]] = [hx(s) for s in strs]
    with open(os.path.join(d, "cases.txt"), "w") as f:
        f.write("".join(out))
    with open(os.path.join(d, "lmatch.txt"), "w") as f:
        f.write("".join(lmatch))
    with open(os.path.join(d, "lstrings.json"), "w") as f:
        json.dump(lstrings, f)


def lwalk(a):
    """Walker requests for the L cases, from the reference grammar text (needs lconv.out)."""
    d = a.dir
    spec = json.load(open(os.path.join(d, "specs.json")))
    rng = random.Random(spec["seed"] * 3 + 5)
    lconv = read_frames(os.path.join(d, "lconv.out"))
    with open(os.path.join(d, "walk.txt"), "a") as f:
        for sp in spec["specs"]:
            if sp["kind"] != "L":
                continue
            fr = lconv.get(sp["id"])
            if fr is not None and fr.startswith(b"OK\n"):
                g = fr[3:].decode("utf-8")
                f.write(f"CASE {sp['id']}\nG {hx(g)}\nR {hx('root')}\nW 10 {rng.randint(1, 10 ** 9)}\nEND\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["stage1", "lwalk", "stage2"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--prefix", default="h")
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    {"stage1": stage1, "lwalk": lwalk, "stage2": stage2}[a.stage](a)
