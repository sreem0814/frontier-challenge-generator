"""Generate modify-filter cases (configs + records) and freeze the expected outputs from oracle.py.

usage: python3 -I generate.py <seed> <scale> <out.jsonl>
Each line: {"id", "bucket", "props": [[name, value], ...], "records": [hex], "status", "outputs": [hex] | null}
"""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "harbor" / "tests"))
import oracle  # noqa: E402
from mpcodec import MMap, packb  # noqa: E402

ROOTS = ["log", "level", "kubernetes", "meta", "items", "tags", "user", "http", "status", "a", "b", "c",
         "data", "resource", "attrs", "span-ctx", "svc/name"]
SUBS = ["labels", "annotations", "pod", "name", "id", "app", "app_id", "app.kubernetes.io/name", "env",
        "region", "x", "y", "z", "code", "secret", "token", "trace_id", "host", "k8s", "list", "it's", "café",
        "0", "a b"]
WORDS = ["prod", "dev", "api", "200", "404", "error", "info", "true", "false", "web-1", "us-east", "", "x",
         "debug", "café", "null"]
SET_VALUES = ["v1", "hello", "200", "true", "redacted", "$literal", "\"two words\"", "new", "0", "x.y",
              "a'b"]
KEY_RX = ["^app", "^app_", "id$", "^(env|region)$", "^x", "[0-9]", "^l", "e", "^a.*d$", "^(x|y|z)$",
          "^k8s", "o"]
VAL_RX = ["^prod$", "^[a-z]+$", "^[0-9]+$", "true", "^e", "^web", "-", "^(dev|prod)$", "s"]
PREFIXES = ["app", "app_", "x", "e", "k8s", "a", "tr", "na", "lab", "c"]
NEWNAMES = ["renamed", "app", "env", "x", "copy_of", "id", "name", "zz", "labels"]


class G:
    def __init__(self, rnd):
        self.r = rnd

    def scalar(self):
        r = self.r.random()
        if r < 0.55:
            return self.r.choice(WORDS)
        if r < 0.75:
            return self.r.choice([0, 1, 7, 200, 404, -3, 65535, 1 << 40, -200000])
        if r < 0.88:
            return self.r.choice([True, False])
        return None

    def value(self, depth):
        r = self.r.random()
        if depth <= 0 or r < 0.45:
            return self.scalar()
        if r < 0.78:
            return self.map(depth - 1)
        return self.array(depth - 1)

    def map(self, depth, n=None):
        n = n if n is not None else self.r.randint(1, 5)
        keys = self.r.sample(SUBS, n)
        if self.r.random() < 0.06 and keys:
            keys.append(self.r.choice(keys))      # an occasional duplicate key
        return MMap((k, self.value(depth)) for k in keys)

    def array(self, depth):
        n = self.r.randint(0, 4)
        if self.r.random() < 0.6:
            return [self.map(depth, self.r.randint(1, 3)) for _ in range(n)]
        return [self.scalar() for _ in range(n)]

    def record(self):
        n = self.r.randint(3, 7)
        keys = self.r.sample(ROOTS, n)
        rec = MMap()
        for k in keys:
            rec.append((k, self.value(self.r.randint(1, 3))))
        return rec


def all_paths(rec):
    out = []

    def walk(v, steps):
        if isinstance(v, MMap):
            for k, x in v:
                if isinstance(k, str):
                    s = steps + [("k", k)]
                    out.append(s)
                    walk(x, s)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                s = steps + [("i", i)]
                out.append(s)
                walk(x, s)

    walk(rec, [])
    return out


def render(steps):
    root = steps[0][1]
    parts = ["$" + root]
    for kind, s in steps[1:]:
        if kind == "k":
            parts.append("['" + s.replace("'", "''") + "']")
        else:
            parts.append("[%d]" % s)
    tok = "".join(parts)
    return tok


def renderable(steps):
    """A path we can write as a valid token: root an identifier, names without space/comma/double quote."""
    import re
    if not re.fullmatch(r"[_A-Za-z][A-Za-z0-9_\-/]*", steps[0][1]) or steps[0][1].startswith("TAG"):
        return False
    for kind, s in steps[1:]:
        if kind == "k" and any(c in s for c in " \t,\""):
            return False
    return True


class CaseMaker:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.g = G(self.r)

    # ---- path choice helpers
    def pick_path(self, rec, pred=None, min_len=1):
        ps = [p for p in all_paths(rec) if renderable(p) and len(p) >= min_len and (pred is None or pred(p, rec))]
        return self.r.choice(ps) if ps else None

    def ensure_nested(self, rec):
        """Make sure the record has a nested map and an array of maps to aim at."""
        if not any(isinstance(v, MMap) for _, v in rec):
            rec.append((self.r.choice(["kubernetes", "meta"]), self.g.map(2, 3)))
        if self.r.random() < 0.5 and not any(isinstance(v, list) for _, v in rec):
            rec.append(("items", [self.g.map(1, 2) for _ in range(self.r.randint(1, 3))]))
        return rec

    def variants(self, base, target, n):
        """Records around a target path: the base, the target removed, an intermediate broken, a sibling."""
        recs = [base]
        kinds = ["drop_leaf", "drop_mid", "scalar_mid", "fresh", "dup_leaf", "array_short"]
        while len(recs) < n:
            k = self.r.choice(kinds)
            v = oracle.copy.deepcopy(base)
            if k == "drop_leaf" and target:
                v = oracle.path_remove(v, target) or v
            elif k == "drop_mid" and target and len(target) >= 2:
                cut = self.r.randint(1, len(target) - 1)
                v = oracle.path_remove(v, target[:cut]) or v
            elif k == "scalar_mid" and target and len(target) >= 2:
                cut = self.r.randint(1, len(target) - 1)
                v = oracle.path_set(v, target[:cut], self.r.choice(["flat", 5, None, True])) or v
            elif k == "dup_leaf" and target and target[-1][0] == "k":
                s = oracle.resolve(v, target)
                if s and isinstance(s[0], MMap):
                    s[0].insert(0, (target[-1][1], self.g.scalar()))
            elif k == "array_short" and target and any(st[0] == "i" for st in target):
                pos = max(i for i, st in enumerate(target) if st[0] == "i")
                s = oracle.resolve(v, target[:pos])
                if s:
                    arr = oracle.slot_get(*s)
                    if isinstance(arr, list):
                        del arr[target[pos][1]:]
            else:
                v = self.ensure_nested(self.g.record())
            recs.append(v)
        return recs

    def extend(self, steps, k=1):
        out = list(steps)
        for _ in range(k):
            out.append(("k", self.r.choice(["new", "x", "deep", "app", "z9"])))
        return out

    def target_for_write(self, rec):
        r = self.r.random()
        p = self.pick_path(rec)
        if p is None:
            return [("k", "fresh")]
        if r < 0.35:
            return p
        if r < 0.65:
            return self.extend(p if self.r.random() < 0.8 else p[:1], self.r.randint(1, 2))
        if r < 0.8:
            arr = self.pick_path(rec, lambda q, rr: q[-1][0] == "i")
            if arr:
                return arr if self.r.random() < 0.5 else arr[:-1] + [("i", arr[-1][1] + self.r.randint(1, 3))]
            return p
        return [("k", self.r.choice(ROOTS))] + [("k", self.r.choice(SUBS[:12])) for _ in range(self.r.randint(0, 2))]

    def src_dst(self, rec):
        src = self.pick_path(rec, lambda q, rr: True)
        if src is None:
            src = [("k", "missing")]
        r = self.r.random()
        if r < 0.3:
            dst = self.extend(self.pick_path(rec) or src[:1], self.r.randint(0, 2))
            if dst == src:
                dst = self.extend(dst, 1)
        elif r < 0.55:
            dst = self.pick_path(rec) or self.extend(src, 1)
        elif r < 0.7:
            dst = [("k", self.r.choice(["moved", "copy", "out", "meta"]))] + \
                  [("k", self.r.choice(SUBS[:10])) for _ in range(self.r.randint(0, 2))]
        elif r < 0.8:
            dst = src[:-1] + [("k", self.r.choice(NEWNAMES))] if len(src) > 1 else [("k", "top")]
        elif r < 0.9:
            dst = self.extend(src, 1)          # inside the source
        else:
            dst = list(src)
        return src, dst

    # ---- buckets
    def c_set_add(self):
        base = self.ensure_nested(self.g.record())
        t = self.target_for_write(base)
        op = self.r.choice(["Set", "Set", "Add", "Add", "Add_if_not_present"])
        props = [(op, render(t) + " " + self.r.choice(SET_VALUES))]
        return props, self.variants(base, t, 3), t

    def c_remove(self):
        base = self.ensure_nested(self.g.record())
        t = self.pick_path(base) or [("k", "x")]
        if self.r.random() < 0.2:
            t = self.extend(t, 1)
        props = [("Remove", render(t))]
        if self.r.random() < 0.25:
            t2 = self.pick_path(base)
            if t2:
                props.append(("Remove", render(t2)))
        return props, self.variants(base, t, 3), t

    def c_rename(self):
        base = self.ensure_nested(self.g.record())
        op = self.r.choice(["Rename", "Hard_rename"])
        if self.r.random() < 0.5:
            src = self.pick_path(base, lambda q, rr: q[-1][0] == "k") or [("k", "log")]
            nn = self.r.choice(NEWNAMES + [src[-1][1]])
            s = oracle.resolve(base, src)
            if s and isinstance(s[0], MMap) and self.r.random() < 0.5:
                sib = [k for k, _ in s[0] if isinstance(k, str) and k != src[-1][1]]
                if sib:
                    nn = self.r.choice(sib)
            if " " in nn:
                nn = "renamed"
            props = [(op, render(src) + " " + nn)]
        else:
            src, dst = self.src_dst(base)
            props = [(op, render(src) + " " + render(dst))]
        return props, self.variants(base, src, 3), src

    def c_copy(self):
        base = self.ensure_nested(self.g.record())
        op = self.r.choice(["Copy", "Hard_copy"])
        if self.r.random() < 0.5:
            src = self.pick_path(base, lambda q, rr: q[-1][0] == "k") or [("k", "log")]
            nn = self.r.choice(NEWNAMES + [src[-1][1]])
            s = oracle.resolve(base, src)
            if s and isinstance(s[0], MMap) and self.r.random() < 0.5:
                sib = [k for k, _ in s[0] if isinstance(k, str) and k != src[-1][1]]
                if sib:
                    nn = self.r.choice(sib)
            if " " in nn:
                nn = "copied"
            props = [(op, render(src) + " " + nn)]
        else:
            src, dst = self.src_dst(base)
            props = [(op, render(src) + " " + render(dst))]
        return props, self.variants(base, src, 3), src

    def labelled(self):
        base = self.ensure_nested(self.g.record())
        lab = MMap()
        for k in self.r.sample(["app", "app_id", "app_name", "env", "region", "x1", "xy", "k8s-app", "tier",
                                "trace", "name", "id"], self.r.randint(2, 6)):
            lab.append((k, self.r.choice(WORDS[:12] + [True, 3])))
        holder = self.r.choice([[("k", "kubernetes"), ("k", "labels")], [("k", "meta")],
                                [("k", "items"), ("i", 0), ("k", "labels")], [("k", "attrs")]])
        base = oracle.path_set(base, holder, lab) or base
        if self.r.random() < 0.3:
            return base, self.pick_path(base, lambda q, rr: oracle.resolve(rr, q) is not None and isinstance(
                oracle.slot_get(*oracle.resolve(rr, q)), MMap)) or holder
        return base, holder

    def c_keysets(self):
        base, holder = self.labelled()
        op = self.r.choice(["Remove_wildcard", "Remove_regex", "Move_to_start", "Move_to_end"])
        arg = self.r.choice(KEY_RX) if op == "Remove_regex" else self.r.choice(PREFIXES)
        props = [(op, render(holder) + " " + arg)]
        if self.r.random() < 0.2:
            op2 = self.r.choice(["Remove_wildcard", "Move_to_end", "Move_to_start"])
            props.append((op2, render(holder) + " " + self.r.choice(PREFIXES)))
        return props, self.variants(base, holder, 3), holder

    def marker(self, rec):
        r = self.r.random()
        if r < 0.5:
            return ("Set", "$meta['matched'] yes")
        if r < 0.75:
            return ("Add", "matched yes")
        p = self.pick_path(rec)
        return ("Remove", render(p)) if p else ("Set", "$flag yes")

    def c_conditions(self):
        base = self.ensure_nested(self.g.record())
        n = self.r.choice([1, 1, 2])
        props = []
        target = None
        for _ in range(n):
            ctype = self.r.choice(["Key_exists", "Key_does_not_exist", "Key_value_equals",
                                   "Key_value_does_not_equal", "Key_value_matches", "Key_value_does_not_match"])
            p = self.pick_path(base, min_len=2) or self.pick_path(base) or [("k", "log")]
            if self.r.random() < 0.25:
                p = self.extend(p, 1)
            target = target or p
            tok = render(p)
            if ctype in ("Key_exists", "Key_does_not_exist"):
                props.append(("Condition", ctype + " " + tok))
            else:
                s = oracle.resolve(base, p)
                v = oracle.slot_get(*s) if s else None
                if ctype.endswith("equals") or ctype.endswith("equal"):
                    val = v if isinstance(v, str) and v and " " not in v and self.r.random() < 0.7 \
                        else self.r.choice(["prod", "200", "true", "x"])
                    props.append(("Condition", ctype + " " + tok + " " + val))
                else:
                    props.append(("Condition", ctype + " " + tok + " " + self.r.choice(VAL_RX)))
        props.append(self.marker(base))
        return props, self.variants(base, target, 3), target

    def c_cond_keysets(self):
        base, holder = self.labelled()
        ctype = self.r.choice(["A_key_matches", "No_key_matches", "Matching_keys_have_matching_values",
                               "Matching_keys_do_not_have_matching_values"])
        if ctype.startswith("Matching"):
            c = ctype + " " + render(holder) + " " + self.r.choice(KEY_RX) + " " + self.r.choice(VAL_RX)
        else:
            c = ctype + " " + render(holder) + " " + self.r.choice(KEY_RX)
        props = [("Condition", c), self.marker(base)]
        return props, self.variants(base, holder, 3), holder

    BAD_PATHS = ["$", "$a[", "$a['b'", "$a[x]", "$a[-1]", "$a[01]", "$a['b']x", "$a.b", "$TAG", "$TAG[0]",
                 "$1", "$a['b']]", "$['a']", "$a[''b']", "$a[1.5]", "$9lives", "$a['b'][", "$a[]"]

    def c_config(self):
        base = self.ensure_nested(self.g.record())
        recs = self.variants(base, None, 2)
        good = self.pick_path(base) or [("k", "log")]
        bad = self.r.choice(self.BAD_PATHS)
        k = self.r.randint(0, 11)
        if k == 0:
            props = [(self.r.choice(["Set", "Add", "Copy", "Rename"]), bad + " v")]
        elif k == 1:
            props = [("Remove", bad)]
        elif k == 2:
            props = [(self.r.choice(["Copy", "Hard_copy", "Rename", "Hard_rename"]), render(good) + " " + bad)]
        elif k == 3:
            props = [("Condition", self.r.choice(["Key_exists ", "Key_does_not_exist "]) + bad),
                     ("Set", "$meta['m'] 1")]
        elif k == 4:
            props = [("Condition", "Key_value_equals " + bad + " prod"), ("Add", "m 1")]
        elif k == 5:
            arr = self.pick_path(base, lambda q, rr: q[-1][0] == "i")
            src = arr or [("k", "items"), ("i", 0)]
            props = [(self.r.choice(["Rename", "Hard_rename", "Copy", "Hard_copy"]), render(src) + " newname")]
        elif k == 6:
            props = [(self.r.choice(["Remove_wildcard", "Remove_regex", "Move_to_start", "Move_to_end"]),
                      self.r.choice(["labels", "app", "x"]) + " app")]
        elif k == 7:
            props = [("Remove_regex", render(good) + " " + self.r.choice(["(", "[a-", "a{2,1}", "*x"]))]
        elif k == 8:
            props = [("Condition", self.r.choice(["Matching_keys_have_matching_values",
                                                  "Matching_keys_do_not_have_matching_values"]) + " " +
                      render(good) + " ^a"), ("Set", "$m yes")]
        elif k == 9:
            props = [("Condition", self.r.choice(["A_key_matches ", "No_key_matches "]) + bad + " ^a"),
                     ("Set", "$m yes")]
        elif k == 10:
            # accepted: path tokens are not compiled as regexes
            props = [(self.r.choice(["Set", "Add"]), "$meta['x('] " + self.r.choice(["v", "(", "[z"]))]
        else:
            props = [("Set", render(good) + " v"), (self.r.choice(["Set", "Remove", "Copy"]),
                                                     self.r.choice(self.BAD_PATHS) + " w")]
            if props[1][0] == "Remove":
                props[1] = ("Remove", props[1][1].split(" ")[0])
        return props, recs, None

    def c_chains(self):
        base = self.ensure_nested(self.g.record())
        props = []
        makers = [self.c_set_add, self.c_remove, self.c_rename, self.c_copy, self.c_keysets]
        recs = None
        for _ in range(self.r.randint(3, 6)):
            p, rr, _ = self.r.choice(makers)()
            props += [x for x in p if x[0] != "Condition"]
            if recs is None:
                recs = rr
        if self.r.random() < 0.5:
            cp, _, _ = self.r.choice([self.c_conditions, self.c_cond_keysets])()
            props = [x for x in cp if x[0] == "Condition"] + props
        # the chain runs on records built around the first sub-case's target plus two fresh ones
        recs = recs[:2] + [self.ensure_nested(self.g.record()), base]
        return props, recs, None

    def c_legacy(self):
        rec = self.g.record()
        keys = [k for k, _ in rec]
        props = []
        for _ in range(self.r.randint(1, 3)):
            op = self.r.choice(["Set", "Add", "Remove", "Rename", "Hard_rename", "Copy", "Hard_copy",
                                "Remove_wildcard", "Remove_regex", "Move_to_start", "Move_to_end"])
            k = self.r.choice(keys + ["fresh", "zz"])
            if op in ("Remove", ):
                props.append((op, k))
            elif op in ("Remove_wildcard", "Move_to_start", "Move_to_end"):
                props.append((op, self.r.choice(["a", "s", "l", "k", "u", "t"])))
            elif op == "Remove_regex":
                props.append((op, self.r.choice(["^a", "s$", "^(log|level)$", "e"])))
            elif op in ("Set", "Add"):
                props.append((op, k + " " + self.r.choice(["v", "1", "x"])))
            else:
                # same-name Hard_copy corrupts the record in the untouched tree (a legacy bug): not a regression case
                props.append((op, k + " " + self.r.choice([x for x in keys + ["new"] if x != k])))
        if self.r.random() < 0.5:
            ct = self.r.choice(["Key_exists", "Key_does_not_exist", "Key_value_equals", "Key_value_does_not_equal",
                                "Key_value_matches", "A_key_matches", "No_key_matches",
                                "Matching_keys_have_matching_values"])
            if ct in ("Key_exists", "Key_does_not_exist"):
                props.insert(0, ("Condition", ct + " " + self.r.choice(keys + ["nope"])))
            elif ct in ("A_key_matches", "No_key_matches"):
                props.insert(0, ("Condition", ct + " " + self.r.choice(["^l", "^z", "s$"])))
            elif ct == "Matching_keys_have_matching_values":
                props.insert(0, ("Condition", ct + " ^l ^[a-z]+$"))
            else:
                props.insert(0, ("Condition", ct + " " + self.r.choice(keys) + " " + self.r.choice(["prod", "^e"])))
        recs = [rec, self.g.record(), self.g.record()]
        return props, recs, None


BUCKETS = {
    "set_add": 400, "remove": 250, "rename": 400, "copy": 400, "keysets": 350, "conditions": 400,
    "cond_keysets": 300, "config": 300, "chains": 400, "legacy": 400,
}


def main():
    seed = int(sys.argv[1])
    scale = float(sys.argv[2])
    out = Path(sys.argv[3])
    cm = CaseMaker(seed)
    seen = set()
    n = 0
    with out.open("w") as f:
        for bucket, count in BUCKETS.items():
            want = max(1, int(count * scale))
            made = 0
            tries = 0
            while made < want and tries < want * 50:
                tries += 1
                props, recs, _ = getattr(cm, "c_" + bucket)()
                key = json.dumps([props, [packb(r).hex() for r in recs]])
                if key in seen:
                    continue
                seen.add(key)
                status, outs = oracle.apply_case(props, recs)
                if bucket not in ("legacy", "config") and status == "ok" and \
                        all(packb(a) == packb(b) for a, b in zip(recs, outs)):
                    continue          # no visible effect on any record: not informative
                n += 1
                made += 1
                f.write(json.dumps({
                    "id": "%s-%05d" % (bucket, made), "bucket": bucket, "props": [list(p) for p in props],
                    "records": [packb(r).hex() for r in recs], "status": status,
                    "outputs": [packb(o).hex() for o in outs] if outs is not None else None,
                }) + "\n")
    print("wrote", n, "cases to", out)


if __name__ == "__main__":
    main()
