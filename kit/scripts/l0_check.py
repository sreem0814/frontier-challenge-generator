#!/usr/bin/env python3
"""l0_check.py: static checks on tasks/<task>/harbor/ against capture/instructions.md (written 2026-10-20).

Usage: ~/.local/bin/uv run --no-project --python 3.12 python -I kit/scripts/l0_check.py <task>

Mirrors the platform's structure stage as far as the spec describes it: required files, task.toml policy, the
timer and Dockerfile tail byte-for-byte, PROVENANCE and instruction length, solution size, nothing graded in
environment/, verifier hygiene, sandbox-limit warnings, deny-list phrases, leftover TODO/REPLACE markers.
BLOCK lines fail the run (exit 1); WARN lines need a human look. Report: tasks/<task>/build/l0-report.md.
"""
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = next(d / "capture" / "instructions.md" for d in Path(__file__).resolve().parents
            if (d / "capture" / "instructions.md").exists())
DENY = Path(__file__).with_name("leak-denylist.txt")
PRIVATE_DENY = Path.home() / ".config" / "cgpipe" / "denylist.txt"   # platform identifiers (private)
PRIVATE_ORG = Path.home() / ".config" / "cgpipe" / "org"             # the task-name prefix (private)
TIERS = {7200, 14400, 28800, 72000}
BAD_ENV = re.compile(r"^(LD_\w*|PATH|PYTHON\w*|BASH_ENV|ENV|SHELLOPTS|BASHOPTS|GCONV_PATH|PROMPT_COMMAND)$")
CODE_EXT = {".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".py", ".sh", ".go", ".zig", ".hs", ".ts", ".js", ".java",
            ".kt", ".ml", ".toml", ".cu", ".cuh", ".lua", ".rb"}


class Report:
    def __init__(self):
        self.lines, self.blocks, self.warns = [], 0, 0

    def block(self, group, msg):
        self.blocks += 1; self.lines.append(f"BLOCK [{group}] {msg}")

    def warn(self, group, msg):
        self.warns += 1; self.lines.append(f"WARN  [{group}] {msg}")

    def ok(self, group, msg):
        self.lines.append(f"ok    [{group}] {msg}")


def spec_blocks():
    src = SPEC.read_text()
    blocks = re.findall(r"```\n(.*?)```", src, re.S)
    timer = next(b for b in blocks if b.startswith("#!/usr/bin/env bash\n# Background task timer daemon"))
    tail = next(b for b in blocks if b.startswith("# --- task timer"))
    return timer, tail


def code_only(text):
    """Drop full-line and trailing # comments (shell, Python, Dockerfile) so rules match code, not prose."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#!") or not line.lstrip().startswith("#"):
            out.append(re.sub(r"\s+#\s.*$", "", line))
    return "\n".join(out)


def words(path):
    text = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.S)
    return len(re.findall(r"\S+", text)), text


def check_files(h, r):
    need = ["task.toml", "instruction.md", "PROVENANCE.md", "environment/Dockerfile", "environment/timer.sh",
            "tests/test.sh", "tests/compute_reward.py", "solution/solve.sh"]
    missing = [n for n in need if not (h / n).is_file()]
    for n in missing:
        r.block("files", f"missing {n}")
    if not missing:
        r.ok("files", "all required files present")
    for n in ("cheat", "environment/tests", "environment/solution"):
        if (h / n).exists():
            r.block("files", f"{n}/ must not ship")


def check_toml(h, r):
    try:
        t = tomllib.loads((h / "task.toml").read_text())
    except Exception as e:
        r.block("toml", f"task.toml does not parse: {e}"); return
    raw = (h / "task.toml").read_text()
    task, meta, agent = t.get("task", {}), t.get("metadata", {}), t.get("agent", {})
    ver, env = t.get("verifier", {}), t.get("environment", {})
    envvars = env.get("env", {})
    name = task.get("name", "")
    org = PRIVATE_ORG.read_text().strip() if PRIVATE_ORG.exists() else ""
    m = re.fullmatch(r"([a-z0-9][a-z0-9._-]*)/[a-z0-9][a-z0-9._-]*", name)
    if not m or m.group(1) == "org":
        r.block("toml", f"[task] name must be <org>/<slug> (got {name!r})")
    elif m.group(1) == "cg":
        pass                         # the repo's placeholder: make_zip.sh writes the private prefix into the zip
    elif org and m.group(1) != org:
        r.block("toml", f"[task] name prefix {m.group(1)!r} differs from ~/.config/cgpipe/org")
    elif not org:
        r.warn("toml", "~/.config/cgpipe/org not set: the name prefix is not checked")
    if not task.get("description"):
        r.block("toml", "[task] description missing")
    par = meta.get("paradigm")
    if par not in ("implementation", "optimization", "research"):
        r.block("toml", f"[metadata] paradigm invalid: {par!r}")
    gpus = env.get("gpus", 0)
    if meta.get("compute") != ("gpu" if gpus else "cpu"):
        r.block("toml", f"[metadata] compute {meta.get('compute')!r} does not match gpus = {gpus}")
    if not meta.get("languages") or not isinstance(meta.get("languages"), list):
        r.block("toml", "[metadata] languages must be a non-empty list")
    for k in ("category", "difficulty", "tags"):
        if k not in meta:
            r.warn("toml", f"[metadata] {k} missing")
    if par == "research" and meta.get("reward_cap") not in ("capped", "uncapped"):
        r.block("toml", "research tasks must set [metadata] reward_cap")
    if "oracle_reward_threshold" not in meta:
        r.warn("toml", "[metadata] oracle_reward_threshold not set (l3_run.sh then expects 1.0)")
    to = agent.get("timeout_sec")
    if to not in TIERS:
        r.block("toml", f"[agent] timeout_sec {to} is not a budget tier {sorted(TIERS)}")
    if str(envvars.get("TASK_BUDGET_SECS")) != str(int(to or 0)):
        r.block("toml", f"[environment.env] TASK_BUDGET_SECS {envvars.get('TASK_BUDGET_SECS')!r} != timeout {to}")
    if not isinstance(envvars.get("TASK_BUDGET_SECS"), str):
        r.block("toml", "TASK_BUDGET_SECS must be a string")
    if ver.get("timeout_sec", 600) > 86400:
        r.block("toml", "[verifier] timeout_sec > 86400")
    if ver.get("environment_mode") == "separate" or "environment" in ver:
        r.block("toml", "separate verifier environment: it cannot see the agent's /app")
    if env.get("allow_internet") is not False:
        r.block("toml", "[environment] allow_internet must be false")
    if env.get("cpus", 1) > 16: r.block("toml", "cpus > 16")
    if env.get("memory_mb", 0) > 131072: r.block("toml", "memory_mb > 131072")
    if env.get("memory_mb", 0) > 16384: r.warn("toml", "memory_mb > 16384: will not fit the local runners")
    if gpus > 1: r.block("toml", "gpus > 1")
    if gpus and env.get("gpu_types") != ["H100"]: r.block("toml", 'GPU tasks set gpu_types = ["H100"]')
    if "docker_image" in env: r.block("toml", "no docker_image: the platform builds the Dockerfile")
    if "network_mode" in env: r.block("toml", "no network-policy overrides")
    if "${" in raw: r.block("toml", "no ${VAR} interpolation")
    if "env" in ver: r.block("toml", "no variables injected into the verifier")
    for k in envvars:
        if BAD_ENV.match(k):
            r.block("toml", f"[environment.env] may not set {k}")
    if re.search(r"(api[_-]?key|token|secret)\s*=", raw, re.I):
        r.block("toml", "looks like a key or token in task.toml")
    r.ok("toml", f"parsed: {name} {par} timeout {to}")


def check_env(h, r, timer, tail):
    tp = h / "environment/timer.sh"
    if tp.is_file():
        if tp.read_text() != timer:
            r.block("timer", "environment/timer.sh differs from the spec's copy")
        else:
            r.ok("timer", "timer.sh byte-equal to the spec")
    dp = h / "environment/Dockerfile"
    if not dp.is_file():
        return
    d = dp.read_text()
    if not d.rstrip("\n").endswith(tail.rstrip("\n")):
        r.block("docker", "Dockerfile does not end with the spec's timer tail, verbatim")
    m = re.search(r"^FROM\s+(\S+)", d, re.M)
    base = m.group(1) if m else ""
    if not base or base.endswith(":latest") or (":" not in base and "@" not in base):
        r.block("docker", f"base image must be pinned to a tag or digest (got {base!r})")
    elif "REPLACE" in base:
        r.block("docker", "base image digest still a placeholder")
    elif "@sha256:" not in base:
        r.warn("docker", "base pinned by tag only; a digest is better")
    if not re.search(r"debian|ubuntu", base):
        r.warn("docker", "spec asks for a debian-family base")
    if "@anthropic-ai/claude-code" not in d:
        r.block("docker", "Claude Code CLI is not installed")
    users = re.findall(r"^\s*USER\s+(\S+)", d, re.M)
    if users and users[-1] not in ("root", "0"):
        r.block("docker", f"image must end as root (last USER {users[-1]})")
    d = code_only(d)
    if re.search(r"BASH_ENV|ENTRYPOINT.*timer|profile\.d.*timer|bashrc.*timer", d):
        r.block("docker", "timer must not auto-start from the image")
    if re.search(r"^\s*ENV\s+.*\b(LD_PRELOAD|LD_AUDIT|BASH_ENV|SHELLOPTS|BASHOPTS|GCONV_PATH|PROMPT_COMMAND)\b", d, re.M):
        r.block("docker", "loader or shell hook variable set in the image environment")
    if re.search(r"^\s*COPY\s+.*\b(tests|solution)/", d, re.M):
        r.block("docker", "Dockerfile copies tests/ or solution/ into the image")
    for f in sorted((h / "environment").rglob("*")):
        if f.is_file() and (f.name in ("compute_reward.py", "solve.sh") or "tests" in f.relative_to(h / "environment").parts):
            r.block("leak", f"graded file under environment/: {f.relative_to(h)}")
        elif f.is_file() and f.stat().st_size < 2_000_000:
            try:
                if re.search(r"compute_reward|solve\.sh", f.read_text(errors="strict")):
                    r.block("leak", f"environment file names the grader: {f.relative_to(h)}")
            except (UnicodeDecodeError, ValueError):
                pass


def check_text(h, r):
    ip = h / "instruction.md"
    if ip.is_file():
        n, text = words(ip)
        if n < 250: r.block("instruction", f"{n} words (hard floor 250)")
        elif not 700 <= n <= 3350: r.warn("instruction", f"{n} words (passing tasks run 700-3350)")
        else: r.ok("instruction", f"{n} words")
        if "/app/.timer" not in text: r.block("instruction", "does not point at /app/.timer")
        if not re.search(r"\bhours?\b", text): r.warn("instruction", "budget not stated in hours")
        if "—" in text: r.warn("style", "instruction.md has em dashes (CLAUDE.md)")
    pp = h / "PROVENANCE.md"
    if pp.is_file():
        n, text = words(pp)
        if n < 80: r.block("provenance", f"{n} words (minimum 80)")
        else: r.ok("provenance", f"{n} words")
        if not re.search(r"https?://|RFC|ISO|IEEE|commit|release", text):
            r.warn("provenance", "no URL, commit, release or standard named")
        if "—" in text: r.warn("style", "PROVENANCE.md has em dashes (CLAUDE.md)")


def check_solution(h, r):
    s = h / "solution"
    n = 0
    for f in s.rglob("*"):
        if f.is_file() and (f.suffix in CODE_EXT or f.name == "solve.sh"):
            n += sum(1 for line in f.read_text(errors="ignore").splitlines() if line.strip())
    if n < 150: r.block("solution", f"{n} non-blank code lines under solution/ (minimum 150)")
    else: r.ok("solution", f"{n} non-blank code lines")
    for f in s.rglob("*"):
        if f.suffix in (".zip", ".tar", ".gz", ".tgz", ".xz", ".zst", ".7z"):
            r.block("solution", f"archive in solution/: {f.relative_to(h)} (ship source)")
    sv = code_only((s / "solve.sh").read_text()) if (s / "solve.sh").is_file() else ""
    if re.search(r"/logs/verifier|/tests\b", sv):
        r.block("solution", "solve.sh touches /logs/verifier or /tests")


def check_verifier(h, r):
    t = h / "tests"
    for f in sorted(t.rglob("*")):
        if not f.is_file() or f.suffix not in (".sh", ".py"):
            continue
        rel = f.relative_to(h)
        if any(p in ("cases", "fixtures", "data", "expected") for p in f.relative_to(t).parts[:-1]):
            continue
        s = code_only(f.read_text(errors="ignore"))
        if re.search(r"pkill\s+(-\w+\s+)*-f\b|\bkillall\b|kill\s+(-\w+\s+)?-1\b", s):
            r.block("hygiene", f"{rel}: kills by name or kill -1 (would hit the harness)")
        if f.suffix == ".sh" and re.search(r"(echo|printf)\s+['\"]?[0-9.]+['\"]?\s*>+\s*\S*reward\.(txt|json)", s):
            r.block("hygiene", f"{rel}: reward literal written from shell")
        if f.suffix == ".sh" and re.search(r"python3?\s(?!.*-E)(?!.*-I).*\.py", s):
            r.warn("hygiene", f"{rel}: python run without -E -s / -I")
        if re.search(r"oracle|ORACLE_MODE|IS_ORACLE", s) and f.name != "compute_reward.py":
            r.warn("hygiene", f"{rel}: mentions oracle; no oracle-mode branches allowed")
        for pat, why in ((r"landlock", "Landlock is missing under gVisor"),
                         (r"KILL_PROCESS", "kill-process seccomp default is refused under gVisor"),
                         (r"\bvalgrind\b|callgrind", "valgrind crashes under gVisor"),
                         (r"chmod\s+0?[0-7]?[1357]11\b|chmod\s+0?111\b", "execute-only files fail under gVisor"),
                         (r"RLIMIT_MSGQUEUE|ulimit\s+-q|mq_unlink", "message-queue limits fail under gVisor"),
                         (r"perf_event|\bperf stat\b", "no perf counters under gVisor"),
                         (r"\bnproc\b|cpu_count\(", "visible core count is not the CPU limit")):
            if re.search(pat, s, re.I):
                r.warn("sandbox", f"{rel}: {why}")
    ts = (t / "test.sh").read_text() if (t / "test.sh").is_file() else ""
    if ts and "export PATH=" not in ts: r.block("hygiene", "test.sh does not reset PATH")
    if ts and "LD_PRELOAD" not in ts: r.block("hygiene", "test.sh does not unset loader variables")


def check_markers(h, r):
    # build/l0-upstream.txt: harbor-relative path prefixes of upstream code shipped unchanged (one per line); markers
    # there are upstream's own comments, so they warn instead of block (leftover markers in our own files still block)
    up_f = h.parent / "build" / "l0-upstream.txt"
    upstream = [l.strip() for l in up_f.read_text().splitlines() if l.strip() and not l.startswith("#")] if up_f.exists() else []
    text = DENY.read_text() + ("\n" + PRIVATE_DENY.read_text() if PRIVATE_DENY.exists() else "")
    pats = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    rx = [re.compile(p, re.I) for p in pats]
    for f in sorted(h.rglob("*")):
        if not f.is_file() or f.stat().st_size > 5_000_000:
            continue
        try:
            s = f.read_text(errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
        rel = f.relative_to(h)
        for p, x in zip(pats, rx):
            if x.search(s):
                r.block("denylist", f"{rel}: matches /{p}/")
        if re.search(r"\bTODO\b|REPLACE", re.sub(r"<!--.*?-->", "", s, flags=re.S)):
            if any(str(rel).startswith(p) for p in upstream):   # upstream's own comments, shipped unchanged
                r.warn("markers", f"{rel}: TODO or REPLACE in upstream code (listed in build/l0-upstream.txt)")
            else:
                r.block("markers", f"{rel}: TODO or REPLACE left")
    for f in h.rglob("*"):
        if f.is_symlink() and not str(f.resolve()).startswith(str(h.resolve())):
            r.block("files", f"symlink leaves harbor/: {f.relative_to(h)}")


def main():
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    task = sys.argv[1]
    h = ROOT / "tasks" / task / "harbor"
    if not h.is_dir():
        sys.exit(f"l0_check.py: {h} missing")
    r = Report()
    timer, tail = spec_blocks()
    check_files(h, r); check_toml(h, r); check_env(h, r, timer, tail); check_text(h, r)
    check_solution(h, r); check_verifier(h, r); check_markers(h, r)
    verdict = "PASS" if r.blocks == 0 else "FAIL"
    out = [f"# L0 {task}: {verdict} ({r.blocks} block, {r.warns} warn)", ""] + r.lines
    b = ROOT / "tasks" / task / "build"; b.mkdir(exist_ok=True)
    (b / "l0-report.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    sys.exit(0 if r.blocks == 0 else 1)


if __name__ == "__main__":
    main()
