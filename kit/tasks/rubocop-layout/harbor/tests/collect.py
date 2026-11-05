"""tests/collect.py: evidence only. Rebuilds a clean rubocop tree around the candidate's lib/, runs every frozen
case through layout_probe.rb as an unprivileged uid, scores each unit, and writes evidence.json on every path.

Clean tree = pristine Gemfile, Gemfile.lock, rubocop.gemspec, config/ and exe/ (tests/data/pristine.tar.gz)
plus the regular files under /app/rubocop/lib (symlinks are not copied). Nothing from /app is imported here.

Unit score (cop units): 0.5 when the cop's offense ranges equal the expected ones, plus 0.5 more when the
autocorrected source is also identical. Dept units: 1 when the final source after all default-enabled Layout
cops autocorrect together is identical. Crashes, errors, timeouts and missing results score 0.
"""
import argparse
import gzip
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app/rubocop")
ap.add_argument("--cases", default="/tests/data/hidden.jsonl.gz")
ap.add_argument("--jobs", type=int, default=8)
args = ap.parse_args()

TESTS = os.path.dirname(os.path.abspath(__file__))
SHARD_SECONDS = 2400
MAX_RESTARTS = 300
LIB_LIMIT = 64 * 1024 * 1024

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0,
    "cop_units": 0, "cop_points": 0.0, "dept_units": 0, "dept_passed": 0,
    "buckets": {}, "per_cop": {}, "errors_sample": [], "wall_seconds": 0.0,
}
T0 = time.time()


def write():
    ev["wall_seconds"] = round(time.time() - T0, 1)
    with open(args.out, "w") as f:
        json.dump(ev, f)


def demote():
    os.setsid()
    os.setgroups([])
    os.setgid(args.uid)
    os.setuid(args.uid)
    resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def cand_env(home):
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "BUNDLE_GEMFILE": os.path.join(CLEAN, "Gemfile"), "BUNDLE_FROZEN": "true",
        "BUNDLE_APP_CONFIG": os.path.join(home, ".bundle"), "BUNDLE_IGNORE_CONFIG": "1",
        "BUNDLE_USER_HOME": os.path.join(home, ".bundle-user"), "RUBYOPT": "", "TMPDIR": home,
    }


def run_driver(lines, home, timeout):
    """One driver process over `lines`; returns {id: result}. Kills the whole process group afterwards."""
    p = subprocess.Popen(["ruby", "-rbundler/setup", PROBE], cwd=CLEAN, env=cand_env(home), preexec_fn=demote,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    res = {}
    try:
        out, _ = p.communicate("".join(lines).encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = p.communicate()
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    for l in out.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            res.setdefault(r["id"], r)
    return res


def run_shard(idx, cases):
    home = tempfile.mkdtemp(prefix=f"lp{idx}-", dir=WORK)
    os.chown(home, args.uid, args.uid)
    todo = list(cases)
    results = {}
    deadline = time.time() + SHARD_SECONDS
    restarts = 0
    while todo and time.time() < deadline and restarts <= MAX_RESTARTS:
        lines = [json.dumps({k: c[k] for k in ("id", "cops", "config", "source", "path", "ruby", "engine",
                                                "defaults")}) + "\n" for c in todo]
        got = run_driver(lines, home, max(5, deadline - time.time()))
        results.update(got)
        rest = [c for c in todo if c["id"] not in results]
        if len(rest) == len(todo):          # the first case killed the process: count it failed, go on
            results[todo[0]["id"]] = {"error": "driver died"}
            rest = todo[1:]
        elif rest:                           # died part-way: the first missing case is the culprit
            results[rest[0]["id"]] = {"error": "driver died"}
            rest = rest[1:]
        todo = rest
        restarts += 1
    return results


def score(c, r):
    if not r or r.get("error"):
        return 0.0
    if c["kind"] == "dept":
        return 1.0 if r.get("corrected") == c["expected"]["corrected"] else 0.0
    offs = (r.get("offenses") or {}).get(c["cops"][0], [])
    if offs != c["expected"]["offenses"]:
        return 0.0
    return 1.0 if r.get("corrected") == c["expected"]["corrected"] else 0.5


try:
    # 1. runtime
    if not shutil.which("ruby"):
        raise RuntimeError("ruby missing")
    cases = [json.loads(l) for l in gzip.open(args.cases)]
    ev["cases_total"] = len(cases)
    ev["cop_units"] = sum(1 for c in cases if c["kind"] != "dept")
    ev["dept_units"] = sum(1 for c in cases if c["kind"] == "dept")

    # 2. clean tree: pristine non-lib files + the candidate's lib/ (regular files only)
    WORK = tempfile.mkdtemp(prefix="grade-")
    os.chmod(WORK, 0o755)
    CLEAN = os.path.join(WORK, "rubocop")
    os.makedirs(CLEAN)
    with tarfile.open(os.path.join(TESTS, "data", "pristine.tar.gz")) as tf:
        tf.extractall(CLEAN)
    src_lib = os.path.join(args.app, "lib")
    total = 0
    if os.path.isdir(src_lib) and not os.path.islink(src_lib):
        for root, dirs, files in os.walk(src_lib, followlinks=False):
            rel = os.path.relpath(root, src_lib)
            dst = os.path.join(CLEAN, "lib", rel)
            os.makedirs(dst, exist_ok=True)
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
            for fn in files:
                sp = os.path.join(root, fn)
                if os.path.islink(sp) or not os.path.isfile(sp):
                    continue
                total += os.path.getsize(sp)
                if total > LIB_LIMIT:
                    raise OverflowError
                shutil.copyfile(sp, os.path.join(dst, fn))
    for root, dirs, files in os.walk(CLEAN):
        os.chmod(root, 0o755)
        for fn in files:
            os.chmod(os.path.join(root, fn), 0o644)
    PROBE = os.path.join(WORK, "layout_probe.rb")
    shutil.copyfile(os.path.join(TESTS, "layout_probe.rb"), PROBE)
    os.chmod(PROBE, 0o644)

    # 3. build gate: the tree loads and every Layout cop of config/default.yml is registered
    home = tempfile.mkdtemp(prefix="build-", dir=WORK)
    os.chown(home, args.uid, args.uid)
    chk = ("require 'rubocop'; require 'yaml'; "
           "names = YAML.safe_load(File.read('config/default.yml'), permitted_classes: [Regexp, Symbol], "
           "aliases: true).keys.grep(%r{\\ALayout/}); "
           "missing = names.reject { |n| RuboCop::Cop::Registry.global.find_by_cop_name(n) }; "
           "STDOUT.write(missing.empty? ? \"LOADED #{names.size}\" : \"MISSING #{missing.join(',')}\")")
    p = subprocess.run(["ruby", "-rbundler/setup", "-e", chk], cwd=CLEAN, env=cand_env(home), preexec_fn=demote,
                       capture_output=True, timeout=300)
    out = p.stdout.decode("utf-8", "replace")
    if p.returncode == 0 and out.startswith("LOADED 100"):
        ev["build_ok"] = True
    else:
        ev["gate_reason"] = ("build: rubocop does not load from /app/rubocop/lib or a Layout cop is missing: "
                             + (out or p.stderr.decode("utf-8", "replace"))[-400:])

    # 4. cases
    if ev["build_ok"]:
        shards = [[] for _ in range(args.jobs)]
        for i, c in enumerate(sorted(cases, key=lambda c: -len(c["source"]))):
            shards[i % args.jobs].append(c)
        with ThreadPoolExecutor(args.jobs) as ex:
            parts = list(ex.map(lambda a: run_shard(*a), enumerate(shards)))
        results = {}
        for part in parts:
            results.update(part)
        per_cop, buckets = {}, {}
        for c in cases:
            r = results.get(c["id"])
            s = score(c, r)
            if r and r.get("error") and len(ev["errors_sample"]) < 20:
                ev["errors_sample"].append(f"{c['id']}: {str(r['error'])[:160]}")
            b = buckets.setdefault(c["kind"], {"points": 0.0, "total": 0})
            b["points"] += s
            b["total"] += 1
            if c["kind"] == "dept":
                ev["dept_passed"] += int(s == 1.0)
            else:
                ev["cop_points"] += s
                pc = per_cop.setdefault(c["cops"][0], {"points": 0.0, "total": 0})
                pc["points"] += s
                pc["total"] += 1
            ev["cases_passed"] += int(s == 1.0)
        ev["buckets"] = buckets
        ev["per_cop"] = per_cop
except OverflowError:
    ev["build_ok"] = False
    ev["gate_reason"] = "build: /app/rubocop/lib is larger than 64 MB"
except Exception as e:  # our own failure: a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    try:
        subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], check=False)
    except Exception:
        pass
    write()
sys.exit(0)
