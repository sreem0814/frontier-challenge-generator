"""A narrow implementation of the contract: what a strong first hour plausibly delivers.

Paths work for Set/Add/Remove and for the name forms of Rename/Hard_rename/Copy/Hard_copy, and for the
key-addressing conditions (generously: strict resolution, arrays included). Not covered: creating missing
intermediate maps (Set/Add only append a last key into an existing map, as flb_ra_append_kv_pair does),
destination paths, the scoped key-set rules and the scoped key-set conditions.
Used only to estimate core_share; it is not part of the bundle.
"""
import copy
import oracle
from mpcodec import MMap

_full_path_set = oracle.path_set


def narrow_set(rec, steps, val):
    if oracle.resolve(rec, steps) is not None:
        return _full_path_set(rec, steps, val)
    if steps[-1][0] != "k":
        return None
    if len(steps) == 1:
        return _full_path_set(rec, steps, val)
    parent = oracle.resolve(rec, steps[:-1])
    if parent is None or not isinstance(oracle.slot_get(*parent), MMap):
        return None
    return _full_path_set(rec, steps, val)


_orig_path_rule = oracle.path_rule


def narrow_path_rule(rec, r):
    if r.type in oracle.KEYSET_RULES:
        return None
    if getattr(r, "dst", None) is not None and r.type in ("rename", "hard_rename", "copy", "hard_copy"):
        return None
    return _orig_path_rule(rec, r)


_orig_build_cond = oracle.build_cond


def narrow_build_cond(value):
    c = _orig_build_cond(value)
    if c.type in ("matching_keys_have_matching_values", "matching_keys_do_not_have_matching_values",
                  "a_key_matches", "no_key_matches") and c.path is not None:
        raise oracle.InitFail("not supported in the narrow version")
    return c


_orig_build_path_rule = oracle.build_path_rule


def narrow_build_path_rule(r, lname, toks):
    if lname in oracle.KEYSET_RULES and len(toks) == 2:
        raise oracle.InitFail("not supported in the narrow version")
    return _orig_build_path_rule(r, lname, toks)


def install():
    oracle.path_set = narrow_set
    oracle.path_rule = narrow_path_rule
    oracle.build_cond = narrow_build_cond
    oracle.build_path_rule = narrow_build_path_rule


def apply_case(props, records):
    install()
    try:
        return oracle.apply_case(props, copy.deepcopy(records))
    finally:
        oracle.path_set = _full_path_set
        oracle.path_rule = _orig_path_rule
        oracle.build_cond = _orig_build_cond
        oracle.build_path_rule = _orig_build_path_rule
