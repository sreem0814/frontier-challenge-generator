#!/usr/bin/env python3
"""selfcheck.py: build xlsdump the way the grader does and score it on the sample workbooks.

    python3 /app/tools/selfcheck.py                  # build, gates, all samples, per-format scores
    python3 /app/tools/selfcheck.py --only .xlsb     # samples whose name contains ".xlsb"
    python3 /app/tools/selfcheck.py --show 20        # print the first difference of up to 20 failing units
    python3 /app/tools/selfcheck.py --no-build --bin /tmp/xlsdump

The score printed here uses the same units and the same formula as the hidden grading set, but on the
visible samples only; the hidden set is larger and uses other workbooks.
"""
import argparse
import gzip
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import units as U  # noqa: E402

MODULE = "/app/calamine-go"
SAMPLES = "/app/samples"
BUCKETS = ("xls", "xlsx", "xlsb", "ods", "vba", "pictures", "objects")
FORBIDDEN_IMPORTS = {"C", "os/exec", "plugin", "syscall", "runtime/cgo", "golang.org/x/sys/unix",
                     "golang.org/x/sys/execabs", "internal/syscall/unix", "internal/syscall/exec"}
FORBIDDEN_TOKENS = re.compile(r"go:linkname|go:cgo_|StartProcess|ForkExec|#cgo|import\s+\"C\"")

ap = argparse.ArgumentParser()
ap.add_argument("--bin", default="/tmp/selfcheck/xlsdump")
ap.add_argument("--no-build", action="store_true")
ap.add_argument("--only", default="")
ap.add_argument("--show", type=int, default=5)
ap.add_argument("-j", type=int, default=4)
ap.add_argument("--timeout", type=float, default=20)
a = ap.parse_args()

env = dict(os.environ, GOFLAGS="-mod=vendor", GOTOOLCHAIN="local", GOPROXY="off", CGO_ENABLED="0")

if not a.no_build:
    # Gate 1: forbidden constructs in your own packages (vendor/ is not yours).
    bad = []
    for dp, dns, fns in os.walk(MODULE):
        dns[:] = [d for d in dns if not (dp == MODULE and d in ("vendor", ".git"))]
        for fn in fns:
            p = os.path.join(dp, fn)
            if fn.endswith((".s", ".c", ".h", ".cc", ".cpp", ".syso")):
                bad.append(f"{p}: non-Go source or object file")
            elif fn.endswith(".go"):
                m = FORBIDDEN_TOKENS.search(open(p, encoding="utf-8", errors="replace").read())
                if m:
                    bad.append(f"{p}: uses {m.group(0)}")
    lst = subprocess.run(["go", "list", "-deps", "-f",
                          "{{if not .Standard}}{{.ImportPath}}{{end}}|{{join .Imports \",\"}}|{{.Standard}}",
                          "./cmd/xlsdump"], cwd=MODULE, env=env, capture_output=True, text=True)
    for line in lst.stdout.splitlines():
        name, imps, std = (line.split("|") + ["", "", ""])[:3]
        if std == "true" or not name or name.startswith("golang.org/x/text"):
            continue
        for imp in imps.split(","):
            if imp in FORBIDDEN_IMPORTS:
                bad.append(f"{name}: imports {imp}")
    if bad:
        print("GATE FAIL (the grader scores this 0):")
        for b in sorted(set(bad)):
            print("  " + b)
        sys.exit(1)
    # Gate 2: the build. The grader restores go.mod, go.sum and vendor/ to the shipped versions first.
    for f in ("go.mod", "go.sum"):
        if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", f], cwd=MODULE).returncode != 0:
            print(f"warning: {f} differs from the starting point; the grader restores the shipped file")
    os.makedirs(os.path.dirname(a.bin), exist_ok=True)
    t0 = time.time()
    b = subprocess.run(["go", "build", "-trimpath", "-o", a.bin, "./cmd/xlsdump"], cwd=MODULE, env=env)
    if b.returncode != 0:
        print("BUILD FAIL (the grader scores this 0)")
        sys.exit(1)
    print(f"build ok ({time.time() - t0:.1f}s): {a.bin}")

wbdir = os.path.join(SAMPLES, "workbooks")
expdir = os.path.join(SAMPLES, "expected")
names = sorted(n for n in os.listdir(wbdir) if a.only in n)


def load_expected(name):
    p = os.path.join(expdir, name + ".json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    return json.load(gzip.open(p + ".gz"))


def first_diff(uid, payload, cand):
    try:
        if uid == "sheets":
            got = [[s.get("name"), s.get("type"), s.get("visible")] for s in cand.get("sheets", [])]
            return f"sheets: expected {payload!r:.300} got {got!r:.300}"
        if uid == "names":
            return f"names: expected {payload!r:.300} got {cand.get('names')!r:.300}"
        if uid in ("props", "vba_refs") or uid.split(":")[0] in ("vba_mod", "pic", "table", "pivot"):
            key = {"props": "properties", "vba_refs": "vba", "vba_mod": "vba", "pic": "pictures",
                   "table": "tables", "pivot": "pivots"}[uid.split(":")[0]]
            return f"{uid}: expected {payload!r:.300} got {key}={cand.get(key)!r:.300}"
        kind, idx = uid.split(":")
        if kind == "links":
            kind = "hyperlinks"
        s = (cand.get("sheets") or [])[int(idx)]
        if kind == "cells":
            if s.get("dims") != payload["dims"]:
                return f"{uid}: dims expected {payload['dims']} got {s.get('dims')}"
            got = s.get("cells") or []
            for i, e in enumerate(payload["cells"]):
                if i >= len(got) or not U._cell_eq(e, got[i]):
                    return f"{uid}: cell #{i} expected {e!r:.200} got {(got[i] if i < len(got) else None)!r:.200}"
            return f"{uid}: {len(got)} cells, expected {len(payload['cells'])}"
        got = s.get(kind) or []
        if not isinstance(got, list):
            return f"{uid}: expected a list, got {got!r:.100}"
        for i, e in enumerate(payload):
            if i >= len(got) or got[i] != e:
                return f"{uid}: item #{i} expected {e!r:.200} got {(got[i] if i < len(got) else None)!r:.200}"
        return f"{uid}: {len(got)} items, expected {len(payload)}"
    except Exception as ex:
        return f"{uid}: {type(ex).__name__}: {ex}"


def run(name):
    exp = load_expected(name)
    us = U.units(exp)
    if not us:
        return name, None, [], None, ""
    t0 = time.time()
    try:
        p = subprocess.run([a.bin, os.path.join(wbdir, name)], capture_output=True, timeout=a.timeout)
        cand = json.loads(p.stdout.decode("utf-8")) if p.returncode == 0 else None
        why = "" if p.returncode == 0 else f"exit {p.returncode}: {p.stderr.decode(errors='replace')[:200]}"
    except subprocess.TimeoutExpired:
        cand, why = None, "timeout"
    except Exception as ex:
        cand, why = None, f"invalid JSON ({type(ex).__name__})"
    res = [(U.bucket(uid, exp["format"]), uid, pl, cand is not None and U.unit_ok(uid, pl, cand, exp)) for uid, pl in us]
    return name, exp["format"], res, cand, why or f"{time.time() - t0:.2f}s"


stats = {b: [0, 0.0, 0, 0] for b in BUCKETS}
fails = []
with ThreadPoolExecutor(a.j) as ex:
    for name, fmt, res, cand, why in ex.map(run, names):
        if fmt is None:
            continue
        for bk in sorted(set(x[0] for x in res)):
            rb = [x[3] for x in res if x[0] == bk]
            ok = sum(1 for r in rb if r)
            st = stats[bk]
            st[0] += 1
            st[1] += ok / len(rb)
            st[2] += ok
            st[3] += len(rb)
        for _, uid, pl, r in res:
            if not r:
                fails.append((name, uid, pl, cand, why))

print(f"{'bucket':8s} {'workbooks':>9s} {'units':>13s} {'score':>7s}")
scores = []
for b in BUCKETS:
    n, s, ok, tot = stats[b]
    sc = s / n if n else 0.0
    scores.append(sc)
    print(f"{b:8s} {n:9d} {ok:6d}/{tot:<6d} {sc:7.4f}")
print(f"estimated reward (mean of the seven bucket scores): {sum(scores) / len(scores):.4f}")
print(f"failing units: {len(fails)}")
for name, uid, pl, cand, why in fails[: a.show]:
    if cand is None:
        print(f"  {name} {uid}: no output ({why})")
    else:
        print(f"  {name} {first_diff(uid, pl, cand)}")
