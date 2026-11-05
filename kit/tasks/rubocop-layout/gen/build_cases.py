#!/usr/bin/env python3
"""gen/build_cases.py: build and freeze the case sets (runs inside the dev container on the runner).

  python3 build_cases.py all          # inputs, two reference runs, freeze
Paths (container): /dev0/ref (full rubocop v1.92.0 tree), /dev0/gen, /dev0/tests/layout_probe.rb,
/dev0/work (scratch), /dev0/out (frozen output: hidden/ and samples/).

Units
  spec    one upstream Layout spec input (cop, the spec's own config, source), from spec_hook.rb
  vary    a spec input after 1-3 layout-only mutations (same cop and config)
  corpus  one real Ruby file after layout-only mutations, one cop, a randomized config for that cop
  dept    one mutated corpus file, all Layout cops enabled by default together, compare the final source
A cop unit is kept only when the reference reports at least one offense for that cop; a dept unit only
when the reference changes the file. Units whose two reference runs differ, or that error, are dropped.
"""
import gzip
import hashlib
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

W = "/dev0/work"
OUT = "/dev0/out"
REF = "/dev0/ref"
PROBE = "/dev0/tests/layout_probe.rb"
JOBS = 6
SEED = 20261021


def h(s):
    return int(hashlib.sha256(s.encode()).hexdigest()[:12], 16)


def ruby(script, inp, cwd=REF):
    p = subprocess.run(["bundle", "exec", "ruby", script], input=inp, capture_output=True, text=True, cwd=cwd)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-3000:])
        raise SystemExit("ruby failed: " + script)
    return p.stdout


def sharded(script, lines, cwd=REF, jobs=JOBS):
    shards = [lines[i::jobs] for i in range(jobs)]
    with ThreadPoolExecutor(jobs) as ex:
        outs = list(ex.map(lambda sh: ruby(script, "".join(sh), cwd), shards))
    res = {}
    for o in outs:
        for l in o.splitlines():
            r = json.loads(l)
            res[r["id"]] = r
    return res


def layout_defaults():
    p = os.path.join(W, "layout_defaults.json")
    if not os.path.exists(p):
        code = ("require 'yaml'; require 'json'; a = YAML.safe_load(File.read('config/default.yml'), "
                "permitted_classes: [Regexp, Symbol], aliases: true); "
                "puts JSON.generate(a.select { |k, _| k.start_with?('Layout/') })")
        out = subprocess.run(["ruby", "-e", code], capture_output=True, text=True, cwd=REF, check=True).stdout
        open(p, "w").write(out)
    return json.load(open(p))


NUMERIC_CHOICES = {
    "Max": [60, 80, 100, 120], "Width": [2, 3, 4], "IndentationWidth": [None, 2, 4],
    "MinBodyLength": [1, 2, 3], "NumberOfEmptyLines": [1, 2], "MaximumLineLength": [0, 60, 80],
}
FIXED_KEYS = {"Enabled", "Safe", "SafeAutoCorrect", "AutoCorrect", "VersionAdded", "VersionChanged",
              "Description", "StyleGuide", "Reference", "References", "Include", "Exclude", "Details"}


def random_cop_config(defaults, cop, rng):
    d = defaults.get(cop, {})
    cfg = {"Enabled": True, "AutoCorrect": "always"}
    for k, v in d.items():
        if k in FIXED_KEYS or k.startswith("Supported"):
            continue
        sup = d.get("Supported" + k)
        if isinstance(sup, list) and sup and rng.random() < 0.6:
            cfg[k] = rng.choice(sup)
        elif isinstance(v, bool) and rng.random() < 0.35:
            cfg[k] = not v
        elif k in NUMERIC_CHOICES and rng.random() < 0.5:
            cfg[k] = rng.choice(NUMERIC_CHOICES[k])
    if cop == "Layout/LineLength" and "Max" not in cfg:
        cfg["Max"] = rng.choice([60, 80, 100])
    return cfg


def stage_inputs():
    rng = random.Random(SEED)
    defaults = layout_defaults()
    cops = sorted(defaults)
    assert len(cops) == 100, len(cops)
    enabled = [c for c in cops if defaults[c].get("Enabled") is True]

    # spec inputs (unique, JSON-safe, no unusual cop options)
    seen, spec = set(), []
    for l in open(os.path.join(W, "spec_cases.jsonl")):
        r = json.loads(l)
        if not r["json_safe"] or r["extra_options"]:
            continue
        k = json.dumps([r["cop"], r["config"], r["source"], r["path"], r["ruby"], r["engine"]], sort_keys=True)
        if k in seen:
            continue
        seen.add(k)
        spec.append(r)
    cases = []
    for i, r in enumerate(spec):
        base = {"cops": [r["cop"]], "config": r["config"], "path": r["path"], "ruby": r["ruby"],
                "engine": r["engine"], "defaults": False, "kind": "spec", "group": r["example"]}
        cases.append(dict(base, id=f"spec-{i:05d}", source=r["source"]))
    # variants of spec inputs
    jobs = []
    for i, r in enumerate(spec):
        for k in range(2):
            jobs.append(json.dumps({"id": f"vary-{i:05d}-{k}", "source": r["source"],
                                    "seed": SEED + i * 7 + k, "count": rng.choice([1, 2, 3])}) + "\n")
    muts = sharded("/dev0/gen/mutate.rb", jobs)
    for i, r in enumerate(spec):
        for k in range(2):
            m = muts.get(f"vary-{i:05d}-{k}")
            if not m or not m["ok"] or not m["applied"] or m["source"] == r["source"]:
                continue
            cases.append({"id": f"vary-{i:05d}-{k}", "cops": [r["cop"]], "config": r["config"], "path": r["path"],
                          "ruby": r["ruby"], "engine": r["engine"], "defaults": False, "kind": "vary",
                          "group": r["example"], "source": m["source"]})

    # corpus files: disjoint hidden and sample sets
    files = json.load(open(os.path.join(W, "corpus_files.json")))
    rng.shuffle(files)
    chosen = files[:520]
    jobs = []
    for j, f in enumerate(chosen):
        src = open(f, encoding="utf-8").read()
        n = src.count("\n")
        jobs.append(json.dumps({"id": f"file-{j:04d}", "source": src, "seed": SEED + 1000 + j,
                                "count": max(6, min(30, n // 10))}) + "\n")
    muts = sharded("/dev0/gen/mutate.rb", jobs)
    for j, f in enumerate(chosen):
        m = muts[f"file-{j:04d}"]
        if not m["ok"] or len(m["applied"]) < 3:
            continue
        group = "corpus:" + f
        for cop in cops:
            cfg = {"AllCops": {"TargetRubyVersion": 3.3}, cop: random_cop_config(defaults, cop, rng)}
            cases.append({"id": f"corpus-{j:04d}-{cop.split('/')[1]}", "cops": [cop], "config": cfg, "path": None,
                          "ruby": 3.3, "engine": "parser_whitequark", "defaults": True, "kind": "corpus",
                          "group": group, "source": m["source"], "origin": f})
        cases.append({"id": f"dept-{j:04d}", "cops": enabled, "path": None, "ruby": 3.3,
                      "engine": "parser_whitequark", "defaults": True, "kind": "dept", "group": group,
                      "config": {"AllCops": {"TargetRubyVersion": 3.3}}, "source": m["source"], "origin": f})
    with open(os.path.join(W, "cases_in.jsonl"), "w") as fo:
        for c in cases:
            fo.write(json.dumps(c) + "\n")
    print("inputs", len(cases))


def stage_reference():
    lines = open(os.path.join(W, "cases_in.jsonl")).readlines()
    probe_lines = [json.dumps({k: v for k, v in json.loads(l).items() if k not in ("kind", "group", "origin")}) + "\n"
                   for l in lines]
    for tag in ("a", "b"):
        res = sharded(PROBE, probe_lines)
        with open(os.path.join(W, f"ref_{tag}.jsonl"), "w") as fo:
            for r in res.values():
                fo.write(json.dumps(r) + "\n")
        print("reference run", tag, len(res))


def stage_freeze():
    cases = [json.loads(l) for l in open(os.path.join(W, "cases_in.jsonl"))]
    ra = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(W, "ref_a.jsonl"))}
    rb = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(W, "ref_b.jsonl"))}
    kept, drop = [], {"error": 0, "nondet": 0, "empty": 0}
    for c in cases:
        a, b = ra.get(c["id"]), rb.get(c["id"])
        if a is None or b is None or a["error"] or b["error"]:
            drop["error"] += 1
            continue
        if a != b:
            drop["nondet"] += 1
            continue
        if c["kind"] == "dept":
            if a["corrected"] == c["source"]:
                drop["empty"] += 1
                continue
            exp = {"corrected": a["corrected"]}
        else:
            offs = a["offenses"].get(c["cops"][0], [])
            if not offs:
                drop["empty"] += 1
                continue
            exp = {"offenses": offs, "corrected": a["corrected"]}
        c["expected"] = exp
        kept.append(c)
    print("kept", len(kept), drop)

    # split: spec groups (one upstream example and its variants) and corpus files go wholly to one side
    corpus_groups = sorted({c["group"] for c in kept if c["kind"] in ("corpus", "dept")})
    rng = random.Random(SEED + 5)
    rng.shuffle(corpus_groups)
    sample_files = set(corpus_groups[:60])

    def side0(c):
        if c["kind"] in ("corpus", "dept"):
            return "samples" if c["group"] in sample_files else "hidden"
        return "samples" if h("g:" + c["group"]) % 100 < 12 else "hidden"

    # every cop gets at least 3 sample units: move whole spec groups from the hidden side if needed
    moved = set()
    def side2(c):
        return "samples" if c["group"] in moved else side0(c)
    for cop in sorted({c["cops"][0] for c in kept if c["kind"] != "dept"}):
        have = sum(1 for c in kept if c["kind"] != "dept" and c["cops"][0] == cop and side2(c) == "samples")
        groups = sorted({c["group"] for c in kept if c["kind"] in ("spec", "vary") and c["cops"][0] == cop
                         and side2(c) == "hidden"}, key=lambda g: h("m:" + g))
        while have < 3 and groups:
            g = groups.pop(0)
            moved.add(g)
            have += sum(1 for c in kept if c["group"] == g and c["cops"][0] == cop)
    side = side2

    os.makedirs(OUT, exist_ok=True)
    stats = {}
    for name in ("hidden", "samples"):
        sel = [c for c in kept if side(c) == name]
        for c in sel:
            c.pop("origin", None)
        sel.sort(key=lambda c: c["id"])
        with gzip.GzipFile(os.path.join(OUT, f"{name}.jsonl.gz"), "wb", mtime=0) as fo:
            for c in sel:
                fo.write((json.dumps(c, sort_keys=True) + "\n").encode())
        per = {}
        for c in sel:
            per.setdefault(c["kind"], 0)
            per[c["kind"]] += 1
        cops = {}
        for c in sel:
            if c["kind"] != "dept":
                cops[c["cops"][0]] = cops.get(c["cops"][0], 0) + 1
        stats[name] = {"units": len(sel), "by_kind": per, "cops_covered": len(cops),
                       "min_cop_units": min(cops.values()) if cops else 0,
                       "thin_cops": sorted(k for k, v in cops.items() if v < 10)}
    json.dump(stats, open(os.path.join(OUT, "stats.json"), "w"), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    step = sys.argv[1]
    if step in ("inputs", "all"):
        stage_inputs()
    if step in ("reference", "all"):
        stage_reference()
    if step in ("freeze", "all"):
        stage_freeze()
