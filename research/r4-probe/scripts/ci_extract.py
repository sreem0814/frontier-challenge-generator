"""Static test-command extraction from fetched CI configs and manifests (text only).
usage: python3 -I ci_extract.py <repos-dir> <sample.txt> <pool.txt>  -> per-repo JSONL to stdout, summary to stderr"""
import collections, glob, json, os, re, sys
import yaml

TEST_RX = [  # (family, regex) checked against each `run:` line
    ("cargo", r"\bcargo\s+(\+\S+\s+)?(test|nextest|hack\s+test|llvm-cov)\b"),
    ("go", r"\bgo\s+test\b|\bgotestsum\b"),
    ("ctest", r"\bctest\b|cmake\s+--build\s+\S+\s+--target\s+(test|check)\b"),
    ("meson", r"\bmeson\s+test\b|\bninja\s+(-C\s+\S+\s+)?test\b"),
    ("pytest", r"\bpytest\b|python[\d.]*\s+-m\s+pytest\b|\bunittest\b"),
    ("tox", r"\btox\b(?!\.ini)"), ("nox", r"\bnox\b"), ("hatch", r"\bhatch\s+(run\s+\S*test|test)\b"),
    ("node", r"\b(npm|pnpm|yarn|bun)\s+(run\s+)?(test|ci-test|test:\S+)\b|\bnpx\s+(jest|vitest|mocha)\b|\bnode\s+--test\b"),
    ("make", r"\bmake\b[^\n|;&]*\b(test|tests|check|unittest|ci-test)\b"),
    ("just", r"\bjust\s+\S*test"), ("bazel", r"\bbazel(isk)?\s+test\b"), ("zig", r"\bzig\s+build\s+test\b"),
    ("script", r"(^|\s)\.?/?[\w./-]*(test|check)[\w.-]*\.(sh|py)\b"),
]
INSTALL_RX = re.compile(r"\b(pip3?|uv\s+pip|uv\s+tool|pipx|apt(-get)?|brew|cargo|go|npm|pnpm|yarn|gem)\s+(-\S+\s+)*(install|add|i)\b")
ACTION_RX = [("cargo", r"actions-rs/cargo|clechasseur/rs-cargo"), ("node", r"cypress-io/github-action"),
             ("ctest", r"threeal/ctest-action|lukka/run-cmake")]
FAMILY_OF = {"rust": {"cargo"}, "go": {"go"}, "cmake": {"ctest"}, "meson": {"meson"}, "python": {"pytest", "tox", "nox", "hatch"},
             "node": {"node"}, "autotools": {"make"}, "make": {"make"}}
WRAPPERS = {"make", "just", "script", "tox", "nox", "hatch"}


def eco_of(root):
    s = set(root)
    for eco, marks in (("rust", ["Cargo.toml"]), ("go", ["go.mod"]), ("meson", ["meson.build"]), ("cmake", ["CMakeLists.txt"]),
                       ("autotools", ["configure.ac", "configure", "Makefile.am"]), ("node", ["package.json"]),
                       ("python", ["pyproject.toml", "setup.py", "setup.cfg"]), ("make", ["Makefile", "GNUmakefile", "makefile"]),
                       ("bazel", ["MODULE.bazel", "WORKSPACE", "BUILD.bazel"]), ("zig", ["build.zig"]), ("jvm", ["pom.xml", "build.gradle"])):
        if s & set(marks):
            return eco
    return "none"


def eco_marker(e, root):
    marks = {"rust": "Cargo.toml", "go": "go.mod", "cmake": "CMakeLists.txt", "meson": "meson.build", "node": "package.json"}
    return marks.get(e) in root if e in marks else bool(set(root) & {"pyproject.toml", "setup.py", "setup.cfg"})


def read(d, n):
    p = os.path.join(d, "f__" + n)
    return open(p, errors="replace").read() if os.path.exists(p) else ""


def convention(eco, d, root):
    """Is there a default test command, without CI? Returns (cmd or None)."""
    s = set(root)
    if eco == "rust":
        return "cargo test"
    if eco == "go":
        return "go test ./..."
    if eco == "cmake":
        c = read(d, "CMakeLists.txt")
        return "ctest" if re.search(r"enable_testing|add_test|include\s*\(\s*CTest|gtest_discover_tests|add_subdirectory\s*\(\s*tests?\b", c, re.I) else None
    if eco == "meson":
        return "meson test" if re.search(r"\btest\s*\(|subdir\s*\(\s*'tests?'", read(d, "meson.build")) else None
    if eco == "python":
        if s & {"tests", "test", "testing", "pytest.ini", "conftest.py", "tox.ini", "noxfile.py"} or "[tool.pytest" in read(d, "pyproject.toml") \
                or "[tool:pytest]" in read(d, "setup.cfg"):
            return "pytest"
        return None
    if eco == "node":
        try:
            t = (json.loads(read(d, "package.json") or "{}").get("scripts") or {}).get("test", "")
        except ValueError:
            t = ""
        return "npm test" if t and "no test specified" not in t else None
    if eco in ("autotools", "make"):
        m = read(d, "Makefile") or read(d, "GNUmakefile") or read(d, "makefile")
        am = read(d, "Makefile.am")
        if eco == "autotools":
            return "make check"
        mm = re.search(r"^(check|test|tests)\s*:", m, re.M)
        return f"make {mm.group(1)}" if mm else None
    return None


def runs_from_workflow(txt):
    try:
        y = yaml.safe_load(txt)
    except Exception:  # noqa: BLE001
        return [], [], True
    out, uses = [], []
    jobs = (y or {}).get("jobs") if isinstance(y, dict) else None
    for jn, j in (jobs or {}).items():
        if not isinstance(j, dict):
            continue
        ro = json.dumps(j.get("runs-on", ""))
        for st in j.get("steps") or []:
            if isinstance(st, dict):
                if isinstance(st.get("run"), str):
                    out.append((jn, ro, st["run"]))
                if isinstance(st.get("uses"), str):
                    uses.append((jn, st["uses"], json.dumps(st.get("with") or {})))
    return out, uses, False


def main(repos_dir, sample, pool):
    lang_of = {l.split()[1].lower(): l.split()[0] for l in open(sample) if l.strip()}
    pool_set = {l.strip().lower() for l in open(pool) if l.strip()}
    rows = []
    for mp in sorted(glob.glob(os.path.join(repos_dir, "*", "meta.json"))):
        d = os.path.dirname(mp)
        m = json.load(open(mp))
        if m.get("error"):
            continue
        root = m.get("root", [])
        eco = eco_of(root)
        conv = convention(eco, d, root)
        cands, bad_yaml, hidden = [], False, []
        for w in m.get("workflows", []):
            runs, uses, bad = runs_from_workflow(open(os.path.join(d, "wf__" + w), errors="replace").read())
            bad_yaml |= bad
            for jn, ro, r in runs:
                for line in r.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or INSTALL_RX.search(line):
                        continue
                    for fam, rx in TEST_RX:
                        if re.search(rx, line):
                            cands.append({"wf": w, "job": jn, "fam": fam, "line": line[:200], "linux": "ubuntu" in ro or "${{" in ro,
                                          "matrix": "${{" in line})
                            break
            for jn, u, wi in uses:
                for fam, rx in ACTION_RX:
                    if re.search(rx, u) and (fam != "cargo" or "test" in wi):
                        hidden.append(fam)
        for extra in (".gitlab-ci.yml", ".travis.yml"):
            t = read(d, extra)
            for line in t.splitlines():
                for fam, rx in TEST_RX:
                    if re.search(rx, line):
                        cands.append({"wf": extra, "job": "", "fam": fam, "line": line.strip()[:200], "linux": True, "matrix": "$" in line})
                        break
        mk = read(d, "Makefile") or read(d, "GNUmakefile") or read(d, "makefile")
        for c in list(cands) + [{"fam": "make", "line": l, "wf": "", "job": "", "linux": True, "matrix": False}
                                for l in re.findall(r"\bmake\s+[\w -]+", "\n".join(r for w in m.get("workflows", []) for r in [open(os.path.join(d, "wf__" + w), errors="replace").read()]))]:
            if c["fam"] == "make" or re.search(r"\bmake\b", c["line"]):
                for tgt in re.findall(r"\bmake\s+(?:-\S+\s+)*([\w-]+)", c["line"]):
                    body = re.search(rf"^{re.escape(tgt)}\s*:[^\n]*\n((?:\t[^\n]*\n?)*)", mk, re.M)
                    deps = re.search(rf"^{re.escape(tgt)}\s*:([^\n]*)", mk, re.M)
                    text = (body.group(1) if body else "") + " ".join(
                        (re.search(rf"^{re.escape(x)}\s*:[^\n]*\n((?:\t[^\n]*\n?)*)", mk, re.M) or [None, ""])[1] or ""
                        for x in (deps.group(1).split() if deps else []))
                    for fam, rx in TEST_RX[:8]:
                        if fam != "make" and re.search(rx, text):
                            cands.append({"wf": c["wf"], "job": c["job"], "fam": fam, "line": f"{c['line']} -> {fam} via Makefile",
                                          "linux": True, "matrix": False, "via": "make"})
                            break
        allwf = "\n".join(open(os.path.join(d, "wf__" + w), errors="replace").read() for w in m.get("workflows", []))
        miss = ("reusable-remote" if re.search(r"uses:\s*[\w.-]+/[\w.-]+/\.github/workflows/", allwf) else
                "docker-build" if re.search(r"docker/(bake|build-push)-action|docker (build|compose)", allwf) else
                "codeql-or-release-only" if allwf else "no-ci")
        fams = collections.Counter(c["fam"] for c in cands)
        native = FAMILY_OF.get(eco, set())
        alt = [e for e in ("rust", "go", "cmake", "meson", "python", "node") if e != eco and FAMILY_OF[e] & set(c["fam"] for c in cands)
               and eco_marker(e, root)]
        mixed = bool(alt)
        if not (native & set(c["fam"] for c in cands)) and alt:
            eco = alt[0]; native = FAMILY_OF[eco]; conv = convention(eco, d, root)
        best = None
        for c in cands:                      # prefer: native family, linux job, no matrix vars
            score = (c["fam"] in native) * 4 + c["linux"] * 2 + (not c["matrix"])
            if best is None or score > best[0]:
                best = (score, c)
        repo = m["repo"].lower()
        rows.append({"repo": m["repo"], "set": "pool" if repo in pool_set else "sample", "sample_lang": lang_of.get(repo, ""),
                     "gh_lang": m.get("lang"), "eco": eco, "has_gha": bool(m.get("workflows")),
                     "has_other_ci": bool(set(root) & {".gitlab-ci.yml", ".travis.yml", ".cirrus.yml", "appveyor.yml"}),
                     "ci_test": bool(cands) or bool(hidden), "ci_best": best[1] if best else None, "ci_fams": dict(fams),
                     "ci_native": any(c["fam"] in native for c in cands), "ci_wrapper_only": bool(cands) and all(c["fam"] in WRAPPERS for c in cands),
                     "hidden_action": hidden, "mixed": mixed, "miss": None if cands or hidden else miss,
                     "via_make": any(c.get("via") == "make" for c in cands), "convention": conv, "bad_yaml": bad_yaml})
    for r in rows:
        print(json.dumps(r))
    # summary per ecosystem
    by = collections.defaultdict(list)
    for r in rows:
        by[r["eco"]].append(r)
    hdr = f"{'eco':10} {'n':>3} {'gha':>5} {'ci_test':>7} {'native':>6} {'wrap':>5} {'conv':>5} {'ci|conv':>7}"
    print(hdr, file=sys.stderr)
    for eco, rs in sorted(by.items(), key=lambda x: -len(x[1])):
        n = len(rs)
        pct = lambda k: f"{100 * sum(bool(k(r)) for r in rs) / n:5.0f}"
        print(f"{eco:10} {n:3} {pct(lambda r: r['has_gha'])} {pct(lambda r: r['ci_test']):>7} {pct(lambda r: r['ci_native']):>6} "
              f"{pct(lambda r: r['ci_wrapper_only'])} {pct(lambda r: r['convention'])} {pct(lambda r: r['ci_test'] or r['convention']):>7}",
              file=sys.stderr)
    n = len(rows)
    print(f"ALL n={n} gha={sum(r['has_gha'] for r in rows)} ci_test={sum(r['ci_test'] for r in rows)} "
          f"conv={sum(bool(r['convention']) for r in rows)} either={sum(bool(r['ci_test'] or r['convention']) for r in rows)}", file=sys.stderr)


if __name__ == "__main__":
    main(*sys.argv[1:4])
