"""Executable model of the modify filter contract (legacy plain-key behaviour plus record-accessor paths).

apply_case(props, records) -> ("init_fail", None) or ("ok", [output bodies]).
props: list of (property name, value string) in configuration order.
records: list of MMap bodies.

This is the specification the hidden set is frozen from. The legacy part is checked against the
pristine build (gen/check_legacy.py); the path part follows the task contract in instruction.md.
"""
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harbor" / "tests"))
from mpcodec import MMap, Bin  # noqa: E402


class InitFail(Exception):
    pass


# ---------------------------------------------------------------- tokenizer (flb_utils_split_quoted)

def _quoted_len(s, i):
    quote = s[i]
    i += 1
    n = 0
    while True:
        if i >= len(s):
            return -1
        c = s[i]
        i += 1
        if c == "\\":
            if i < len(s) and (s[i] == quote or s[i] == "\\"):
                i += 1
        elif c == quote:
            return n
        n += 1


def _next_token(s, start):
    i = start
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s) or (s[i] != '"' and s[i] != "'"):
        j = s.find(" ", i)
        if j > i:
            return s[i:j], j
        return s[i:], len(s)
    n = _quoted_len(s, i)
    if n < 0:
        return None, -1
    quote = s[i]
    i += 1
    out = []
    for _ in range(n):
        if s[i] == "\\" and i + 1 < len(s) and (s[i + 1] == quote or s[i + 1] == "\\"):
            i += 1
        out.append(s[i])
        i += 1
    return "".join(out), i


def split_quoted(s, max_split):
    toks = []
    i = 0
    n = len(s)
    count = 0
    while i < n:
        tok, end = _next_token(s, i)
        if end == -1:
            raise InitFail("unterminated quote")
        i = end
        toks.append(tok)
        count += 1
        i += 1
        if count >= max_split and max_split > 0 and i < n:
            toks.append(s[i:])
            break
    return toks


# ---------------------------------------------------------------- paths

_ROOT = re.compile(r"[_A-Za-z][A-Za-z0-9_\-/]*")
_SUB = re.compile(r"\[(?:'((?:[^'\s,\"]|'')*)'|(0|[1-9][0-9]{0,8}))\]")


def parse_path(tok):
    """'$root[...]...' -> list of steps ('k', name) / ('i', n); None when the token is not a valid path."""
    if not tok.startswith("$"):
        return None
    m = _ROOT.match(tok, 1)
    if not m:
        return None
    root = m.group(0)
    if root.startswith("TAG"):
        return None
    steps = [("k", root)]
    i = m.end()
    while i < len(tok):
        m = _SUB.match(tok, i)
        if not m:
            return None
        if m.group(1) is not None:
            steps.append(("k", m.group(1).replace("''", "'")))
        else:
            steps.append(("i", int(m.group(2))))
        i = m.end()
    return steps


def is_str(v):
    return isinstance(v, str) and not isinstance(v, Bin)


def _last_key(mp, name):
    for j in range(len(mp) - 1, -1, -1):
        k = mp[j][0]
        if is_str(k) and k == name:
            return j
    return -1


def resolve(rec, steps):
    """Strict resolution. Returns (container, index) of the addressed slot, or None."""
    cur = rec
    cont = None
    idx = None
    for kind, s in steps:
        if kind == "k":
            if not isinstance(cur, MMap):
                return None
            j = _last_key(cur, s)
            if j < 0:
                return None
            cont, idx = cur, j
            cur = cur[j][1]
        else:
            if not isinstance(cur, list) or isinstance(cur, MMap):
                return None
            if s >= len(cur):
                return None
            cont, idx = cur, s
            cur = cur[s]
    return cont, idx


def slot_get(cont, idx):
    return cont[idx][1] if isinstance(cont, MMap) else cont[idx]


def slot_set(cont, idx, val):
    if isinstance(cont, MMap):
        cont[idx] = (cont[idx][0], val)
    else:
        cont[idx] = val


def path_set(rec, steps, val):
    """Set semantics on a copy: replace in place when the path resolves, otherwise create through map steps.
    Returns the new record, or None when the path can be neither resolved nor created."""
    rec = copy.deepcopy(rec)
    cur = rec
    for n, (kind, s) in enumerate(steps):
        last = n == len(steps) - 1
        if kind == "k":
            if not isinstance(cur, MMap):
                return None
            j = _last_key(cur, s)
            if j >= 0:
                if last:
                    cur[j] = (cur[j][0], copy.deepcopy(val))
                    return rec
                cur = cur[j][1]
                continue
            # create the rest: only name steps may follow
            rest = steps[n + 1:]
            if any(k != "k" for k, _ in rest):
                return None
            node = copy.deepcopy(val)
            for _, name in reversed(rest):
                node = MMap([(name, node)])
            cur.append((s, node))
            return rec
        else:
            if not isinstance(cur, list) or isinstance(cur, MMap) or s >= len(cur):
                return None
            if last:
                cur[s] = copy.deepcopy(val)
                return rec
            cur = cur[s]
    return None


def path_remove(rec, steps):
    rec = copy.deepcopy(rec)
    r = resolve(rec, steps)
    if r is None:
        return None
    cont, idx = r
    del cont[idx]
    return rec


# ---------------------------------------------------------------- matchers (legacy helpers)

class Rx:
    def __init__(self, pattern):
        try:
            self.rx = re.compile(pattern)
        except re.error:
            raise InitFail("bad regex %r" % pattern)

    def search(self, s):
        return self.rx.search(s) is not None


def rx_obj(o, rx):
    """helper_msgpack_object_matches_regex: str values, booleans as true/false; never bin."""
    if isinstance(o, Bin):
        return False
    if o is True:
        return rx.search("true")
    if o is False:
        return rx.search("false")
    if isinstance(o, str):
        return rx.search(o)
    return False


def str_obj(o, s):
    """helper_msgpack_object_matches_str: str or bin with identical bytes."""
    if isinstance(o, Bin):
        return bytes(o) == s.encode("utf-8", "surrogateescape")
    if isinstance(o, str):
        return o == s
    return False


def wild_obj(o, prefix):
    if isinstance(o, Bin):
        return bytes(o).startswith(prefix.encode("utf-8", "surrogateescape"))
    if isinstance(o, str):
        return o.encode("utf-8", "surrogateescape").startswith(prefix.encode("utf-8", "surrogateescape"))
    return False


# ---------------------------------------------------------------- configuration

RULES1 = {"remove", "remove_wildcard", "remove_regex", "move_to_start", "move_to_end"}
RULES2 = {"rename", "hard_rename", "add", "add_if_not_present", "set", "copy", "hard_copy"}
KEYSET_RULES = {"remove_wildcard", "remove_regex", "move_to_start", "move_to_end"}
CONDS = {"key_exists", "key_does_not_exist", "a_key_matches", "no_key_matches", "key_value_equals",
         "key_value_does_not_equal", "key_value_matches", "key_value_does_not_match",
         "matching_keys_have_matching_values", "matching_keys_do_not_have_matching_values"}
KNOWN_PROPS = RULES1 | RULES2 | {"condition"}


class Rule:
    pass


class Cond:
    pass


def build(props):
    rules, conds = [], []
    for name, value in props:
        lname = name.lower()
        if lname not in KNOWN_PROPS:
            raise InitFail("unknown property")
        if lname == "condition":
            conds.append(build_cond(value))
        else:
            rules.append(build_rule(lname, value))
    return rules, conds


def build_cond(value):
    toks = split_quoted(value, 3)
    if len(toks) == 0:
        raise InitFail("token count")
    ctype = toks[0].lower()
    path_mk = ctype in ("matching_keys_have_matching_values", "matching_keys_do_not_have_matching_values") \
        and len(toks) >= 2 and toks[1].startswith("$")
    if len(toks) > 3 and not path_mk:
        raise InitFail("token count")
    if ctype not in CONDS:
        raise InitFail("unknown condition")
    c = Cond()
    c.type = ctype
    c.path = None
    if ctype in ("matching_keys_have_matching_values", "matching_keys_do_not_have_matching_values") \
            and len(toks) >= 2 and toks[1].startswith("$"):
        t4 = split_quoted(value, 4)
        if len(t4) != 4:
            raise InitFail("path form needs PATH KEYREGEX VALREGEX")
        c.path = parse_path(t4[1])
        if c.path is None:
            raise InitFail("bad path")
        c.krx = Rx(t4[2])
        c.vrx = Rx(t4[3])
        return c
    if ctype in ("a_key_matches", "no_key_matches"):
        if len(toks) < 2 or len(toks[1]) < 1:
            raise InitFail("missing regex")
        if len(toks) == 3 and toks[1].startswith("$"):
            c.path = parse_path(toks[1])
            if c.path is None:
                raise InitFail("bad path")
            c.krx = Rx(toks[2])
        else:
            c.krx = Rx(toks[1])
        return c
    if ctype in ("matching_keys_have_matching_values", "matching_keys_do_not_have_matching_values"):
        if len(toks) != 3:
            raise InitFail("needs two regexes")
        c.krx = Rx(toks[1])
        c.vrx = Rx(toks[2])
        return c
    # key-addressing conditions
    if len(toks) < 2:
        raise InitFail("missing key")
    key = toks[1]
    if key.startswith("$"):
        c.path = parse_path(key)
        if c.path is None:
            raise InitFail("bad path")
    else:
        c.key = key
    if ctype in ("key_value_equals", "key_value_does_not_equal", "key_value_matches", "key_value_does_not_match"):
        if len(toks) != 3:
            raise InitFail("missing value")
        c.b = toks[2]
        if ctype in ("key_value_matches", "key_value_does_not_match"):
            c.vrx = Rx(toks[2])
    return c


def build_rule(lname, value):
    toks = split_quoted(value, 3)
    if len(toks) == 0 or len(toks) > 3:
        raise InitFail("token count")
    r = Rule()
    r.name = lname
    first = toks[0]
    if first.startswith("$"):
        return build_path_rule(r, lname, toks)
    # legacy plain-key rule
    if len(toks) == 1 and lname not in RULES1:
        raise InitFail("invalid operation")
    if len(toks) == 2 and lname not in RULES2:
        if lname in KEYSET_RULES:
            raise InitFail("two-token key-set rule needs a path")
        raise InitFail("invalid operation")
    if len(toks) == 3:
        raise InitFail("too many tokens")
    r.path = None
    r.key = toks[0]
    r.val = toks[-1]
    r.type = "add" if lname == "add_if_not_present" else lname
    # legacy compiles both tokens as regexes and refuses the rule when either fails
    Rx(r.key)
    Rx(r.val)
    if r.type == "remove_regex":
        r.krx = Rx(r.key)
    return r


def build_path_rule(r, lname, toks):
    r.path = parse_path(toks[0])
    if r.path is None:
        raise InitFail("bad path")
    r.type = "add" if lname == "add_if_not_present" else lname
    if len(toks) == 3:
        raise InitFail("too many tokens")
    if len(toks) == 1:
        if lname == "remove":
            return r
        # one-token key-set rules keep their literal meaning: handled as legacy
        if lname in KEYSET_RULES:
            r.path = None
            r.key = toks[0]
            r.val = toks[0]
            Rx(r.key)
            if lname == "remove_regex":
                r.krx = Rx(r.key)
            return r
        raise InitFail("invalid operation")
    # two tokens
    arg = toks[1]
    if lname in KEYSET_RULES:
        if lname == "remove_regex":
            r.krx = Rx(arg)
        else:
            r.prefix = arg
        return r
    if lname == "remove":
        raise InitFail("invalid operation")
    if r.type in ("set", "add"):
        r.val = arg
        return r
    # rename / hard_rename / copy / hard_copy
    if arg.startswith("$"):
        r.dst = parse_path(arg)
        if r.dst is None:
            raise InitFail("bad destination path")
        r.newname = None
    else:
        if r.path[-1][0] != "k":
            raise InitFail("name form needs a source that ends with a key")
        r.dst = None
        r.newname = arg
    return r


# ---------------------------------------------------------------- conditions

def legacy_lookup(rec, key):
    j = _last_key(rec, key)
    if j < 0:
        return None
    return (rec, j)


def cond_slot(rec, c):
    if c.path is not None:
        return resolve(rec, c.path)
    return legacy_lookup(rec, c.key)


def eval_cond(rec, c):
    t = c.type
    if t in ("key_exists", "key_does_not_exist"):
        e = cond_slot(rec, c) is not None
        return e if t == "key_exists" else not e
    if t in ("key_value_equals", "key_value_does_not_equal"):
        s = cond_slot(rec, c)
        if s is None:
            return False
        eq = str_obj(slot_get(*s), c.b)
        return eq if t == "key_value_equals" else not eq
    if t in ("key_value_matches", "key_value_does_not_match"):
        s = cond_slot(rec, c)
        if s is None:
            return False
        m = rx_obj(slot_get(*s), c.vrx)
        return m if t == "key_value_matches" else not m
    if t in ("a_key_matches", "no_key_matches"):
        if c.path is not None:
            s = resolve(rec, c.path)
            mp = slot_get(*s) if s is not None else None
            hit = isinstance(mp, MMap) and any(rx_obj(k, c.krx) for k, _ in mp)
        else:
            hit = any(rx_obj(k, c.krx) for k, _ in rec)
        return hit if t == "a_key_matches" else not hit
    if t in ("matching_keys_have_matching_values", "matching_keys_do_not_have_matching_values"):
        if c.path is not None:
            s = resolve(rec, c.path)
            mp = slot_get(*s) if s is not None else None
            if not isinstance(mp, MMap):
                ok = False
            else:
                ok = all(rx_obj(v, c.vrx) for k, v in mp if rx_obj(k, c.krx))
        else:
            ok = all(rx_obj(v, c.vrx) for k, v in rec if rx_obj(k, c.krx))
        return ok if t == "matching_keys_have_matching_values" else not ok
    raise AssertionError(t)


# ---------------------------------------------------------------- legacy rules

def legacy_rule(rec, r):
    t = r.type
    k, v = r.key, r.val
    items = list(rec)
    mk = [i for i, (kk, _) in enumerate(items) if str_obj(kk, k)]
    if t == "set":
        out = MMap(p for p in items if not str_obj(p[0], k))
        out.append((k, v))
        return out
    if t == "add":
        if mk:
            return None
        out = MMap(items)
        out.append((k, v))
        return out
    if t == "remove":
        if not mk:
            return None
        return MMap(p for p in items if not str_obj(p[0], k))
    if t == "remove_wildcard":
        if not any(wild_obj(kk, k) for kk, _ in items):
            return None
        return MMap(p for p in items if not wild_obj(p[0], k))
    if t == "remove_regex":
        if not any(rx_obj(kk, r.krx) for kk, _ in items):
            return None
        return MMap(p for p in items if not rx_obj(p[0], r.krx))
    if t in ("move_to_start", "move_to_end"):
        m = [p for p in items if wild_obj(p[0], k)]
        if not m:
            return None
        n = [p for p in items if not wild_obj(p[0], k)]
        return MMap(m + n) if t == "move_to_start" else MMap(n + m)
    conflict = [i for i, (kk, _) in enumerate(items) if str_obj(kk, v)]
    if t == "rename":
        if not mk or conflict:
            return None
        return MMap(((v, vv) if str_obj(kk, k) else (kk, vv)) for kk, vv in items)
    if t == "hard_rename":
        if not mk:
            return None
        out = MMap()
        for kk, vv in items:
            if conflict and str_obj(kk, v):
                continue
            out.append((v, vv) if str_obj(kk, k) else (kk, vv))
        return out
    if t == "copy":
        if len(mk) != 1 or conflict:
            return None
        out = MMap()
        for kk, vv in items:
            out.append((kk, vv))
            if str_obj(kk, k):
                out.append((v, copy.deepcopy(vv)))
        return out
    if t == "hard_copy":
        if len(mk) != 1 or len(conflict) > 1:
            return None
        out = MMap()
        for kk, vv in items:
            if conflict and str_obj(kk, v):
                continue
            out.append((kk, vv))
            if str_obj(kk, k):
                out.append((v, copy.deepcopy(vv)))
        return out
    raise AssertionError(t)


# ---------------------------------------------------------------- path rules

def path_rule(rec, r):
    t = r.type
    if t == "set":
        return path_set(rec, r.path, r.val)
    if t == "add":
        if resolve(rec, r.path) is not None:
            return None
        return path_set(rec, r.path, r.val)
    if t == "remove":
        return path_remove(rec, r.path)
    if t in KEYSET_RULES:
        rec = copy.deepcopy(rec)
        s = resolve(rec, r.path)
        if s is None:
            return None
        mp = slot_get(*s)
        if not isinstance(mp, MMap):
            return None
        if t == "remove_regex":
            keep = MMap(p for p in mp if not rx_obj(p[0], r.krx))
        elif t == "remove_wildcard":
            keep = MMap(p for p in mp if not wild_obj(p[0], r.prefix))
        else:
            m = [p for p in mp if wild_obj(p[0], r.prefix)]
            n = [p for p in mp if not wild_obj(p[0], r.prefix)]
            keep = MMap(m + n) if t == "move_to_start" else MMap(n + m)
        slot_set(s[0], s[1], keep)
        return rec
    # rename / hard_rename / copy / hard_copy
    hard = t.startswith("hard_")
    is_copy = t.endswith("copy")
    s = resolve(rec, r.path)
    if s is None:
        return None
    if r.dst is not None:
        if r.dst == r.path:
            return None
        val = copy.deepcopy(slot_get(*s))
        if not hard and resolve(rec, r.dst) is not None:
            return None
        base = rec if is_copy else path_remove(rec, r.path)
        return path_set(base, r.dst, val)
    # name form: the source ends with a key step
    cont, idx = s
    name = cont[idx][0]
    if r.newname == name:
        return None
    rec = copy.deepcopy(rec)
    cont, idx = resolve(rec, r.path)
    conflicts = [j for j, (kk, _) in enumerate(cont) if j != idx and is_str(kk) and kk == r.newname]
    if conflicts and not hard:
        return None
    entry = cont[idx]
    newmap = MMap()
    for j, (kk, vv) in enumerate(cont):
        if j in conflicts:
            continue
        if j == idx:
            if is_copy:
                newmap.append((kk, vv))
                newmap.append((r.newname, copy.deepcopy(vv)))
            else:
                newmap.append((r.newname, vv))
        else:
            newmap.append((kk, vv))
    cont[:] = newmap
    del entry
    return rec


# ---------------------------------------------------------------- driver

def apply_record(rec, rules, conds):
    if not all(eval_cond(rec, c) for c in conds):
        return rec
    cur = rec
    for r in rules:
        nxt = path_rule(cur, r) if r.path is not None else legacy_rule(cur, r)
        if nxt is not None:
            cur = nxt
    return cur


def apply_case(props, records):
    try:
        rules, conds = build(props)
    except InitFail:
        return "init_fail", None
    return "ok", [apply_record(copy.deepcopy(r), rules, conds) for r in records]
