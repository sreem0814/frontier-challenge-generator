"""units.py: split an expected dump into scored units and compare a candidate dump against them.

Shared by the authoring tools, the grader and /app/tools/selfcheck.py (identical copies).
A unit is one of: the sheet list, the defined names, per sheet its cells (with dims), formulas,
merged regions and hyperlinks, the document properties, each VBA module, the VBA references,
each picture, each table and each pivot table. Units whose expected content is empty or an error
are not scored, so printing empty lists earns nothing.
"""
import math

REL_TOL = 1e-12


def _num_eq(a, b):
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    a, b = float(a), float(b)
    if a == b:
        return True
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b))


def _cell_eq(e, c):
    # e, c: [row, col, tag, value, ...]
    if not isinstance(c, list) or len(c) != len(e):
        return False
    if c[0] != e[0] or c[1] != e[1] or c[2] != e[2]:
        return False
    tag = e[2]
    if tag == "i":
        return isinstance(c[3], int) and not isinstance(c[3], bool) and c[3] == e[3]
    if tag == "f":
        return _num_eq(e[3], c[3])
    if tag == "b":
        return c[3] is e[3]
    if tag == "d":
        return _num_eq(e[3], c[3]) and c[4] == e[4] and c[5] == e[5]
    return c[3] == e[3]  # s, di, du, e


def _val_eq(e, c):
    """Compare two position-less tagged values (["f", 1.5], ["s", "x"], ...) or nulls."""
    if e is None or c is None:
        return e is None and c is None
    if not isinstance(c, list):
        return False
    return _cell_eq([0, 0] + e, [0, 0] + c)


BUCKETS = ("xls", "xlsx", "xlsb", "ods", "vba", "pictures", "objects")


def bucket(uid, fmt):
    """The reward bucket a unit counts towards."""
    kind = uid.split(":")[0]
    if kind in ("vba_mod", "vba_refs"):
        return "vba"
    if kind == "pic":
        return "pictures"
    if kind in ("props", "links", "table", "pivot"):
        return "objects"
    return fmt


def units(expected):
    """Return [(unit_id, payload)] for the scored units of one expected dump."""
    out = []
    if not isinstance(expected, dict) or "error" in expected:
        return out
    sheets = expected.get("sheets") or []
    if sheets:
        out.append(("sheets", [[s["name"], s["type"], s["visible"]] for s in sheets]))
    if expected.get("names"):
        out.append(("names", expected["names"]))
    seen = set()
    for i, s in enumerate(sheets):
        if s["name"] in seen:  # duplicate names read the same sheet twice; score it once
            continue
        seen.add(s["name"])
        if isinstance(s.get("cells"), list) and s["cells"]:
            out.append((f"cells:{i}", {"dims": s["dims"], "cells": s["cells"]}))
        if isinstance(s.get("formulas"), list) and s["formulas"]:
            if not any(isinstance(f[2], str) and f[2].startswith("Unrecognised formula") for f in s["formulas"]):
                out.append((f"formulas:{i}", s["formulas"]))
        if isinstance(s.get("merged"), list) and s["merged"]:
            out.append((f"merged:{i}", s["merged"]))
        if isinstance(s.get("hyperlinks"), list) and s["hyperlinks"]:
            out.append((f"links:{i}", s["hyperlinks"]))
    props = expected.get("properties")
    if isinstance(props, dict) and any(v is not None for v in props.values()):
        out.append(("props", props))
    vba = expected.get("vba")
    if isinstance(vba, dict):
        for name, src in vba.get("modules") or []:
            if src != "error":
                out.append((f"vba_mod:{name}", [name, src]))
        if vba.get("references"):
            out.append(("vba_refs", vba["references"]))
    for i, p in enumerate(expected.get("pictures") or []):
        out.append((f"pic:{i}", p))
    if isinstance(expected.get("tables"), list):
        for i, t in enumerate(expected["tables"]):
            if len(t) == 5 and isinstance(t[4], list):
                out.append((f"table:{i}", t))
    if isinstance(expected.get("pivots"), list):
        for i, p in enumerate(expected["pivots"]):
            if len(p) == 3 and isinstance(p[2], list):
                out.append((f"pivot:{i}", p))
    return out


def _pictures_ok(payload, cand, uid, expected_pics):
    """Pictures are a multiset: the k-th copy of a tuple needs k copies in the candidate list."""
    pics = cand.get("pictures")
    if not isinstance(pics, list):
        return False
    idx = int(uid.split(":")[1])
    k = sum(1 for p in expected_pics[: idx + 1] if p == payload)
    return sum(1 for p in pics if p == payload) >= k


def _sheet(cand, i):
    sheets = cand.get("sheets") if isinstance(cand, dict) else None
    if not isinstance(sheets, list) or i >= len(sheets) or not isinstance(sheets[i], dict):
        return None
    return sheets[i]


def unit_ok(uid, payload, cand, expected=None):
    """True when the candidate dump reproduces the unit exactly."""
    try:
        if not isinstance(cand, dict):
            return False
        kind = uid.split(":")[0]
        if kind == "props":
            got = cand.get("properties")
            return isinstance(got, dict) and all(got.get(k) == v for k, v in payload.items())
        if kind == "vba_mod":
            vba = cand.get("vba")
            mods = vba.get("modules") if isinstance(vba, dict) else None
            if not isinstance(mods, list):
                return False
            for m in mods:
                if isinstance(m, list) and len(m) == 2 and m[0] == payload[0]:
                    return m[1] == payload[1]
            return False
        if kind == "vba_refs":
            vba = cand.get("vba")
            return isinstance(vba, dict) and vba.get("references") == payload
        if kind == "pic":
            return _pictures_ok(payload, cand, uid, (expected or {}).get("pictures") or [payload])
        if kind == "table":
            ts = cand.get("tables")
            i = int(uid.split(":")[1])
            if not isinstance(ts, list) or i >= len(ts) or not isinstance(ts[i], list) or len(ts[i]) != 5:
                return False
            t = ts[i]
            if t[:4] != payload[:4] or not isinstance(t[4], list) or len(t[4]) != len(payload[4]):
                return False
            return all(_cell_eq(e, c) for e, c in zip(payload[4], t[4]))
        if kind == "pivot":
            ps = cand.get("pivots")
            i = int(uid.split(":")[1])
            if not isinstance(ps, list) or i >= len(ps) or not isinstance(ps[i], list) or len(ps[i]) != 3:
                return False
            p = ps[i]
            if p[:2] != payload[:2] or not isinstance(p[2], list) or len(p[2]) != len(payload[2]):
                return False
            for er, cr in zip(payload[2], p[2]):
                if not isinstance(cr, list) or len(cr) != len(er):
                    return False
                if not all(_val_eq(e, c) for e, c in zip(er, cr)):
                    return False
            return True
        if kind == "links":
            s = _sheet(cand, int(uid.split(":")[1]))
            return s is not None and s.get("hyperlinks") == payload
        if uid == "sheets":
            cs = cand.get("sheets")
            if not isinstance(cs, list) or len(cs) != len(payload):
                return False
            return all(isinstance(s, dict) and [s.get("name"), s.get("type"), s.get("visible")] == p
                       for s, p in zip(cs, payload))
        if uid == "names":
            return cand.get("names") == payload
        kind, idx = uid.split(":")
        s = _sheet(cand, int(idx))
        if s is None:
            return False
        if kind == "cells":
            if s.get("dims") != payload["dims"]:
                return False
            cc = s.get("cells")
            if not isinstance(cc, list) or len(cc) != len(payload["cells"]):
                return False
            return all(_cell_eq(e, c) for e, c in zip(payload["cells"], cc))
        if kind == "formulas":
            return s.get("formulas") == payload
        if kind == "merged":
            return s.get("merged") == payload
    except Exception:
        return False
    return False
