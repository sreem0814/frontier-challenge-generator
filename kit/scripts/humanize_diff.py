#!/usr/bin/env python3
"""humanize_diff.py: check that a humanize pass changed only the wording (written 2026-10-08 by prompt 4).

Usage: python3 -I scripts/humanize_diff.py <before.md> <after.md> [--allow-new N]

Run it on the text before and after the humanize-writing step (spec §4.6; CLAUDE.md hard rule). It compares
  - every /app path, every file name, every URL;
  - every number, with its unit when one follows (12 MB, 0.5 %, 3 s, 1e-6, 2025-04-29, v1.2.3);
  - requirement keywords (must, exactly, at least, at most, within, only, never, each, every, all, no more than,
    no fewer than, do not, must not, required) by count;
  - sentences: an "after" sentence with no close "before" sentence (difflib ratio < 0.6 and < 50 % content-word
    overlap) counts as ADDED; a "before" sentence with no close "after" sentence counts as DROPPED.
It prints every difference and exits 1 on any loss of a path, file, URL, number or keyword, on any added
sentence (the humanizer's "personality" pass must not add content; spec §4.2 no filler), and on any dropped
sentence. Exit 0 = safe to show the user for approval (the user still reads and approves the final text).
HTML comments are ignored. --allow-new N tolerates N added sentences (only when the user asked for an addition).
"""
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

UNITS = (r"%|percent|ms|s|sec|secs|seconds?|minutes?|min|h|hours?|days?|kb|mb|gb|tb|kib|mib|gib|b|bytes?|bits?|"
         r"hz|khz|mhz|ghz|px|pt|dpi|bpm|db|k|°c|°f|c|f|m|cm|mm|nm|µm|um|km|g|kg|mg|µg|ug|l|ml|mol|mmol|µmol|umol|"
         r"m/s|v|mv|a|ma|w|kw|mw|j|kj|ev|kev|mev|pa|kpa|mpa|bar|atm|ppm|ppb|usd|eur|gbp|jpy|bp|bps|x|rows?|columns?|"
         r"lines?|files?|decimals?|digits?|samples?|frames?|steps?|epochs?|trials?|runs?|times")
NUM = re.compile(r"(?<![\w.])([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?:[-/:.]\d+)*)"
                 r"(?:\s*(%s)\b|\s*(%%))?" % UNITS, re.I)
APP = re.compile(r"/app(?:/[A-Za-z0-9_.@+-]+)*/?")
FILE = re.compile(r"(?<![\w/.-])[A-Za-z0-9_][A-Za-z0-9_.-]*\.[A-Za-z][A-Za-z0-9]{0,5}\b")
URL = re.compile(r"https?://\S+")
KEYWORDS = ["must not", "must", "exactly", "at least", "at most", "within", "only", "never", "each", "every",
            "all", "no more than", "no fewer than", "no less than", "do not", "don't", "required", "shall", "always"]
STOP = set("the a an of and or to in on for with is are be by as at it this that from into each its their".split())


def load(p):
    return re.sub(r"<!--.*?-->", "", Path(p).read_text(encoding="utf-8"), flags=re.S)


def norm_num(m):
    n = m.group(1).replace(",", "")
    u = (m.group(2) or m.group(3) or "").lower()
    return f"{n} {u}".strip()


def keyword_counts(t):
    low = " " + re.sub(r"\s+", " ", t.lower()) + " "
    c = Counter()
    for k in sorted(KEYWORDS, key=len, reverse=True):  # longest first, then blank them out
        n = len(re.findall(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", low))
        c[k] = n
        low = re.sub(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", " ", low)
    return c


def sentences(t):
    t = re.sub(r"```.*?```", lambda m: m.group(0).replace("\n", " "), t, flags=re.S)
    parts = re.split(r"(?<=[.!?:])\s+(?=[A-Z0-9`\"'(/-])|\n\s*\n|\n\s*[-*] |\n\s*\d+[.)] ", t)
    return [re.sub(r"\s+", " ", p).strip(" -*") for p in parts if len(re.findall(r"\w+", p)) >= 3]


def content(s):
    return {w for w in re.findall(r"[a-z0-9_./-]+", s.lower()) if w not in STOP}


def close(s, pool):
    cs = content(s)
    for o in pool:
        if difflib.SequenceMatcher(None, s.lower(), o.lower()).ratio() >= 0.6:
            return True
        co = content(o)
        if cs and len(cs & co) / len(cs) >= 0.5 and len(cs & co) / max(1, len(co)) >= 0.5:
            return True
    return False


def multiset_loss(name, before, after, out):
    b, a = Counter(before), Counter(after)
    lost = b - a
    added = a - b
    for k, n in sorted(lost.items()):
        out.append(("LOST", name, f"{k}" + (f" (x{n})" if n > 1 else "")))
    for k, n in sorted(added.items()):
        out.append(("NEW", name, f"{k}" + (f" (x{n})" if n > 1 else "")))


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    allow = 0
    if "--allow-new" in argv:
        allow = int(argv[argv.index("--allow-new") + 1]); args = [a for a in args if a != str(allow)]
    if len(args) != 2:
        print(__doc__); return 2
    b, a = load(args[0]), load(args[1])
    out = []
    multiset_loss("url", URL.findall(b), URL.findall(a), out)
    b2, a2 = URL.sub(" ", b), URL.sub(" ", a)
    multiset_loss("/app path", [p.rstrip("/.") for p in APP.findall(b2)], [p.rstrip("/.") for p in APP.findall(a2)], out)
    fb = [f for f in FILE.findall(APP.sub(" ", b2)) if not re.fullmatch(r"[\d.]+", f)]
    fa = [f for f in FILE.findall(APP.sub(" ", a2)) if not re.fullmatch(r"[\d.]+", f)]
    multiset_loss("file name", fb, fa, out)
    multiset_loss("number", [norm_num(m) for m in NUM.finditer(APP.sub(" ", b2))],
                  [norm_num(m) for m in NUM.finditer(APP.sub(" ", a2))], out)
    kb, ka = keyword_counts(b2), keyword_counts(a2)
    for k in KEYWORDS:
        if ka[k] < kb[k]:
            out.append(("LOST", "keyword", f"'{k}' {kb[k]} -> {ka[k]}"))
        elif ka[k] > kb[k]:
            out.append(("NEW", "keyword", f"'{k}' {kb[k]} -> {ka[k]}"))
    sb, sa = sentences(b), sentences(a)
    added = [s for s in sa if not close(s, sb)]
    dropped = [s for s in sb if not close(s, sa)]
    for s in added:
        out.append(("ADDED", "sentence", s[:160]))
    for s in dropped:
        out.append(("DROPPED", "sentence", s[:160]))
    blocking = [o for o in out if o[0] in ("LOST", "DROPPED") or (o[0] == "ADDED")]
    n_added = sum(1 for o in out if o[0] == "ADDED")
    if n_added <= allow:
        blocking = [o for o in blocking if o[0] != "ADDED"]
    # A NEW number, path or keyword is also content the humanizer added: block it too.
    blocking += [o for o in out if o[0] == "NEW" and o[1] in ("/app path", "number", "url", "file name")]
    for kind, what, msg in out:
        print(f"{kind:8} {what:10} {msg}")
    wb, wa = len(re.findall(r"\w+", b)), len(re.findall(r"\w+", a))
    print(f"words {wb} -> {wa}; sentences {len(sb)} -> {len(sa)}")
    if blocking:
        print(f"humanize_diff: BLOCK ({len(blocking)} blocking difference(s)); fix the after-text, then re-run")
        return 1
    print("humanize_diff: PASS (paths, files, numbers, units and requirement keywords preserved; no sentence added "
          "or dropped). The user still reads and approves the final text.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
