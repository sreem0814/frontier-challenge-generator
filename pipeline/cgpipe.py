#!/usr/bin/env python3
"""cgpipe.py: the CG idea pipeline. Documentation: README.md.

  harvest + enrich + probe (no tokens) -> [scout] -> write -> L0 (no tokens) -> V1 -> V2 -> spike -> validated

  python3 -I pipeline/cgpipe.py run [--dry-run] [--target N] [--budget USD] [--max-batches N] [--no-spike]
  python3 -I pipeline/cgpipe.py watch [--once]               live dashboard: running jobs, funnel, bottleneck, ETA, issues
  python3 -I pipeline/cgpipe.py dashboard [--port 8765] [--interval 10]   web dashboard at http://127.0.0.1:8765/
  python3 -I pipeline/cgpipe.py status                       counts, yields, plan usage, cost, best seeds
  python3 -I pipeline/cgpipe.py warmup                       zero tokens: harvest, enrich and probe rows ahead of a run, then exit
  python3 -I pipeline/cgpipe.py stop                         finish in-flight calls, start nothing new, exit
  python3 -I pipeline/cgpipe.py selftest                     zero-token robustness test (dry-run scenarios, injected faults)
  python3 -I pipeline/cgpipe.py similar "<text>"             nearest public tasks and seeds to any idea text
  python3 -I pipeline/cgpipe.py try-prompts [ROWS] [V1S]     real write + V1 on a few rows in data-dry/ (cents; tests prompts)
  python3 -I pipeline/cgpipe.py add-idea "<text>"            queue your own idea (enters at V1)
  python3 -I pipeline/cgpipe.py requeue <seed-id> v1|v2|spike
  python3 -I pipeline/cgpipe.py import-sources <tsv>...      load source rows from research tables

Stdlib only, Python 3.10+. One runner at a time (lock file). All state lives in data/ and every write is atomic, so a
crash or Ctrl-C loses at most the calls in flight; they are scheduled again on the next start.
"""
import argparse
import collections
import concurrent.futures as cf
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import socket
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PIPE = os.path.join(ROOT, "pipeline")
sys.path.insert(0, PIPE)
import harvest  # noqa: E402  (zero-token harvesters and enricher)

DATA = os.path.join(ROOT, "data")
CACHE = os.path.expanduser("~/.cache/cgpipe")       # worker cwd and system-prompt files, outside the repo
CLAUDE = os.path.expanduser("~/.local/bin/claude")
IO_LOCK = threading.Lock()                          # cost.jsonl and pipeline.log are appended from worker threads
CHILDREN = set()                                    # live worker processes (own sessions: Ctrl-C reaches only us)
UTIL = {}                                           # latest plan usage from rate_limit_event: window -> (u, resetsAt)
SRC_COLS = ["key", "channel", "class", "type", "family", "name", "url", "version", "licence", "surface",
            "reference", "notes", "status", "offered", "used_by", "added", "priority", "facts"]
WEIGHTS = {"Real": 3, "Surf": 3, "Ref": 2, "Band": 3, "Hor": 2, "Multi": 2, "Seal": 2, "Nov": 2, "Lic": 1,
           "Fit": 1, "Build": 1}
GATES = {"Real": "K2", "Surf": "K3", "Ref": "K5", "Band": "K8", "Hor": "K10", "Multi": "K10", "Seal": "K11",
         "Nov": "K1", "Lic": "K6", "Fit": "K7"}
BAND_CAP = {"E0": 3, "E1": 4}
CLASS_CODE = {"implementation": "im", "optimization": "op", "research": "rs"}
KCODE = re.compile(r"K(1[0-3]|[1-9])")
MODEL_KILLS = [""] + [f"K{i}" for i in range(1, 13)]      # K13 is set by the runner only (calls failed three times)
METHODS = ["conform", "port", "diffref", "feature", "rebuild", "perfseries", "incident", "research", "mutate"]
FAMILIES = ["codec", "compression", "font-text", "protocol", "compiler-toolchain", "emulator-vm", "database-query",
            "numeric-scientific", "geo", "solver", "build-system", "data-format", "other"]
CLASSES = ["implementation", "optimization", "research"]
# Seed status flow: short -> l0-pass -> v1-pass -> v2-pass -> validated; any stage may set killed:Kn.
AUTH_RX = re.compile(r"invalid (api key|x-api-key|bearer)|authentication_error|oauth token (has )?(expired|revoked)|"
                     r"\b401\b|please run /login|not logged in|invalid_grant", re.I)
LIMIT_RX = re.compile(r"hit your .{0,40}limit|spend limit|usage limit|limiting requests|wrapping up|rate.?limit|"
                      r"\b429\b|overloaded|too many requests|quota exceeded", re.I)


def set_data(path):
    global DATA, SEEDS, RUNS, SOURCES, COST, LOG, STOPF, LOCK, CHANNELS, USAGE
    DATA = path
    SEEDS, RUNS = os.path.join(DATA, "seeds"), os.path.join(DATA, "runs")
    SOURCES, COST, LOG = (os.path.join(DATA, f) for f in ("sources.tsv", "cost.jsonl", "pipeline.log"))
    global SMOKE, HINTS
    SMOKE, HINTS = os.path.join(DATA, "smoke.json"), os.path.join(DATA, "hints.json")
    STOPF, LOCK, CHANNELS, USAGE = (os.path.join(DATA, f) for f in ("STOP", ".lock", "channels.json", "usage.json"))
    global STATE
    STATE = os.path.join(DATA, "state.json")


set_data(os.environ.get("CGPIPE_DATA") or DATA)     # CGPIPE_DATA: run against another data folder (testing)


# ---------------------------------------------------------------- small helpers
def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    line = f"[{now()}] " + " ".join(str(msg).split("\n"))
    with IO_LOCK:
        print(line, flush=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")


def atomic_write(path, text):
    tmp = f"{path}.tmp{os.getpid()}.{threading.get_ident()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_config():
    return load_json(os.path.join(PIPE, "config.json"))


def norm_url(u):
    u = re.sub(r"^https?://(www\.)?", "", u.strip().lower())
    return re.sub(r"(\.git)?/*$", "", u)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]


# ---------------------------------------------------------------- sources
def read_sources():
    if not os.path.exists(SOURCES):
        return []
    with open(SOURCES, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_sources(rows):
    tmp = SOURCES + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, SRC_COLS, delimiter="\t", extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: str(r.get(c, "") or "").replace("\t", " ").replace("\n", " ") for c in SRC_COLS})
    os.replace(tmp, SOURCES)


def cost_records():
    out = []
    if os.path.exists(COST):
        with IO_LOCK:
            lines = open(COST).read().splitlines()
        for l in lines:
            try:
                out.append(json.loads(l))
            except ValueError:
                pass
    return out


def log_cost(stage, key, model, secs, cost, turns=None, error=False, subtype=None):
    with IO_LOCK:
        with open(COST, "a") as f:
            f.write(json.dumps({"ts": now(), "stage": stage, "key": key, "model": model, "secs": round(secs),
                                "cost": cost, "turns": turns, "error": error, "subtype": subtype}) + "\n")


def row_facts(r):
    try:
        return json.loads(r.get("facts") or "{}")
    except ValueError:
        return {}


def add_sources(new, channel):
    """Append new rows, deduplicated by URL and version (an unversioned URL counts as the same source)."""
    rows = read_sources()
    keys = {r["key"] for r in rows}
    versions = collections.defaultdict(set)
    for r in rows:
        versions[norm_url(r["url"])].add(slug(r.get("version")))
    added = 0
    for n in new:
        u, v = norm_url(n.get("url")), slug(n.get("version"))
        key = u + "|" + (v or slug(n.get("name")))
        if not n.get("url") or key in keys or (u in versions and (not v or "" in versions[u] or v in versions[u])):
            continue
        versions[u].add(v)
        lic, fit = n.get("licence", "").lower(), n.get("cpu_offline_ok", "").strip().lower()
        blocked = (re.search(r"not ok|non-?commercial|\bby-nc|\bnc\b|by-nd|no-?deriv|may not redistribute|"
                             r"academic research only|proprietary", lic) or fit.startswith("no"))
        row = {c: n.get(c, "") for c in SRC_COLS}
        row.update(key=key, channel=channel, status="blocked" if blocked else "unused", offered="0", used_by="",
                   added=now(), priority="", facts="")
        rows.append(row)
        keys.add(key)
        added += 1
    write_sources(rows)
    return added


def cmd_import(paths):
    for p in paths:
        with open(p, newline="") as f:
            new = []
            for r in csv.DictReader(f, delimiter="\t"):
                version = r.get("version_or_commit") or " -> ".join(
                    x for x in (r.get("baseline"), r.get("reference")) if x and x != "n/a (input set)")
                new.append({"class": r.get("class") or "implementation", "type": r.get("type", ""),
                            "name": r.get("name", ""), "url": r.get("url", ""), "version": version,
                            "licence": r.get("licence", ""), "surface": r.get("surface") or r.get("metric_or_speedup", ""),
                            "reference": r.get("reference_impl") or r.get("reference", ""), "notes": r.get("notes", ""),
                            "cpu_offline_ok": r.get("cpu_offline_ok", "")})
        print(f"{p}: {add_sources(new, 'seedmap:' + os.path.basename(p))} new rows")


# ---------------------------------------------------------------- seeds
def seed_path(sid):
    return os.path.join(SEEDS, sid + ".json")


def all_seeds():
    out = []
    for fn in sorted(os.listdir(SEEDS)) if os.path.isdir(SEEDS) else []:
        if fn.endswith(".json"):
            s = load_json(os.path.join(SEEDS, fn))
            if s:
                out.append(s)
    return out


def save_seed(s):
    atomic_write(seed_path(s["id"]), json.dumps(s, indent=1, sort_keys=True))


def hist(s, stage, result, note=""):
    s.setdefault("history", []).append([now(), stage, result, str(note)[:300]])


def next_id(cls, seeds):
    cc = CLASS_CODE.get(cls, "im")
    nums = [int(s["id"].split("-")[2]) for s in seeds if s["id"].startswith(f"S-{cc}-")]
    return f"S-{cc}-{(max(nums) if nums else 0) + 1:03d}"


def kill(s, code, stage, reason):
    s["status"], s["kill"] = f"killed:{code}", code
    hist(s, stage, f"killed:{code}", reason)


def card_text(s):
    c = s.get("card", {})
    return " ".join(str(c.get(k, "")) for k in ("title", "task", "grading", "reference", "source"))


# ---------------------------------------------------------------- similarity (TF-IDF over the public corpus)
STOP = set("the a an and or of to in for on with from by is are be as at this that it its into your you must should "
           "will file files task agent use using output input data run write create each all any not no if then than "
           "also such per via has have".split())


def toks(s):
    return [w for w in re.findall(r"[a-z][a-z0-9]{2,}", (s or "").lower()) if w not in STOP]


class Corpus:
    def __init__(self):
        self.docs = []
        cat = os.path.join(DATA, "catalog.csv")
        if os.path.exists(cat):
            for r in csv.DictReader(open(cat)):
                if not r.get("dup_kind"):
                    t = toks(r["name"].replace("-", " ")) * 3 + toks(r.get("tags", "").replace("|", " ")) * 2 + \
                        toks(r.get("description", ""))
                    self.docs.append((f"{r['name']} [{r.get('location', '')}]", collections.Counter(t)))
        extra = os.path.join(DATA, "corpus-extra.tsv")
        if os.path.exists(extra):
            for r in csv.DictReader(open(extra), delimiter="\t"):
                t = toks(r.get("name", "").replace("-", " ")) * 3 + toks(r.get("description", ""))
                self.docs.append((f"{r.get('name')} [{r.get('source')}]", collections.Counter(t)))
        df = collections.Counter()
        for _, c in self.docs:
            df.update(c.keys())
        n = max(1, len(self.docs))
        self.idf = {w: math.log((1 + n) / (1 + k)) + 1 for w, k in df.items()}
        self.vecs = [self.vec(c) for _, c in self.docs]

    def vec(self, counter):
        dflt = math.log(1 + len(self.idf)) + 1
        v = {w: (1 + math.log(c)) * self.idf.get(w, dflt) for w, c in counter.items()}
        nrm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / nrm for w, x in v.items()}

    @staticmethod
    def cos(a, b):
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(w, 0.0) for w, x in a.items())

    def top(self, text, k=3, extra=()):
        q = self.vec(collections.Counter(toks(text)))
        sc = [(self.cos(q, v), name) for (name, _), v in zip(self.docs, self.vecs)]
        sc += [(self.cos(q, self.vec(collections.Counter(toks(t)))), name) for name, t in extra]
        return sorted(sc, reverse=True)[:k]


# ---------------------------------------------------------------- scoring (README.md section 4)
def score(scores, grade="E0"):
    """scores: {code: int 1-5}. Returns (total 20-100, first gate kill code or None, capped scores)."""
    sc = {k: max(1, min(5, int(scores.get(k, 1) or 1))) for k in WEIGHTS}
    sc["Band"] = min(sc["Band"], BAND_CAP.get(grade, 3))
    total = round(100 * sum(WEIGHTS[k] * v for k, v in sc.items()) / (5 * sum(WEIGHTS.values())))
    gate = next((GATES[k] for k in GATES if sc[k] <= 2), None)
    if gate is None and sc["Build"] <= 1:
        gate = "K12"
    return total, gate, sc


# ---------------------------------------------------------------- calling Claude
class UsageLimit(Exception):
    def __init__(self, msg, until=None):
        super().__init__(msg)
        self.until = until      # epoch seconds when the window resets, if known


def stage_prompt_file(stage):
    """COMMON + the stage's section as a system-prompt file: identical across calls, so it is served from cache."""
    text = open(os.path.join(PIPE, "prompts.txt")).read()
    parts = re.split(r"^=== ([A-Z0-9_]+) ===\s*$", text, flags=re.M)
    sec = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}
    body = sec["COMMON"] + "\n\n" + sec[stage.upper()] + "\n"
    d = os.path.join(CACHE, "prompts")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{stage}-{hashlib.sha256(body.encode()).hexdigest()[:10]}.txt")
    if not os.path.exists(path):
        atomic_write(path, body)
    return path


def claude_args(stage, schema, cfg, prompt_file):
    return ["-p", "--model", cfg["models"][stage], "--effort", cfg["effort"][stage],
            "--output-format", "stream-json", "--verbose", "--json-schema", json.dumps(schema),
            "--no-session-persistence", "--permission-prompts", "none", "--safe-mode", "--strict-mcp-config",
            "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--setting-sources", "",
            "--append-system-prompt-file", prompt_file, "--max-turns", str(cfg["max_turns"][stage]),
            "--max-budget-usd", str(cfg["call_budget_usd"][stage])]


def pool_env():
    """The pipeline role's pool token (pipeline/tokens.py writes it to ~/.config/cgpipe/env) for the runner's own
    claude calls, so they bill that account instead of VM 1's login; without a pool, the login is used as before."""
    if not os.path.exists(os.path.expanduser("~/.config/cgpipe/tokens.json")):
        return None
    m = re.search(r"^CLAUDE_CODE_OAUTH_TOKEN=(\S+)", open(os.path.expanduser("~/.config/cgpipe/env")).read(), re.M) \
        if os.path.exists(os.path.expanduser("~/.config/cgpipe/env")) else None
    return dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=m.group(1)) if m else None


def run_child(cmd, stdin_text, timeout, cwd=None, on_timeout=None, env=None):
    """Run a worker in its own session (Ctrl-C reaches only the runner). Returns (stdout, stderr, rc)."""
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         cwd=cwd, start_new_session=True, env=env)
    CHILDREN.add(p)
    try:
        out, err = p.communicate(stdin_text, timeout=timeout)
        return out, err, p.returncode
    except subprocess.TimeoutExpired:
        if on_timeout:
            on_timeout()
        kill_child(p)
        p.communicate()
        raise RuntimeError(f"timeout after {timeout}s")
    finally:
        CHILDREN.discard(p)


def kill_child(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def call_claude(stage, key, payload, cfg, tools):
    cmd = [CLAUDE] + claude_args(stage, SCHEMA[stage], cfg, stage_prompt_file(stage))
    cmd += ["--tools", tools] + (["--allowed-tools", tools.replace(",", " ")] if tools else [])
    workdir = os.path.join(CACHE, "work")
    os.makedirs(workdir, exist_ok=True)
    t0 = time.time()
    try:
        out, err, rc = run_child(cmd, "INPUT:\n" + json.dumps(payload, indent=1), cfg["timeouts_sec"][stage], cwd=workdir,
                                 env=pool_env())
    except RuntimeError:          # timed out: the spend is unknown, so count the call's cap against the budget
        log_cost(stage, key, cfg["models"][stage], time.time() - t0, cfg["call_budget_usd"][stage], error=True,
                 subtype="timeout")
        raise
    return parse_stream(stage, key, cfg["models"][stage], out, err, rc, t0)


def parse_stream(stage, key, model, stdout, stderr, rc, t0):
    """Read a stream-json run: keep plan usage from rate_limit_event, return the result's structured output."""
    result, events = None, []
    for line in (stdout or "").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "rate_limit_event":
            info = e.get("rate_limit_info") or {}
            with IO_LOCK:
                for win, w in (info.get("unifiedWindows") or {}).items():
                    UTIL[win] = (float(w.get("utilization") or 0), int(w.get("resetsAt") or 0))
                if info.get("status") == "rejected":
                    UTIL["rejected"] = (1.0, int(info.get("resetsAt") or 0))
            events.append(e)
        elif e.get("type") == "result":
            result = e
            events.append(e)
    log_cost(stage, key, model, time.time() - t0, (result or {}).get("total_cost_usd", 0) or 0,
             (result or {}).get("num_turns"), bool(result is None or result.get("is_error") or rc != 0),
             (result or {}).get("subtype"))
    os.makedirs(os.path.join(RUNS, stage), exist_ok=True)
    atomic_write(os.path.join(RUNS, stage, f"{slug(key)}-{int(t0)}.jsonl"),
                 "\n".join(json.dumps(e) for e in events) + "\n" + (stderr or "")[-4000:])
    if result is None or result.get("is_error") or rc != 0:
        msg = str((result or {}).get("result") or (stderr or "")[-400:] or f"exit {rc}")
        with IO_LOCK:
            rejected = UTIL.pop("rejected", None)
        if rejected or LIMIT_RX.search(msg) or LIMIT_RX.search((stderr or "")[-2000:]):
            until = (rejected or (0, 0))[1] or None
            raise UsageLimit(msg[:300], until)
        raise RuntimeError(f"{(result or {}).get('subtype') or 'error'}: {msg[:300]}")
    so = result.get("structured_output")
    if not isinstance(so, dict):
        raise RuntimeError("no structured_output")
    return so


def call_spike(s, payload, cfg, boost=1):
    """A spike runs Claude inside a throwaway container with network, build tools and its own scratch folder."""
    sc = cfg["spike"]
    wd = os.path.join(DATA, "spikes", s["id"])
    os.makedirs(wd, exist_ok=True)
    os.chmod(wd, 0o777)
    envf = os.path.expanduser(sc["env_file"])
    if not os.path.exists(envf):
        raise RuntimeError(f"missing {envf} (the spike token): run `bash pipeline/setup-token.sh`")
    shutil.copy(stage_prompt_file("spike"), os.path.join(wd, ".cgpipe-system.txt"))
    name = f"cgspike-{s['id'].lower()}"
    probe = s.get("smoke") or {}
    vol = probe.get("work_volume")
    mounted = bool(vol) and subprocess.run(["docker", "volume", "inspect", vol], capture_output=True,
                                           timeout=60).returncode == 0
    pinned = probe.get("ref") not in (None, "", "default")
    payload["probe_tree"] = (f"/p (src/ is the built source at {'ref ' + probe['ref'] if pinned else 'the default branch'})"
                             if mounted else "none: obtain the source yourself")
    if mounted and pinned and probe.get("verdict") == "green":   # build and suite done at the pinned version: smaller spike
        cfg = json.loads(json.dumps(cfg))
        cfg["call_budget_usd"]["spike"] = round(cfg["spike_green"]["call_budget_usd"] * boost, 2)
        cfg["timeouts_sec"]["spike"] = int(cfg["spike_green"]["timeout_sec"] * boost)
    cmd = ["docker", "run", "--rm", "-i", "--name", name, "--cpus", str(sc["cpus"]), "--memory", sc["memory"],
           "--env-file", envf, "-v", f"{wd}:/work", "-w", "/work"] + (["-v", f"{vol}:/p"] if mounted else [])
    for v in harvest.CACHE_VOLUMES if mounted else []:     # the tree's cargo, Go, pip and npm caches
        cmd += ["-v", v]
    cmd += [sc["image"], "claude"]
    cmd += claude_args("spike", SCHEMA["spike"], cfg, "/work/.cgpipe-system.txt")
    cmd += ["--dangerously-skip-permissions"]
    t0 = time.time()
    try:
        out, err, rc = run_child(cmd, "INPUT:\n" + json.dumps(payload, indent=1), cfg["timeouts_sec"]["spike"],
                                 on_timeout=lambda: subprocess.run(["docker", "kill", name], capture_output=True))
    except RuntimeError:          # timed out: count the cap (see call_claude)
        log_cost("spike", s["id"], cfg["models"]["spike"], time.time() - t0, cfg["call_budget_usd"]["spike"],
                 error=True, subtype="timeout")
        raise
    finally:   # files the container wrote as root go back to the user
        try:
            subprocess.run(["docker", "run", "--rm", "-v", f"{wd}:/work", sc["image"], "chown", "-R",
                            f"{os.getuid()}:{os.getgid()}", "/work"], capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            pass
    return parse_stream("spike", s["id"], cfg["models"]["spike"], out, err, rc, t0)


# ---------------------------------------------------------------- schemas
STR, INT, BOOL, NUM = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "number"}


def obj(props, req=None):
    return {"type": "object", "properties": props, "required": req or list(props)}


def arr(item, mx=None):
    a = {"type": "array", "items": item}
    if mx:
        a["maxItems"] = mx
    return a


SCORES = obj({k: obj({"v": INT, "why": STR}) for k in WEIGHTS})
SCHEMA = {
    "scout": obj({"rows": arr(obj({"class": {"enum": CLASSES}, "type": STR, "name": STR, "url": STR, "version": STR, "licence": STR,
                                   "surface": STR, "reference": STR, "notes": STR}), 15),
                  "exhausted": BOOL}),
    "write": obj({"cards": arr(obj({"row": STR, "class": {"enum": CLASSES}, "family": {"enum": FAMILIES},
                                    "method": {"enum": METHODS}, "title": STR,
                                    "source": STR, "task": STR, "grading": STR, "reference": STR, "band": STR,
                                    "cheat": STR}), 12)}),
    "v1": obj({"facts": arr(obj({"claim": STR, "url": STR, "status": {"enum": ["confirmed", "not_found",
                                                                               "contradicted"]}}), 20),
               "full_card": obj({k: STR for k in ("provenance", "ships", "deliverable", "grading_surface", "reference",
                                                  "gates_anticheat", "band", "lookup", "similarity", "local_fit",
                                                  "build_cost")}),
               "scores": SCORES, "evidence_grade": {"enum": ["E0", "E1"]}, "evidence_url": STR,
               "lookup_verdict": {"enum": ["none", "partial", "direct"]},
               "frontier_hours": NUM, "tier_hours": {"enum": [2, 4, 8, 20]},
               "spike_plan": obj({"steps": arr(STR, 12), "pass_if": STR, "kill_if": STR, "est_minutes": INT}),
               "kill_code": {"enum": MODEL_KILLS}, "kill_reason": STR, "summary": STR}),
    "v2": obj({"seeds": arr(obj({"id": STR, "scores": obj({k: INT for k in WEIGHTS}),
                                 "evidence_grade": {"enum": ["E0", "E1"]}, "kill_code": {"enum": MODEL_KILLS},
                                 "note": STR})),
               "ranking": arr(STR), "batch_note": STR}),
    "spike": obj({"reference_built": BOOL, "oracle_available": BOOL, "cases_sampled": INT,
                  "reference_cases_passed": INT, "deterministic": BOOL, "headroom_ok": BOOL, "headroom_note": STR,
                  "start_scores_zero": BOOL, "offline_ok": BOOL, "reference_lines": INT, "outputs_match": BOOL,
                  "build_minutes": NUM, "verifier_minutes_estimate": NUM, "image_gb_estimate": NUM,
                  "gvisor_concerns": arr(STR), "blockers": arr(STR), "commands_log": STR,
                  "quick_attempt": obj({"tried": BOOL, "minutes": NUM, "share": NUM, "note": STR}),
                  "verdict": {"enum": ["pass", "fail", "inconclusive"]}, "kill_code": {"enum": MODEL_KILLS},
                  "notes": STR}),
}


# ---------------------------------------------------------------- payloads and batch picking
def compact_card(s):
    c = dict(s["card"])
    c.update(id=s["id"], class_=s["class"], family=s.get("family"), method=s.get("method"),
             l0_neighbours=s.get("l0", {}).get("neighbours", []), source_facts=s.get("source_facts", {}),
             source_notes=s.get("source_notes", ""),
             smoke_build={k: v for k, v in (s.get("smoke") or {}).items()
                          if k not in ("log", "work_volume", "cmd_fetch", "flaky_names", "stable_failure_names")})
    return c


def v2_view(s):
    """What the judge sees: the card and V1's evidence, never V1's scores or verdict (a shown score anchors the judge)."""
    v1 = s.get("v1") or {}
    return dict(compact_card(s), v1_facts=v1.get("facts", []), v1_full_card=v1.get("full_card", {}),
                lookup_verdict=v1.get("lookup_verdict"), spike_plan=v1.get("spike_plan"),
                frontier_hours=v1.get("frontier_hours"), tier_hours=v1.get("tier_hours"),
                evidence_url=v1.get("evidence_url"), dead_links=(s.get("v1_links") or {}).get("dead", []))


def class_want(cfg):
    return {"implementation": cfg["quota"]["implementation"] + 2, "optimization": cfg["quota"]["optimization"] + 1,
            "research": cfg["quota"]["research"] + 1}


def pick_rows_for_batch(rows, cfg, seeds=()):
    """Choose 2x batch_size unused rows (the writer skips weak ones): highest priority first, class quotas, at most a
    third per channel."""
    total = int(cfg["batch_size"] * 2)
    want = class_want(cfg)
    pool = [r for r in rows if r["status"] == "unused"]
    random.Random(len(rows)).shuffle(pool)
    bonus = cfg.get("class_priority_bonus", {})     # classes trials showed can hold up rank first when filling a batch
    pool.sort(key=lambda r: (-(float(r.get("priority") or 30) + bonus.get(r["class"] or "implementation", 0)), int(r["offered"] or 0)))
    pick, per_ch = [], collections.Counter()
    cap = max(2, total // 3)
    for cls, n in want.items():
        for r in pool:
            if n <= 0:
                break
            if (r["class"] or "implementation") == cls and per_ch[r["channel"]] < cap and r not in pick:
                pick.append(r); per_ch[r["channel"]] += 1; n -= 1
    for r in pool:
        if len(pick) >= total:
            break
        if r not in pick and per_ch[r["channel"]] < cap:
            pick.append(r); per_ch[r["channel"]] += 1
    for r in pool:              # few channels hold unused rows: fill past the per-channel cap
        if len(pick) >= total:
            break
        if r not in pick:
            pick.append(r)
    return pick[:total]


def row_for_writer(r, rid):
    out = {"row": rid}
    out.update({k: r.get(k, "") for k in ("channel", "class", "type", "name", "url", "version", "licence",
                                          "surface", "reference", "notes")})
    out["facts"] = row_facts(r)
    return out


QUICK_SHARE_MAX = 0.25    # config.json spike_quick_share_max overrides


def spike_kill(res, method, cls="implementation", quick_max=QUICK_SHARE_MAX):
    """None when the spike validates the idea, else the kill code that names the first failed condition.
    feature: no reference exists yet, so the base must build, its suite be deterministic, and headroom means
    "not implemented upstream"; its grading surface is designed when the bundle is built.
    optimization and research: the measured speedup or metric gap is the evidence, not a case pass rate."""
    feature, cases = method == "feature", cls == "implementation" and method != "feature"
    n = res.get("cases_sampled", 0) or 0
    lines = res.get("reference_lines", 0) or 0
    opt = cls == "optimization"
    checks = [(res.get("reference_built"), "K5"), (feature or res.get("oracle_available"), "K3"),
              (res.get("deterministic"), "K4"), (res.get("headroom_ok"), "K8"),
              (feature or res.get("start_scores_zero", True), "K3"), (res.get("offline_ok", True), "K7"),
              (lines >= (600 if feature else 150), "K10"), (not opt or res.get("outputs_match", False), "K5"),
              (not cases or n > 0, "K3"), (not cases or (res.get("reference_cases_passed", 0) or 0) >= 0.95 * n, "K5")]
    qa = res.get("quick_attempt") or {}
    checks.append((not qa.get("tried") or (qa.get("share") or 0) < quick_max, "K8"))   # too easy: a 12-minute attempt got far
    failed = next((code for ok, code in checks if not ok), None)
    if res.get("verdict") == "pass" and failed is None:
        return None
    return failed or (res.get("kill_code") if KCODE.fullmatch(res.get("kill_code") or "") else "K5")


def probe_target(url, version):
    """(git URL, ref) to probe: the GitHub repo at a single version tag (a version pair or prose means the default)."""
    g = harvest.gh_repo_of(url or "")
    if not g:
        return "", ""
    v = (version or "").strip()
    ref = v if re.fullmatch(r"[A-Za-z0-9._/+-]{1,60}", v) and "->" not in v else ""
    return f"https://github.com/{g[0]}/{g[1]}", ref


def smoke_target(s):
    return probe_target(s.get("source_url") or s.get("card", {}).get("source", ""), s.get("source_version"))


def probe_key(url, ref):
    return f"{norm_url(url)}|{ref}"


PROBE_BONUS = {"green": 25, "amber": 5, "red": -25}


def enriched(r):
    """The enricher has answered for this row (facts, not found, or failed three times)."""
    f = row_facts(r)
    return "stars" in f or bool(f.get("not_found")) or int(f.get("enrich_failed") or 0) >= 3


def row_priority(r):
    """Priority from the enrich facts plus the probe verdict; recomputed, never accumulated."""
    f = row_facts(r)
    base = harvest.priority(f, r["class"]) if ("stars" in f or f.get("not_found")) else 30.0
    return max(0.0, min(100.0, base + PROBE_BONUS.get((f.get("probe") or {}).get("verdict"), 0)))


def probe_summary(res):
    """The few probe facts a source row carries (the full result lives in data/smoke.json)."""
    return {k: res.get(k) for k in ("verdict", "eco", "build_ok", "tests_total", "tests_fail", "deterministic",
                                    "skipped") if k in res}


# ---------------------------------------------------------------- the runner
class Pipeline:
    def __init__(self, args):
        self.args, self.cfg = args, load_config()
        if args.target is not None:
            self.cfg["target_validated"] = args.target
        if not self.cfg["target_validated"]:
            self.cfg["target_validated"] = float("inf")     # 0 = as many as the budget allows
        if args.budget:
            self.cfg["budget_usd"] = args.budget
        self.pool = cf.ThreadPoolExecutor(max_workers=self.cfg["max_parallel_calls"] + self.cfg["pools"]["smoke"] + 3)
        self.inflight = {}                      # future -> (stage, key)
        self.paused_until, self.pause_reason = 0.0, ""
        self.backoff = 300
        self.stop = False
        self.signals = 0
        self.corpus = Corpus()
        self.batches_written = 0
        self.fails = collections.Counter()      # key -> consecutive failures
        self.retry_at = {}                      # key -> earliest retry time
        self.write_disabled = False
        self.last_activity = time.time()
        self.started = {}                       # key -> start time of in-flight work (for the dashboard)
        self.run_started = time.time()
        self.boost = {}                         # (stage, key) -> cap multiplier after a cap hit
        self.probing = {}                       # key of a probe in flight -> its repo|ref
        self.errors = []                        # (time, key) of recent failures: several at once mean an outage
        self.outages = 0                        # outage pauses since the last success
        self.spikes_off = ""                    # why spikes stopped (a rejected spike token), if they did
        self.budget_refused = 0.0               # last time a call didn't fit the budget
        self.offered = {}                       # write key -> {short row id: source key} for the call in flight
        self.spent_now = 0.0
        state = load_json(CHANNELS, {})
        for c in self.cfg["channels"]:
            c.update(state.get(c["id"], {}))

    # ---- bookkeeping
    def save_channels(self):
        keep = ("dry", "exhausted", "scouted", "harvested", "harvest_rows", "harvest_failed")
        atomic_write(CHANNELS, json.dumps({c["id"]: {k: c[k] for k in keep if k in c} for c in self.cfg["channels"]},
                                          indent=1))

    def blocked(self, key):
        return self.fails[key] >= 3 or time.time() < self.retry_at.get(key, 0)

    def settle(self, key):
        """A terminal outcome ends the retries for this key (otherwise it stays blocked)."""
        self.fails.pop(key, None); self.retry_at.pop(key, None)

    def spent(self):
        return sum(r.get("cost", 0) or 0 for r in cost_records())

    def affordable(self, stage, key):
        """Spent so far, plus the caps of every call in flight, plus this call's cap, must fit the budget."""
        caps = self.cfg["call_budget_usd"]
        reserved = sum(caps.get(st, 0) * self.boost.get((st, k), 1) for st, k in self.inflight.values())
        return self.spent_now + reserved + caps[stage] * self.boost.get((stage, key), 1) <= self.cfg["budget_usd"]

    def running(self, stage):
        return sum(1 for st, _ in self.inflight.values() if st == stage)

    def busy_keys(self):
        return {k for _, k in self.inflight.values()} | {k for k in self.retry_at if self.blocked(k)}

    def llm_running(self):
        return sum(1 for st, _ in self.inflight.values() if st in self.cfg["call_budget_usd"])

    def probes_running(self):
        return self.running("smoke") + self.running("rowprobe")

    def submit(self, stage, key, fn, *a):
        if stage in self.cfg["call_budget_usd"] and getattr(self.args, "warmup", False):
            return False               # warm-up runs only the zero-token stages
        if stage in self.cfg["call_budget_usd"] and not self.affordable(stage, key):
            self.budget_refused = time.time()     # the run ends as "budget reached" if nothing else can move
            return False
        self.inflight[self.pool.submit(fn, *a)] = (stage, key)
        self.started[key] = time.time()
        self.last_activity = time.time()
        log(f"start {stage} {key}")
        return True

    def cfg_for(self, stage, key):
        """A call that hit its turn, budget or time cap is retried once with 1.5x caps instead of identically."""
        b = self.boost.get((stage, key))
        if not b:
            return self.cfg
        c = json.loads(json.dumps(self.cfg))
        c["max_turns"][stage] = int(c["max_turns"][stage] * b)
        c["call_budget_usd"][stage] = round(c["call_budget_usd"][stage] * b, 2)
        c["timeouts_sec"][stage] = int(c["timeouts_sec"][stage] * b)
        return c

    def worker(self, stage, key, payload, tools=""):
        res = fake(stage, key, payload) if self.args.dry_run else \
            call_claude(stage, key, payload, self.cfg_for(stage, key), tools)
        if stage == "v1":   # zero-token check of every cited URL, in this worker thread
            res["_links"] = (check_urls([f.get("url") for f in res.get("facts", [])] + [res.get("evidence_url")])
                             if not self.args.dry_run else {"checked": 0, "dead": [], "ratio": 0.0})
        return res

    def harvest_job(self, ch):
        return fake("harvest", ch["id"], ch) if self.args.dry_run else harvest.harvest_channel(ch)

    def enrich_job(self, keys, tree_for):
        facts = fake("enrich", "enrich", keys)["facts"] if self.args.dry_run else \
            harvest.enrich([tuple(k.split("/", 1)) for k in keys], tree_for)
        return {"facts": facts, "keys": keys}

    def probe_job(self, stage, key, url, ref, keep):
        if self.args.dry_run:
            return fake(stage, key, {"keep": keep})
        name = "cgprobe-" + hashlib.sha1(key.encode()).hexdigest()[:10]
        g = harvest.gh_repo_of(url)
        apt = (load_json(HINTS, {}).get("/".join(g).lower() if g else "") or {}).get("apt", [])
        sm = {k: v for k, v in self.cfg["smoke"].items() if k != "row_caps"}
        if stage == "rowprobe":        # ranking a row needn't wait an hour for a huge build: amber is enough
            sm["caps"] = dict(sm.get("caps", {}), **self.cfg["smoke"].get("row_caps", {}))
        return harvest.probe(url, ref, self.cfg["spike"]["image"], name=name, keep=keep, apt=apt, **sm)

    def submit_probe(self, stage, key, url, ref, keep):
        """Two probes of one repo and version would share a Docker volume: run one at a time."""
        pk = probe_key(url, ref)
        if pk in self.probing.values() or self.probes_running() >= self.cfg["pools"]["smoke"]:
            return False
        if self.submit(stage, key, self.probe_job, stage, key, url, ref, keep):
            self.probing[key] = pk
            return True
        return False

    def needs_tree(self, s):
        """A spike reuses the probe's build tree when the source built; re-probe (keeping the tree) if it is gone."""
        p = s.get("smoke") or {}
        if self.args.no_smoke or p.get("tree_failed") or p.get("verdict") not in ("green", "amber") or p.get("timeouts"):
            return False               # (a probe that hit its caps would only hit them again)
        vol = p.get("work_volume")
        if self.args.dry_run:          # CGPIPE_FAULTS=tree:always exercises this path without Docker
            return "tree:always" in os.environ.get("CGPIPE_FAULTS", "") and not vol
        if not vol:
            return True
        try:
            return subprocess.run(["docker", "volume", "inspect", vol], capture_output=True, timeout=30).returncode != 0
        except subprocess.TimeoutExpired:
            return None

    def validated(self):
        return sum(1 for s in all_seeds() if s["status"] == "validated")

    def batch_cap(self):
        return self.args.max_batches or self.cfg.get("max_batches", 99)

    def batch_cap_reached(self, seeds):
        return max([s["batch"] for s in seeds] + [0]) >= self.batch_cap()

    def spare_capacity_reached(self, by):
        ahead = (len(by["v2-pass"]) + len(by["validated"]) +
                 sum(1 for s in by["v1-pass"] if not s.get("v2_done")) // 2)
        if self.cfg["target_validated"] != float("inf") and ahead >= 2 * self.cfg["target_validated"]:
            return True
        # validated_buffer: enough validated ideas already wait for a build; save the plan allowance for builds
        buf = self.cfg.get("validated_buffer")
        if buf and not self.args.dry_run:
            unbuilt = len(set(s["id"] for s in by["validated"]) - building_seeds())
            if unbuilt >= buf:
                if not getattr(self, "buffer_logged", False):
                    log(f"{unbuilt} validated ideas wait for a build (validated_buffer {buf}): no new batches until builds take some")
                    self.buffer_logged = True
                return True
            self.buffer_logged = False
        return False

    # ---- plan-usage pacing
    def pace(self):
        """Pause before a plan limit is hit: utilization comes from every call's rate_limit_event."""
        th = self.cfg["pace"]
        for win, limit in (("five_hour", th["five_hour"]), ("seven_day", th["seven_day"])):
            with IO_LOCK:
                u, reset = UTIL.get(win, (0.0, 0))
            if u >= limit and reset > time.time():
                self.paused_until = reset + (1 if self.args.dry_run else 60)
                reason = f"{win} plan usage at {u:.0%}"
                if reason != self.pause_reason:
                    log(f"pacing: {reason}; pausing new calls until "
                        f"{dt.datetime.fromtimestamp(reset, dt.timezone.utc):%Y-%m-%d %H:%M}Z")
                self.pause_reason = reason
                with IO_LOCK:
                    UTIL.pop(win, None)           # re-read from the next call after the pause
                return True
        return False

    # ---- scheduling (closest to the goal first)
    def schedule(self):
        cfg, seeds, rows = self.cfg, all_seeds(), read_sources()
        self.spent_now = self.spent()
        busy = self.busy_keys()
        free = cfg["max_parallel_calls"] - self.llm_running()
        probing = not self.args.no_smoke
        cache = load_json(SMOKE, {})
        by = collections.defaultdict(list)
        batches = collections.defaultdict(list)
        for s in seeds:
            by[s["status"]].append(s)
            batches[s["batch"]].append(s)
        # 1. spikes, best first; a source that built gets a fresh probe that keeps its build tree for the spike
        if not self.args.no_spike and not self.spikes_off:
            for s in sorted(by["v2-pass"], key=lambda s: -s.get("final", 0)):
                if free <= 0 or self.running("spike") >= cfg["pools"]["spike"]:
                    break
                if s["id"] in busy or s.get("spike_parked"):
                    continue
                if smoke_target(s)[0] and probe_key(*smoke_target(s)) in self.probing.values():
                    continue                  # its repo's tree is being probed or used right now
                tree = self.needs_tree(s)
                if tree is None:              # Docker didn't answer: try again next tick
                    continue
                if tree:
                    self.submit_probe("smoke", s["id"], *smoke_target(s), True)
                    continue
                payload = {"seed": compact_card(s), "v1": s.get("v1", {}).get("full_card"),
                           "spike_plan": s.get("v1", {}).get("spike_plan"),
                           "probe": {k: v for k, v in (s.get("smoke") or {}).items() if k != "work_volume"}}
                if s.get("spike"):          # an inconclusive first attempt: carry on from its notes in /work
                    payload["previous_attempt"] = {k: s["spike"].get(k) for k in ("notes", "blockers", "commands_log")}
                elif any(h[1] == "spike" and h[2] == "error" for h in s.get("history", [])):
                    payload["previous_attempt"] = {"notes": "an earlier attempt stopped with an error or a timeout"}
                fn = (lambda st, k, p: fake(st, k, p)) if self.args.dry_run else \
                    (lambda st, k, p, s=s: call_spike(s, p, self.cfg_for("spike", s["id"]),
                                                      self.boost.get(("spike", s["id"]), 1)))
                if self.submit("spike", s["id"], fn, "spike", s["id"], payload):
                    if smoke_target(s)[0]:
                        self.probing[s["id"]] = probe_key(*smoke_target(s))     # its build tree is in use
                    free -= 1
        # 2. V2 per batch, once every seed of the batch has left V1 (the judge sees evidence, not V1's scores)
        for b, ss in sorted(batches.items()):
            key = f"batch-{b:02d}"
            cands = [s for s in ss if s["status"] == "v1-pass" and not s.get("v2_done")]
            if free <= 0 or key in busy or not cands or any(s["status"] in ("short", "l0-pass") for s in ss):
                continue
            if self.running("v2") >= cfg["pools"]["v2"]:
                break
            if self.submit("v2", key, self.worker, "v2", key, {"seeds": [v2_view(s) for s in cands], "calibration": load_json(os.path.join(DATA, "calibration.json"), [])[-8:]}, ""):
                free -= 1
        # 3. a seed without probe facts (own idea, scout source, or its row was never probed): probe it; V1 waits
        for s in by["l0-pass"]:
            if "smoke" in s or s["id"] in busy:
                continue
            url, ref = smoke_target(s)
            hit = cache.get(probe_key(url, ref)) if url else None
            if not url or hit is not None or not probing:
                s["smoke"] = hit if hit is not None else {"skipped": "no git source" if not url else "disabled"}
                if hit and hit.get("clone_ok") is False:
                    kill(s, "K2", "smoke", "source repo not reachable (cached)")
                save_seed(s)
            else:
                self.submit_probe("smoke", s["id"], url, ref, False)
        # 4. V1 per seed: it never waits for a probe (probes add facts when a slot is free; the spike re-probes later)
        for s in by["l0-pass"]:
            if free <= 0 or self.running("v1") >= cfg["pools"]["v1"]:
                break
            if s["id"] not in busy and s["status"] == "l0-pass":
                if self.submit("v1", s["id"], self.worker, "v1", s["id"], {"seed": compact_card(s), "calibration": load_json(os.path.join(DATA, "calibration.json"), [])[-8:]}, "WebSearch,WebFetch"):
                    free -= 1
        more_needed = (not self.batch_cap_reached(seeds) and not self.spare_capacity_reached(by)
                       and not self.write_disabled and self.validated() < cfg["target_validated"])
        if not more_needed:
            return
        unused = [r for r in rows if r["status"] == "unused"]
        # 5a. enrich rows that have no facts yet (no tokens; GitHub API): priority, and so probe order, depends on it
        first = {r["key"] for r in pick_rows_for_batch(rows, cfg, seeds)}     # the writer's next rows go first
        unfacted = sorted((r for r in unused if harvest.gh_repo_of(r["url"]) and not enriched(r)),
                          key=lambda r: (r["key"] not in first, int(row_facts(r).get("enrich_failed") or 0)))
        if unfacted and self.running("enrich") == 0 and "enrich" not in busy:
            todo = unfacted[:cfg["enrich_batch"]]
            keys = sorted({"/".join(harvest.gh_repo_of(r["url"])).lower() for r in todo})
            tree_for = sorted({"/".join(harvest.gh_repo_of(r["url"])).lower() for r in todo
                               if (r["class"] or "implementation") in cfg["tree_count_for"]})
            self.submit("enrich", "enrich", self.enrich_job, keys, tree_for)

        # 5b. probe source rows before the writer sees them (zero tokens): rows that build and test move up, rows
        #    whose repo is gone are blocked, and their seeds start V1 without waiting for a probe
        def ready(r):
            return not probing or not probe_target(r["url"], r["version"])[0] or "probe" in row_facts(r)
        # Probe exactly the rows the writer would get now; each verdict moves its row up or down, so the pick
        # changes until every row in it is probed. Spare probe slots work ahead on the next-best rows.
        changed, pick = False, []
        for _ in range(50):                               # resolve cached verdicts without waiting for a loop
            pick = pick_rows_for_batch(rows, cfg, seeds)
            hits = [r for r in pick if not ready(r) and probe_key(*probe_target(r["url"], r["version"])) in cache]
            if not hits:
                break
            for r in hits:
                self.mark_probed(r, cache[probe_key(*probe_target(r["url"], r["version"]))]); changed = True
        if changed:
            write_sources(rows)
        pick_wait = [r for r in pick if not ready(r)]
        # a failing enrich must not hold up writing; a pick without unenriched rows needn't wait for it either
        enriching = not self.blocked("enrich") and any(harvest.gh_repo_of(r["url"]) and not enriched(r) for r in pick)
        probed = sum(1 for r in unused if "probe" in row_facts(r))
        ahead = [] if probed >= 6 * cfg["batch_size"] else sorted(
            (r for r in unused if not ready(r) and enriched(r) and r not in pick_wait),
            key=lambda r: -float(r.get("priority") or 30))[:2 * cfg["batch_size"]]
        # keep a probe slot free for the re-probe a spike waits on
        slots = cfg["pools"]["smoke"] - (1 if by["v2-pass"] and not self.args.no_spike else 0)
        offer = [r for r in pick if ready(r)]
        if getattr(self.args, "warmup", False) and not enriching and len(offer) >= cfg["batch_size"] + 2 and not ahead:
            pick_wait = []             # warm-up is done: the writer could write now; nothing more to probe
        for r in pick_wait + ahead:
            pk = probe_key(*probe_target(r["url"], r["version"]))
            if (row_facts(r).get("kb") or 0) > 2_000_000:          # over 2 GB on GitHub: skip the probe
                self.mark_probed(r, {"skipped": "repo over 2 GB, not probed"}); write_sources(rows)
            elif pk in cache:                               # another row of the same repo was probed already
                self.mark_probed(r, cache[pk]); write_sources(rows)
            elif self.probes_running() < slots and "row:" + r["key"] not in busy:
                self.submit_probe("rowprobe", "row:" + r["key"], *probe_target(r["url"], r["version"]), False)
        # 6. continuous sourcing: the next batch once the previous one has left L0, V1's backlog is under one batch,
        #    and every row in the pick is probed
        key = f"write-{self.batches_written + 1:02d}"
        v1_backlog = sum(1 for s in by["l0-pass"] if s["id"] not in busy)
        # the writer takes the best rows that are ready now (probed, or nothing to probe); rows still probing join a
        # later batch, so a few slow probes of huge repos never hold up writing
        # (any enriched row qualifies: a probe verdict moves a row up or down, but probing never gates writing;
        #  a seed whose row wasn't probed is probed after L0)
        offer = pick_rows_for_batch([r for r in rows if r["status"] != "unused" or ready(r) or enriched(r)], cfg, seeds)
        enriching = not self.blocked("enrich") and any(harvest.gh_repo_of(r["url"]) and not enriched(r) for r in offer)
        if (free > 0 and key not in busy and self.running("write") == 0 and not by["short"] and not enriching
                and v1_backlog < cfg["batch_size"] and len(offer) >= cfg["batch_size"]):
            pick = offer
            ids = {f"r{i + 1}": r["key"] for i, r in enumerate(pick)}
            payload = {"batch_size": cfg["batch_size"], "quota": cfg["quota"], "method_mix": cfg["method_mix"],
                       "rows": [row_for_writer(r, rid) for rid, r in zip(ids, pick)],
                       "existing_titles": [s["card"].get("title") for s in seeds][-200:],
                       "lessons": {"judge_notes": [n["note"] for n in load_json(os.path.join(DATA, "lessons.json"), [])[-3:]],
                                   "recent_kills": {f"{k} {KILL_LABEL.get(k, '')}": n for k, n in collections.Counter(
                                       s.get("kill") for s in seeds[-80:] if s.get("kill")).most_common(6)},
                                   "trial_results": load_json(os.path.join(DATA, "calibration.json"), [])[-6:]}}
            if self.submit("write", key, self.worker, "write", key, payload, ""):
                self.offered[key] = ids; free -= 1
        # 7. harvest channels that have harvesters and are due (no tokens)
        if self.running("harvest") == 0:
            due = [c for c in cfg["channels"] if c.get("harvest") and not c.get("exhausted") and
                   time.time() - c.get("harvested", 0) > cfg["harvest_every_hours"] * 3600]
            for c in due[:1]:
                if f"harvest-{c['id']}" not in busy:
                    self.submit("harvest", f"harvest-{c['id']}", self.harvest_job, c)
        # 8. LLM scouts, only for classes whose unused rows can't cover the remaining batches: channels without a
        #    working harvester, or every channel of a short class when the whole pool runs low
        remaining = max(0, self.batch_cap() - max([s["batch"] for s in seeds] + [0]))
        have = collections.Counter((r["class"] or "implementation") for r in unused)
        short = {c for c, n in class_want(cfg).items() if have[c] < 1.5 * n * remaining}
        low = len(unused) < cfg["min_unused_sources"]
        chans = [c for c in cfg["channels"] if not c.get("exhausted") and c["class"] in short and
                 (low or not c.get("harvest") or c.get("harvest_failed"))]
        chans.sort(key=lambda c: c.get("scouted", 0))
        slots = cfg["pools"]["scout"] - self.running("scout")
        for ch in chans:
            if slots <= 0 or free <= (0 if low else 2):          # leave room for validation work
                break
            key = f"scout-{ch['id']}"
            if key in busy:
                continue
            known = [r["name"] for r in rows if (r["class"] or "implementation") == ch["class"]][-150:]
            if self.submit("scout", key, self.worker, "scout", key,
                           {"channel": {k: ch[k] for k in ("id", "class", "what", "hints")}, "already_known": known},
                           "WebSearch,WebFetch"):
                ch["scouted"] = ch.get("scouted", 0) + 1; slots -= 1; free -= 1

    def mark_probed(self, r, res):
        """Record a probe's verdict on its source row and move the row up or down the queue."""
        f = row_facts(r)
        f["probe"] = probe_summary(res)
        r["facts"] = json.dumps(f, separators=(",", ":"))
        if res.get("clone_ok") is False:
            r["status"] = "blocked"
        r["priority"] = str(row_priority(r))

    # ---- applying results (main thread only)
    def apply(self, stage, key, res):
        cfg = self.cfg
        if stage == "harvest":
            ch = next(c for c in cfg["channels"] if f"harvest-{c['id']}" == key)
            n = add_sources(res.get("rows", []), "harvest:" + ch["id"])
            ch["harvested"], ch["harvest_rows"], ch["harvest_failed"] = time.time(), n, False
            if res.get("hints"):            # recipe hints for the probe (apt packages), keyed by owner/repo
                hints = load_json(HINTS, {})
                hints.update(res["hints"])
                atomic_write(HINTS, json.dumps(hints, indent=1, sort_keys=True))
            self.save_channels()
            log(f"harvest {ch['id']}: {len(res.get('rows', []))} found, {n} new"
                + (f"; errors: {'; '.join(res['errors'])[:200]}" if res.get("errors") else ""))
        elif stage == "enrich":
            facts, keys, rows, n = res.get("facts", {}), set(res.get("keys", [])), read_sources(), 0
            for r in rows:
                g = harvest.gh_repo_of(r["url"])
                k = "/".join(g).lower() if g else None
                if r["status"] != "unused" or enriched(r) or k not in keys:
                    continue          # only the repos this call asked about
                old = row_facts(r)
                f = dict(facts[k]) if k in facts else {"enrich_failed": int(old.get("enrich_failed") or 0) + 1}
                if "probe" in old:    # probed before enrich answered: keep the verdict
                    f["probe"] = old["probe"]
                r["facts"] = json.dumps(f, separators=(",", ":"))
                r["priority"] = str(row_priority(r))
                if f.get("archived") or f.get("fork") or f.get("not_found"):
                    r["status"] = "blocked"
                n += 1
            write_sources(rows)
            log(f"enrich: facts for {n} rows")
        elif stage in ("smoke", "rowprobe"):
            cache = load_json(SMOKE, {})
            if stage == "rowprobe":
                rows = read_sources()
                r = next((x for x in rows if "row:" + x["key"] == key), None)
                if r:
                    cache[probe_key(*probe_target(r["url"], r["version"]))] = res
                    self.mark_probed(r, res)
                    write_sources(rows)
                    log(f"probe {r['name'] or r['url']}: {res.get('verdict', 'unreachable')}, "
                        f"{res.get('tests_total', 0)} tests")
            else:
                s = load_json(seed_path(key))
                url, ref = smoke_target(s)
                cache[probe_key(url, ref)] = dict(res, work_volume="")   # a tree belongs to one seed
                s["smoke"] = res
                if res.get("clone_ok") is False:
                    kill(s, "K2", "smoke", "source repo not reachable")
                else:
                    hist(s, "smoke", res.get("verdict", "?"),
                         f"{res.get('eco')}: build {'ok' if res.get('build_ok') else 'failed'}, "
                         f"{res.get('tests_total', 0)} tests, {res.get('tests_fail', 0)} failing, "
                         f"{'deterministic' if res.get('deterministic') else 'NOT deterministic'} over 3 runs")
                save_seed(s)
            atomic_write(SMOKE, json.dumps(cache, indent=1))
        elif stage == "scout":
            ch = next(c for c in cfg["channels"] if f"scout-{c['id']}" == key)
            n = add_sources(res.get("rows", []), "scout:" + ch["id"])
            log(f"scout {ch['id']}: {n} new rows")
            ch["dry"] = ch.get("dry", 0) + (1 if n < 3 else 0)
            if res.get("exhausted") or ch["dry"] >= 2:
                ch["exhausted"] = True
                log(f"channel {ch['id']} exhausted")
            self.save_channels()
        elif stage == "write":
            self.batches_written += 1
            ids = self.offered.pop(key, {})
            seeds, rows, cache = all_seeds(), read_sources(), load_json(SMOKE, {})
            b = max([s["batch"] for s in seeds] + [0]) + 1
            byk = {r["key"]: r for r in rows}
            for r in rows:                 # offered counts only rows the writer actually saw
                if r["key"] in ids.values():
                    r["offered"] = str(int(r["offered"] or 0) + 1)
            n, used = 0, set()
            for c in res.get("cards", []):
                src = byk.get(ids.get(str(c.get("row", "")).strip()))
                if not src or src["key"] in used or n >= cfg["batch_size"]:
                    continue               # an unknown or repeated row id: no traceable source, so no seed
                used.add(src["key"]); n += 1
                cls = c.get("class") if c.get("class") in CLASS_CODE else "implementation"
                s = {"id": next_id(cls, seeds), "batch": b, "class": cls, "family": c.get("family"),
                     "method": c.get("method"), "source_key": src["key"], "status": "short", "kill": None,
                     "created": now(), "source_facts": {k: v for k, v in row_facts(src).items() if k != "probe"},
                     "source_url": src.get("url", ""), "source_version": src.get("version", ""),
                     "source_notes": src.get("notes", ""),
                     "card": {k: c.get(k, "") for k in ("title", "source", "task", "grading", "reference", "band", "cheat")}}
                hit = cache.get(probe_key(*smoke_target(s))) if smoke_target(s)[0] else None
                skipped = (row_facts(src).get("probe") or {}).get("skipped")
                if hit is not None and hit.get("clone_ok") is not False:
                    s["smoke"] = hit      # probed before writing: V1 starts without waiting
                elif skipped and hit is None:
                    s["smoke"] = {"skipped": skipped}
                hist(s, "write", "short", f"batch {b}")
                src["status"], src["used_by"] = "used", s["id"]
                self.l0(s, seeds)
                save_seed(s); seeds.append(s)
            for r in rows:
                if r["status"] == "unused" and int(r["offered"] or 0) >= 3:
                    r["status"] = "stale"
            write_sources(rows)
            log(f"batch {b}: {n} cards written ({len(res.get('cards', [])) - n} without a known row)")
        elif stage == "v1":
            s = load_json(seed_path(key))
            if s["status"] != "l0-pass":
                log(f"v1 {key}: result ignored, the seed is now {s['status']}"); return
            dead = res.pop("_links", None) or {"checked": 0, "dead": [], "ratio": 0.0}
            sc = {k: v.get("v") for k, v in res.get("scores", {}).items()}
            grade = res.get("evidence_grade", "E0")
            confirmed_dead = [f for f in res.get("facts", []) if f.get("status") == "confirmed" and f.get("url") in dead["dead"]]
            if dead["ratio"] > 0.5:                               # most cited evidence doesn't exist: Real fails its gate
                sc["Real"] = min(sc.get("Real", 1), 2)
            elif dead["ratio"] > 0.34 or confirmed_dead:          # a guessed path or branch name: a warning
                sc["Real"] = min(sc.get("Real", 1), 3)
            fh, th = res.get("frontier_hours") or 0, res.get("tier_hours") or 8
            if 0 < fh < th / 4:                                  # too easy for its tier: Band can't count it as in band
                sc["Band"] = min(sc.get("Band", 1), 3)
            if grade == "E1" and (not res.get("evidence_url") or res.get("evidence_url") in dead["dead"]):
                grade = "E0"                                     # E1 needs a live, dated source
            total, gate, capped = score(sc, grade)
            s["v1"], s["v1_score"], s["v1_links"] = res, total, dead
            code = res.get("kill_code") or ""
            if KCODE.fullmatch(code):
                kill(s, code, "v1", res.get("kill_reason", ""))
            elif gate:
                kill(s, gate, "v1", f"gate on scores {capped}" + (f"; dead cited links {dead['dead']}" if dead["dead"] else ""))
            elif total < cfg["lines"]["v1_keep"]:
                kill(s, "K8", "v1", f"score {total} below line")
            else:
                s["status"] = "v1-pass"; hist(s, "v1", "pass", f"score {total}; dead links {dead['dead']}")
            save_seed(s)
        elif stage == "v2":
            b = int(key.split("-")[1])
            if res.get("batch_note"):          # what this batch teaches the writer (fed back in the next write)
                notes = load_json(os.path.join(DATA, "lessons.json"), [])
                notes.append({"batch": b, "note": res["batch_note"][:600]})
                atomic_write(os.path.join(DATA, "lessons.json"), json.dumps(notes[-10:], indent=1))
            got = {str(x.get("id", "")).strip().upper(): x for x in res.get("seeds", [])}
            rank = [str(x).strip().upper() for x in res.get("ranking", [])]
            for s in all_seeds():
                if s["batch"] != b or s["status"] != "v1-pass" or s.get("v2_done"):
                    continue
                v = got.get(s["id"].upper())
                if not v:                  # never pass a seed the judge didn't score: ask again, then park it
                    s["v2_missed"] = s.get("v2_missed", 0) + 1
                    if s["v2_missed"] >= 2:
                        s["v2_done"] = True
                        hist(s, "v2", "parked", f"the judge skipped it twice; `requeue {s['id']} v2` to retry")
                    else:
                        hist(s, "v2", "missing", "the judge skipped this seed; it goes to the next judge call")
                    save_seed(s)
                    continue
                s["v2_done"] = True
                total, gate, _ = score(v["scores"], v.get("evidence_grade", "E0"))
                s["v2"], s["v2_score"], s["final"] = v, total, min(total, s["v1_score"])
                s["rank"] = rank.index(s["id"].upper()) + 1 if s["id"].upper() in rank else None
                code = v.get("kill_code") or ""
                if KCODE.fullmatch(code):
                    kill(s, code, "v2", v.get("note", ""))
                elif gate:
                    kill(s, gate, "v2", "gate on judge scores")
                elif s["final"] < cfg["lines"]["v2_keep"]:
                    kill(s, "K8", "v2", f"final {s['final']} below line")
                else:
                    s["status"] = "v2-pass"; hist(s, "v2", "pass", f"final {s['final']}")
                save_seed(s)
        elif stage == "spike":
            s = load_json(seed_path(key))
            if s["status"] != "v2-pass":
                log(f"spike {key}: result ignored, the seed is now {s['status']}"); return
            s["spike"] = res
            code = spike_kill(res, s.get("method"), s.get("class", "implementation"),
                              self.cfg.get("spike_quick_share_max", QUICK_SHARE_MAX))
            if code is None:
                s["status"] = "validated"; hist(s, "spike", "validated", res.get("notes", ""))
            elif res.get("verdict") == "inconclusive" and s.get("attempts", {}).get("spike", 0) < 1:
                s.setdefault("attempts", {})["spike"] = 1; hist(s, "spike", "retry", res.get("notes", ""))
            else:
                qa = res.get("quick_attempt") or {}
                why = (f"too easy: a {qa.get('minutes', '?')}-minute Sonnet attempt reached {qa.get('share', 0):.0%} of the reference"
                       if code == "K8" and qa.get("tried") and (qa.get("share") or 0) >= self.cfg.get("spike_quick_share_max", QUICK_SHARE_MAX)
                       else "; ".join(res.get("blockers", []))[:300] or res.get("notes", ""))
                kill(s, code, "spike", why)
            save_seed(s)

    def l0(self, s, seeds):
        live = [(o["id"], card_text(o)) for o in seeds if o["id"] != s["id"] and not o["status"].startswith("killed")]
        pub = self.corpus.top(card_text(s), 5)
        own = sorted(((self.corpus.cos(self.corpus.vec(collections.Counter(toks(card_text(s)))),
                                       self.corpus.vec(collections.Counter(toks(t)))), n) for n, t in live),
                     reverse=True)[:3]
        top = sorted(pub + own, reverse=True)[:5]
        s["l0"] = {"neighbours": [[round(x, 3), n] for x, n in top]}
        if pub and pub[0][0] >= self.cfg["similarity"]["kill"]:
            kill(s, "K1", "l0", f"near-duplicate of public task {pub[0][1]} ({pub[0][0]:.2f})")
        elif own and own[0][0] >= self.cfg["similarity"]["kill_seed"]:   # cards share a template: only near-identical
            kill(s, "K1", "l0", f"near-duplicate of seed {own[0][1]} ({own[0][0]:.2f})")
        else:
            s["status"] = "l0-pass"
            hist(s, "l0", "pass", f"top neighbour {top[0][1] if top else '-'} {top[0][0] if top else 0:.2f}")

    # ---- failures
    def requeue_failed(self, stage, key, why):
        if stage in self.cfg["call_budget_usd"] and re.search(r"error_max_turns|error_max_budget|timeout after", why):
            self.boost[(stage, key)] = 1.5     # a model call hit a cap: the retry gets 1.5x turns, budget and time
        if stage == "rowprobe" and self.fails[key] < 3:
            self.fails[key] = 3                # one try is enough to rank a row
        if self.fails[key] < 3:
            if stage in ("v1", "spike"):
                s = load_json(seed_path(key))
                if s:
                    hist(s, stage, "error", why); save_seed(s)
            return
        if stage == "smoke":          # the probe is advisory: after three failures V1 (or the spike) proceeds without it
            s = load_json(seed_path(key))
            if s:
                if s.get("smoke") and not s["smoke"].get("skipped"):
                    s["smoke"].update(work_volume="", tree_failed=True)   # keep the earlier facts; spike without a tree
                else:
                    s["smoke"] = {"skipped": f"probe failed 3 times: {why}"[:200]}
                save_seed(s)
            self.settle(key)
        elif stage == "rowprobe":
            rows = read_sources()
            r = next((x for x in rows if "row:" + x["key"] == key), None)
            if r:
                pk = probe_key(*probe_target(r["url"], r["version"]))
                for x in rows:
                    if x["status"] == "unused" and probe_key(*probe_target(x["url"], x["version"])) == pk:
                        self.mark_probed(x, {"skipped": f"probe failed 3 times: {why}"[:120]})
                write_sources(rows)
            self.settle(key)
        elif stage == "harvest":      # a broken harvester hands its channel to the LLM scouts until it works again
            ch = next(c for c in self.cfg["channels"] if f"harvest-{c['id']}" == key)
            ch["harvested"], ch["harvest_failed"] = time.time(), True
            self.save_channels(); self.settle(key)
            log(f"harvest {ch['id']} failed 3 times ({why[:120]}): scouts cover this channel until the next harvest")
        elif stage == "enrich":
            log(f"enrich failed 3 times ({why[:120]}): retrying in 30 minutes")
            self.fails[key] = 0; self.retry_at[key] = time.time() + 1800
        elif stage == "scout":
            ch = next(c for c in self.cfg["channels"] if f"scout-{c['id']}" == key)
            ch["exhausted"] = True
            self.save_channels(); log(f"channel {ch['id']} disabled after 3 failed scouts")
        elif stage == "write":
            self.write_disabled = True; log("writer failed 3 times: no new batches this run")
        elif stage == "v2":           # never promote on V1 (Haiku) scores alone: park the batch for a later judge call
            b = int(key.split("-")[1])
            for s in all_seeds():
                if s["batch"] == b and s["status"] == "v1-pass" and not s.get("v2_done"):
                    s["v2_done"] = True
                    hist(s, "v2", "parked", f"the judge failed 3 times ({why}); `requeue {s['id']} v2` to retry")
                    save_seed(s)
            self.settle(key); log(f"judge failed 3 times on {key}: its seeds are parked at v1-pass")
        elif stage == "spike":       # the idea survived V1 and V2: an infrastructure fault must not kill it
            s = load_json(seed_path(key))
            if s:
                s["spike_parked"] = why[:200]
                hist(s, "spike", "parked", f"3 failed calls ({why}); `requeue {s['id']} spike` retries"); save_seed(s)
            self.settle(key); log(f"spike {key}: 3 failed calls, parked at v2-pass (requeue to retry)")
        elif stage == "v1":
            s = load_json(seed_path(key))
            if s:
                kill(s, "K13", stage, f"3 failed calls: {why}"); save_seed(s)
            self.settle(key); log(f"{stage} {key}: 3 failed calls, killed K13")

    # ---- main loop
    def prune_volumes(self):
        """Remove kept probe build trees (cgp-work-*) that no live seed and no running probe needs."""
        self.last_prune = time.time()
        try:
            p = subprocess.run(["docker", "volume", "ls", "-q", "--filter", "name=cgp-work-"],
                               capture_output=True, text=True, timeout=60)
            if p.returncode != 0:
                return
            keep = {(s.get("smoke") or {}).get("work_volume") for s in all_seeds() if s["status"] == "v2-pass"}
            for st, k in list(self.inflight.values()):
                if st in ("smoke", "rowprobe", "spike"):
                    if k.startswith("row:"):
                        r = next((x for x in read_sources() if "row:" + x["key"] == k), None)
                        if r:
                            keep.add(harvest.work_volume(*probe_target(r["url"], r["version"])))
                    else:
                        keep.add(harvest.work_volume(*smoke_target(load_json(seed_path(k)))))
            gone = [v for v in p.stdout.split() if v not in keep]
            t0 = time.time()
            for v in gone:     # Docker refuses to remove a volume a container still uses
                if time.time() - t0 > 120:
                    break      # never hold up scheduling for long; the rest goes next time
                subprocess.run(["docker", "volume", "rm", v], capture_output=True, timeout=30)
            if gone:
                log(f"pruned {len(gone)} probe volume(s) no seed needs")
        except Exception as e:  # noqa: BLE001 (housekeeping must never stop the run)
            log(f"volume prune skipped: {e}")

    def preflight(self):
        """Refuse to start when a missing tool, login, image or token would turn every call into a failure."""
        def ok(cmd):
            try:
                return subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                return False
        bad = []
        if not ok([CLAUDE, "--version"]):
            bad.append(f"{CLAUDE} --version failed: install or log in to Claude Code")
        if not ok(["gh", "auth", "status"]):
            bad.append("gh auth status failed: run gh auth login")
        if (not self.args.no_smoke or not self.args.no_spike) and not ok(["docker", "image", "inspect", self.cfg["spike"]["image"]]):
            bad.append(f"Docker image {self.cfg['spike']['image']} missing or Docker down: README section 5, step 3")
        envf = os.path.expanduser(self.cfg["spike"]["env_file"])
        if not self.args.no_spike:
            if not os.path.exists(envf):
                bad.append(f"{envf} missing (the spike token): run `bash pipeline/setup-token.sh`, or use --no-spike")
            elif os.stat(envf).st_mode & 0o077:
                bad.append(f"{envf} is readable by others: chmod 600 {envf}")
        if bad:
            sys.exit("preflight failed:\n  - " + "\n  - ".join(bad))

    def check_spec(self):
        """capture/instructions.md is the single source of truth; prompts.txt COMMON is a digest of it."""
        got = hashlib.sha256(open(os.path.join(ROOT, "capture", "instructions.md"), "rb").read()).hexdigest()
        if got != self.cfg.get("spec_sha256"):
            sys.exit("capture/instructions.md changed since prompts.txt COMMON was written. Review COMMON against the "
                     "spec, then set spec_sha256 in pipeline/config.json to: " + got)

    def on_signal(self, *_):
        self.signals += 1
        if self.signals == 1:
            self.stop = True
            log("stop requested: finishing in-flight calls (press Ctrl-C again to kill them)")
        else:
            kids = list(CHILDREN)
            log(f"hard stop: killing {len(kids)} worker(s); their seeds are retried on the next run")
            for p in kids:
                kill_child(p)
            if not self.args.dry_run:
                kill_containers()      # dockerd owns spike and probe containers: killing the client leaves them running
            os._exit(130)

    def idle_exhausted(self):
        seeds, rows = all_seeds(), read_sources()
        live = [s for s in seeds if not s["status"].startswith("killed") and s["status"] != "validated"
                and not (s["status"] == "v1-pass" and s.get("v2_done"))]
        if self.args.no_spike or self.spikes_off:
            live = [s for s in live if s["status"] != "v2-pass"]
        live = [s for s in live if not s.get("spike_parked")]
        if live:
            return False
        by = collections.defaultdict(list)
        for s in seeds:
            by[s["status"]].append(s)
        if self.batch_cap_reached(seeds) or self.write_disabled or self.spare_capacity_reached(by):
            return True
        unused = sum(1 for r in rows if r["status"] == "unused")
        chans = [c for c in self.cfg["channels"] if not c.get("exhausted")]
        return unused < self.cfg["batch_size"] and not chans

    def run(self):
        self.check_spec()
        if not self.args.dry_run:
            self.preflight()
            kill_containers()          # left over from a crashed run (we hold the lock, so none is ours)
            self.prune_volumes()
        rows, n = read_sources(), 0
        for r in rows:                 # a probe skipped in an earlier run (an outage, say) gets another try, but not
            f = row_facts(r)           # one the repo itself caused (over 2 GB, or failed three times): those repeat forever
            why = str((f.get("probe") or {}).get("skipped") or "")
            if r["status"] == "unused" and why and not why.startswith(("probe failed", "repo over")):
                f.pop("probe"); r["facts"] = json.dumps(f, separators=(",", ":")); r["priority"] = str(row_priority(r)); n += 1
        if n:
            write_sources(rows); log(f"{n} rows whose probe was skipped in an earlier run will be probed again")
        log(f"run start (dry-run={self.args.dry_run}, target={self.cfg['target_validated']}, "
            f"budget=${self.cfg['budget_usd']})")
        log(f"state: {len(all_seeds())} seeds, {sum(1 for r in read_sources() if r['status'] == 'unused')} unused sources")
        if os.path.exists(STOPF):
            os.remove(STOPF); log("removed a stale STOP file from an earlier stop request")
        signal.signal(signal.SIGTERM, self.on_signal)
        signal.signal(signal.SIGINT, self.on_signal)
        while True:
            for f in [f for f in self.inflight if f.done()]:
                stage, key = self.inflight.pop(f)
                self.probing.pop(key, None)
                self.last_activity = time.time()
                try:
                    self.apply(stage, key, f.result())
                    self.backoff, self.outages = 300, 0
                    self.fails.pop(key, None); self.retry_at.pop(key, None)
                except UsageLimit as e:
                    wait = (e.until - time.time() + 60) if e.until else self.backoff
                    self.paused_until = time.time() + (1 if self.args.dry_run else max(60, wait))
                    self.pause_reason = "plan usage limit"
                    log(f"usage limit on {stage} {key}: pausing {int(self.paused_until - time.time())}s ({e})")
                    self.backoff = min(self.backoff * 2, 3600)
                except Exception as e:  # noqa: BLE001 (a failed call must never stop the loop)
                    log(f"error {stage} {key}: {type(e).__name__}: {e}")
                    t = time.time()
                    # infrastructure-looking failures only: a cap hit or a bad answer is about the call, not an outage
                    if stage == "spike" and AUTH_RX.search(str(e)):
                        self.spikes_off = f"the spike token was rejected ({str(e)[:100]})"
                        log(f"spike {key}: {self.spikes_off}. Spikes stop; V1 and V2 go on. Renew the token "
                            "(bash pipeline/setup-token.sh --force) and restart the run to resume spikes")
                        self.retry_at[key] = 0
                        continue
                    if stage in self.cfg["call_budget_usd"] and AUTH_RX.search(str(e)) and self.outages < 3:
                        self.outages += 1
                        self.paused_until = t + (1 if self.args.dry_run else 600)
                        self.pause_reason = "authentication failed"
                        log(f"{stage} {key}: authentication failed ({str(e)[:120]}); pausing 10 minutes. If this repeats, "
                            "log in to Claude Code again (claude /login)")
                        self.retry_at[key] = self.paused_until
                        continue
                    llm = stage in self.cfg["call_budget_usd"] and not re.search(
                        r"error_max_turns|error_max_budget|structured_output|timeout after", str(e))
                    self.errors = [(ts, k) for ts, k in self.errors if ts > t - 600] + ([(t, key)] if llm else [])
                    if llm and len({k for _, k in self.errors}) >= 4 and self.outages < 3:
                        self.outages += 1      # after 3 pauses with no success in between, failures count again
                        self.paused_until = t + (1 if self.args.dry_run else 600)     # likely an outage
                        self.pause_reason = "several calls failed at once (outage?)"
                        log("several different calls failed within 10 minutes: probably an outage (login, network, "
                            "provider or Docker); pausing new calls for 10 minutes without counting these failures")
                        self.errors = []
                        self.retry_at[key] = self.paused_until
                        continue
                    self.fails[key] += 1
                    self.retry_at[key] = time.time() + (5 if self.args.dry_run else 120 * self.fails[key])
                    self.requeue_failed(stage, key, str(e))
            with IO_LOCK:
                usage = dict(UTIL)
            atomic_write(USAGE, json.dumps(usage))
            atomic_write(STATE, json.dumps({
                "ts": time.time(), "ended": None, "pid": os.getpid(), "run_started": self.run_started, "dry_run": self.args.dry_run,
                "target": None if self.cfg["target_validated"] == float("inf") else self.cfg["target_validated"],
                "budget": self.cfg["budget_usd"], "paused_until": self.paused_until, "pause_reason": self.pause_reason,
                "stopping": bool(self.stop or os.path.exists(STOPF)), "write_disabled": self.write_disabled,
                "spikes_off": self.spikes_off,
                "pools": self.cfg["pools"], "max_parallel_calls": self.cfg["max_parallel_calls"],
                "inflight": [{"stage": st, "key": k, "since": self.started.get(k, time.time())}
                             for st, k in self.inflight.values()],
                "failing": {k: n for k, n in self.fails.items() if n}}))
            done = self.validated() >= self.cfg["target_validated"]
            broke = self.spent() + min(self.cfg["call_budget_usd"].values()) > self.cfg["budget_usd"] or (
                not self.inflight and self.budget_refused > self.last_activity and time.time() - self.last_activity > 60)
            stopping = self.stop or os.path.exists(STOPF) or done or broke
            if stopping and not self.inflight:
                self.end_reason = "target reached" if done else "budget reached" if broke else "stop requested"
                log("run end: " + self.end_reason)
                break
            if self.pause_reason and time.time() >= self.paused_until and not self.pace():
                self.pause_reason = ""
            if not stopping and time.time() >= self.paused_until and not self.pace():
                self.schedule()
                if (getattr(self.args, "warmup", False) and not self.inflight
                        and time.time() - self.last_activity > (5 if self.args.dry_run else 30)):
                    self.end_reason = "warm-up done"
                    log("run end: warm-up done (harvest, enrich and probes finished; nothing zero-token left)")
                    break
                if not self.inflight and self.idle_exhausted():
                    self.end_reason = "nothing left to do"
                    log("run end: nothing left to do (batch cap reached, writer stopped, or sources and channels "
                        "exhausted; no seed queued)")
                    break
                idle = time.time() - self.last_activity
                if not self.inflight and idle > (10 if self.args.dry_run else 900):
                    self.end_reason = "stalled"
                    log(f"run end: stalled ({int(idle)}s with nothing schedulable); check `status` and pipeline.log")
                    break
            if not self.args.dry_run and time.time() - getattr(self, "last_prune", 0) > 600:
                self.prune_volumes()
            time.sleep(0.2 if self.args.dry_run else 5)
        self.pool.shutdown(wait=True)
        if not self.args.dry_run:
            self.prune_volumes()
        st = load_json(STATE, {})
        st.update(ts=time.time(), ended=getattr(self, "end_reason", "ended"), inflight=[])
        atomic_write(STATE, json.dumps(st))
        if os.path.exists(STOPF):
            os.remove(STOPF)
        cmd_status()


def kill_containers():
    """Remove probe and spike containers (they belong to dockerd, not to this process)."""
    try:
        ids = subprocess.run(["docker", "ps", "-aq", "--filter", "name=cgspike-", "--filter", "name=cgprobe-"],
                             capture_output=True, text=True, timeout=30).stdout.split()
        if ids:
            subprocess.run(["docker", "rm", "-f"] + ids, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        pass


def check_urls(urls):
    """Zero-token hallucination guard: HEAD each cited URL (in parallel); count the dead ones."""
    urls = sorted({u for u in urls if u and u.startswith("http")})[:20]

    def dead(u):
        """Only a 404/410 answer or a name that doesn't resolve is evidence; HEAD refusals, bot walls, timeouts
        and server errors are not (crates.io and Kaggle answer HEAD with 404 for pages that exist)."""
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 cgpipe", "Accept": "text/html,*/*",
                                                 "Range": "bytes=0-1023"})
        try:
            with urllib.request.urlopen(req, timeout=15):
                return False
        except urllib.error.HTTPError as e:
            return e.code in (404, 410)
        except urllib.error.URLError as e:
            return isinstance(e.reason, socket.gaierror)
        except Exception:  # noqa: BLE001
            return False
    with cf.ThreadPoolExecutor(8) as ex:
        bad = [u for u, d in zip(urls, ex.map(dead, urls)) if d]
    return {"checked": len(urls), "dead": bad, "ratio": (len(bad) / len(urls)) if urls else 0.0}


# ---------------------------------------------------------------- dry-run fakes (zero tokens; test the plumbing)
def cmd_status():
    seeds, rows = all_seeds(), read_sources()
    st = collections.Counter(s["status"] for s in seeds)
    src = collections.Counter(r["status"] for r in rows)
    n_enriched = sum(1 for r in rows if enriched(r))
    n_probed = collections.Counter((row_facts(r).get("probe") or {}).get("verdict") or "skipped"
                                   for r in rows if "probe" in row_facts(r))
    cost, calls, errs = collections.defaultdict(float), collections.Counter(), collections.Counter()
    for r in cost_records():
        cost[r["stage"]] += r.get("cost", 0) or 0; calls[r["stage"]] += 1
        errs[r["stage"]] += 1 if r.get("error") else 0
    print(f"seeds: {len(seeds)}  " + "  ".join(f"{k}={v}" for k, v in sorted(st.items())))
    print(f"sources: {len(rows)} ({n_enriched} enriched; probed: "
          + (", ".join(f"{k} {v}" for k, v in sorted(n_probed.items())) or "none") + ")  "
          + "  ".join(f"{k}={v}" for k, v in sorted(src.items())))
    print("cost by stage (list-price estimate): " + "  ".join(f"{k}=${v:.2f}/{calls[k]} calls/{errs[k]} err"
                                                           for k, v in sorted(cost.items())) + f"  total=${sum(cost.values()):.2f}")
    use = load_json(USAGE, {})
    if use:
        print("plan usage at last call: " + "  ".join(f"{k}={v[0]:.0%}" for k, v in use.items()))
    kills = collections.Counter(s["kill"] for s in seeds if s.get("kill"))
    if kills:
        print("kills: " + "  ".join(f"{k}={v}" for k, v in sorted(kills.items())))
    srcs = {r["key"]: r["channel"].split(":")[-1] for r in rows}
    for label, keyf in (("channel", lambda s: srcs.get(s.get("source_key"), "own" if s.get("method") == "own" else "?")),
                        ("method", lambda s: s.get("method") or "?")):
        tab = collections.defaultdict(collections.Counter)
        for s in seeds:
            t = tab[keyf(s)]
            t["made"] += 1
            t["v1"] += s["status"] in ("v1-pass", "v2-pass", "validated")
            t["v2"] += s["status"] in ("v2-pass", "validated")
            t["ok"] += s["status"] == "validated"
        if tab:
            print(f"yield by {label} (validated/v2/v1/made): " + "  ".join(
                f"{k}={c['ok']}/{c['v2']}/{c['v1']}/{c['made']}" for k, c in sorted(tab.items(), key=lambda kv: -kv[1]["ok"])))
    for s in sorted([s for s in seeds if s["status"] in ("validated", "v2-pass")], key=lambda s: -s.get("final", 0)):
        print(f"  {s['status']:<10} {s['id']} final={s.get('final')} {s['card'].get('title', '')[:70]}")


def cmd_try_prompts(n_rows, n_v1):
    """Test the real write and V1 stages on a few real source rows, in data-dry/ (data/ is never touched).
    Costs real tokens (a few cents to under a dollar); prints the cards, V1 verdicts, scores and cost per call."""
    os.environ["CGPIPE_DRY"] = f"try-{os.getpid()}"
    use_dry_data()
    for d in (SEEDS, RUNS):
        os.makedirs(d, exist_ok=True)
    cfg = load_config()
    rows = [r for r in read_sources() if r["status"] == "unused"]
    random.Random(7).shuffle(rows)
    pick = rows[:n_rows]
    gh = sorted({"/".join(harvest.gh_repo_of(r["url"])) for r in pick if harvest.gh_repo_of(r["url"])})
    facts = harvest.enrich([tuple(k.split("/", 1)) for k in gh], gh)
    for r in pick:
        g = harvest.gh_repo_of(r["url"])
        if g and facts.get("/".join(g).lower()):
            r["facts"] = json.dumps(facts["/".join(g).lower()])
    print(f"try-prompts: {len(pick)} rows ({len(facts)} enriched); write with {cfg['models']['write']}, V1 with {cfg['models']['v1']}")
    t0 = time.time()
    ids = {f"r{i + 1}": r for i, r in enumerate(pick)}
    out = call_claude("write", "try-write", {"batch_size": min(n_rows, cfg["batch_size"]), "quota": {"implementation": 0, "optimization": 0, "research": 0},
                                             "method_mix": cfg["method_mix"], "rows": [row_for_writer(r, k) for k, r in ids.items()],
                                             "existing_titles": []}, cfg, "")
    cards = out.get("cards", [])
    print(f"\n== write: {len(cards)} cards in {time.time() - t0:.0f}s")
    corpus = Corpus()
    for i, c in enumerate(cards):
        top = corpus.top(" ".join(str(c.get(k, "")) for k in ("title", "task", "grading", "reference", "source")), 3)
        print(f"\n[{i}] {c.get('title')}  ({c.get('class')}/{c.get('method')}/{c.get('family')})")
        for k in ("source", "task", "grading", "reference", "band", "cheat"):
            print(f"    {k}: {c.get(k, '')}")
        print("    L0 neighbours: " + "; ".join(f"{n} {x:.2f}" for x, n in top))
    for i, c in enumerate(cards[:n_v1]):
        src = ids.get(str(c.get("row", "")).strip(), {})
        seed = {"id": f"S-try-{i}", "class": c.get("class"), "family": c.get("family"), "method": c.get("method"),
                "card": {k: c.get(k, "") for k in ("title", "source", "task", "grading", "reference", "band", "cheat")},
                "source_facts": row_facts(src) if src else {}}
        t0 = time.time()
        try:
            v = call_claude("v1", f"try-v1-{i}", {"seed": compact_card(seed)}, cfg, "WebSearch,WebFetch")
        except Exception as e:  # noqa: BLE001
            print(f"\n== V1 [{i}] failed: {type(e).__name__}: {e}"); continue
        links = check_urls([f.get("url") for f in v.get("facts", [])] + [v.get("evidence_url")])
        total, gate, capped = score({k: x.get("v") for k, x in v.get("scores", {}).items()}, v.get("evidence_grade", "E0"))
        print(f"\n== V1 [{i}] {c.get('title')}: score {total}, gate {gate}, kill {v.get('kill_code') or '-'} "
              f"{v.get('kill_reason') or ''} ({time.time() - t0:.0f}s, dead links {len(links['dead'])}/{links['checked']})")
        print("    facts: " + "; ".join(f"{f.get('status')}: {f.get('claim', '')[:70]}" for f in v.get("facts", [])[:8]))
        print("    scores: " + " ".join(f"{k}={x}" for k, x in capped.items()) + f"  evidence {v.get('evidence_grade')}, lookup {v.get('lookup_verdict')}")
        print(f"    summary: {v.get('summary', '')}")
    print("\n== cost")
    for r in cost_records():
        print(f"    {r['stage']:<6} {r['key']:<14} {r['model']:<7} ${r['cost']:.4f}  {r['secs']}s  turns {r['turns']}  {'ERROR ' + str(r.get('subtype')) if r['error'] else ''}")
    shutil.rmtree(DATA, ignore_errors=True)
    print(f"(scratch folder {DATA} removed)")


def cmd_similar(text):
    for sc, name in Corpus().top(text, 8, [(s["id"], card_text(s)) for s in all_seeds()]):
        print(f"{sc:.3f}  {name}")


def cmd_add_idea(text):
    seeds = all_seeds()
    s = {"id": next_id("implementation", seeds), "batch": 0, "class": "implementation", "family": "other",
         "method": "own", "source_key": "", "status": "l0-pass", "kill": None, "created": now(),
         "card": {"title": text[:80], "source": "", "task": text, "grading": "", "reference": "", "band": "", "cheat": ""}}
    hist(s, "add-idea", "l0-pass", "own idea: skips L0")
    save_seed(s)
    print(s["id"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "warmup", "status", "watch", "dashboard", "try-prompts", "stop", "selftest", "similar",
                                    "add-idea", "requeue", "import-sources", "ladder"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-dry", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-spike", action="store_true")
    ap.add_argument("--no-smoke", action="store_true", help="skip probes (no Docker needed before V1)")
    ap.add_argument("--target", type=int, help="validated ideas to stop at; 0 = as many as the budget allows")
    ap.add_argument("--budget", type=float)
    ap.add_argument("--max-batches", type=int)
    ap.add_argument("--once", action="store_true", help="watch: print one snapshot and exit")
    ap.add_argument("--interval", type=int, default=10, help="watch: seconds between refreshes")
    ap.add_argument("--port", type=int, default=8765, help="dashboard: web server port (127.0.0.1)")
    a = ap.parse_args()
    if a.cmd == "selftest":
        cmd_selftest()
    if a.dry_run and a.cmd != "try-prompts":
        use_dry_data(keep=a.keep_dry)
    for d in (DATA, SEEDS, RUNS):
        os.makedirs(d, exist_ok=True)
    if a.cmd == "import-sources":
        cmd_import(a.rest)
    elif a.cmd == "add-idea":
        cmd_add_idea(" ".join(a.rest))
    elif a.cmd == "status":
        cmd_status()
    elif a.cmd == "watch":
        cmd_watch(a.interval, a.once)
    elif a.cmd == "dashboard":   # the web dashboard: data/dashboard.html, rewritten every --interval s, served on --port
        cmd_watch(a.interval, a.once, os.path.join(DATA, "dashboard.html"), a.port)
    elif a.cmd == "similar":
        cmd_similar(" ".join(a.rest))
    elif a.cmd == "try-prompts":
        cmd_try_prompts(int(a.rest[0]) if a.rest else 4, int(a.rest[1]) if len(a.rest) > 1 else 2)
    elif a.cmd == "ladder":            # `ladder plan` plans only (--dry-run is the pipeline's own data-dry mode)
        cmd_ladder(bool(a.rest) and a.rest[0] == "plan")
    elif a.cmd == "stop":
        open(STOPF, "w").close()
        print("stop requested; the runner exits after in-flight calls finish")
    elif a.cmd == "requeue":
        sid, stage = a.rest
        s = load_json(seed_path(sid))
        s["status"] = {"v1": "l0-pass", "v2": "v1-pass", "spike": "v2-pass"}[stage]
        s["kill"] = None
        for k in ("v2_done", "v2_missed", "attempts", "spike_parked"):
            s.pop(k, None)
        hist(s, "requeue", s["status"], "manual"); save_seed(s)
        print(f"{sid} -> {s['status']}")
    elif a.cmd in ("run", "warmup"):
        a.warmup = a.cmd == "warmup"
        if a.warmup:
            a.no_spike = True          # no model calls, so no spike token needed
        os.makedirs(CACHE, exist_ok=True)
        # one lock per data folder, and for real runs one per machine: Docker containers and volumes are shared
        locks = [LOCK] + ([] if a.dry_run else [os.path.join(CACHE, "run.lock")])
        held = []
        for path in locks:
            held.append(open(path, "w"))
            try:
                fcntl.flock(held[-1], fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                sys.exit(f"another cgpipe run is active ({path})")
        Pipeline(a).run()


if __name__ == "__main__":
    main()
