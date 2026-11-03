#!/usr/bin/env python3
"""Claude Code usage from local transcripts -> tokens per model -> API-equivalent $ proxy -> %W.

Run as: python3 -I scripts/usage.py [options]   (stdlib only)

Reads ~/.claude/projects/-work-af-cg*/ (main and worktree sessions get their own folders), including each
session's <sessionId>/subagents/agent-*.jsonl. The same assistant reply is written on several lines
(streaming), so records are de-duplicated by (message.id, requestId) and the largest value of each
token field is kept; a raw sum over-counts (about 2.5x in a 2026-10-07 check).

Subcommands / options
  (default)               report
    --session current     newest session of the current working directory's project folder
    --session <uuid>      one session
    --prompt <id>         sessions whose first user message carries a "PROMPT <id> —" header
    --since <date>        only records at or after this ISO date/time (UTC if no offset)
    --log                 append the cost row to data/usage-log.txt (or data/log.d/<id>.txt in a worktree)
    --raw                 also print the un-deduplicated sum and the ratio
    --tier 5x|20x         which calibration factor to use (default: first stored)
  calibrate --before "<pasted /usage>" [--after "<pasted /usage>"] [--tier 5x] [--other-use]
    A value starting with @ is read from that file. Giving only --before stores the start paste with its
    timestamp; giving --after (with or without --before) closes the window and computes the factor.
    The meter counts the whole account, so tokens of ALL sessions in ALL ~/.claude/projects/* folders
    between the two timestamps are used.

Prices: USD per million tokens, Claude API pricing as cached in the claude-api skill (2026-09-25),
read 2026-10-07. Cache-write multipliers (1.25x for 5 min, 2x for 1 h) are INFERRED, not read.
%W = "% of one subscription's weekly limit". Everything derived from the proxy is INFERRED.
"""
import argparse
import glob
import json
import os
import re
import sys
import datetime as dt

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
COST_LOG = os.path.join(ROOT, "data", "usage-log.txt")
LOG_D = os.path.join(ROOT, "data", "log.d")
PRICES_DATE = "2026-10-07"

# (prefix, input, output, cache_read, cache_write_5m, cache_write_1h)  USD per MTok
PRICES = [
    ("claude-fable-5", 10.0, 50.0, 0.25, 12.5, 20.0),
    ("claude-mythos-5", 10.0, 50.0, 0.25, 12.5, 20.0),
    ("claude-opus-5-5", 4.0, 20.0, 0.20, 5.0, 8.0),
    ("claude-opus-5", 5.0, 25.0, 0.50, 6.25, 10.0),
    ("claude-opus-4", 5.0, 25.0, 0.50, 6.25, 10.0),
    ("claude-sonnet-5", 2.0, 10.0, 0.20, 2.5, 4.0),
    ("claude-sonnet-4", 3.0, 15.0, 0.30, 3.75, 6.0),
    ("claude-haiku-4-5", 1.0, 5.0, 0.10, 1.25, 2.0),
]
FIELDS = ("in", "cw5", "cw1", "cr", "out")
UNKNOWN_MODELS = set()


def price_for(model):
    for p in PRICES:
        if model.startswith(p[0]):
            return p
    UNKNOWN_MODELS.add(model)
    return PRICES[5]  # sonnet-5 price as a stand-in


def cost_usd(model, t):
    _, pin, pout, pcr, pcw5, pcw1 = price_for(model)
    return (t["in"] * pin + t["out"] * pout + t["cr"] * pcr + t["cw5"] * pcw5 + t["cw1"] * pcw1) / 1e6


def parse_ts(s):
    s = s.strip().replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def text_of(msg):
    c = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(c, str):
        return c
    out = []
    for b in c or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(out)


PROMPT_RE = re.compile(r"(?mi)^\s*PROMPT\s+([0-9][0-9A-Za-z-]*)\s+[—–-]")


def scan_file(path, recs, meta):
    """recs: dict key -> record; meta: dict sessionId -> info."""
    sess_dir = None
    parts = path.split(os.sep)
    if "subagents" in parts:
        sess_dir = parts[parts.index("subagents") - 1]
    elif path.endswith(".jsonl"):
        sess_dir = os.path.basename(path)[:-6]
    user_seen = 0
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            sid = d.get("sessionId") or sess_dir
            ts = d.get("timestamp")
            info = meta.setdefault(sid, {"first": None, "last": None, "prompt": None, "effort": None,
                                         "cwd": d.get("cwd"), "files": set()})
            info["files"].add(path)
            if ts:
                try:
                    t = parse_ts(ts)
                except ValueError:
                    t = None
                if t:
                    if not info["first"] or t < info["first"]:
                        info["first"] = t
                    if not info["last"] or t > info["last"]:
                        info["last"] = t
            typ = d.get("type")
            if typ == "user" and "subagents" not in parts and user_seen < 4 and not info["prompt"]:
                user_seen += 1
                m = PROMPT_RE.search(text_of(d.get("message")))
                if m:
                    info["prompt"] = m.group(1)
            if typ != "assistant":
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            model = msg.get("model")
            if not u or not model or model.startswith("<"):
                continue
            if d.get("effort") and "subagents" not in parts:
                info["effort"] = d["effort"]
            cc = u.get("cache_creation") or {}
            cw1 = cc.get("ephemeral_1h_input_tokens")
            cw5 = cc.get("ephemeral_5m_input_tokens")
            total_cw = u.get("cache_creation_input_tokens") or 0
            if cw1 is None and cw5 is None:
                cw1, cw5 = 0, total_cw
            else:
                cw1, cw5 = cw1 or 0, cw5 or 0
            vals = {"in": u.get("input_tokens") or 0, "cw5": cw5, "cw1": cw1,
                    "cr": u.get("cache_read_input_tokens") or 0, "out": u.get("output_tokens") or 0}
            mid, rid = msg.get("id"), d.get("requestId")
            key = (mid, rid) if mid and rid else ("uuid", d.get("uuid") or (path, id(d)))
            r = recs.get(key)
            if r is None:
                recs[key] = {"model": model, "sid": sid, "ts": ts, "vals": vals, "raw_n": 1,
                             "raw": dict(vals), "sub": "subagents" in parts}
            else:
                r["raw_n"] += 1
                for k in FIELDS:
                    r["raw"][k] += vals[k]
                    if vals[k] > r["vals"][k]:
                        r["vals"][k] = vals[k]


def load(folders):
    recs, meta = {}, {}
    for f in folders:
        files = glob.glob(os.path.join(f, "*.jsonl"))
        files += glob.glob(os.path.join(f, "*", "subagents", "*.jsonl"))
        for p in sorted(files):
            scan_file(p, recs, meta)
    return recs, meta


def project_folders(pattern):
    return sorted(p for p in glob.glob(os.path.join(PROJECTS, pattern)) if os.path.isdir(p))


def cwd_folder():
    name = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
    return os.path.join(PROJECTS, name)


def totals(recs, select):
    per = {}
    raw = {}
    for r in recs.values():
        if not select(r):
            continue
        for tgt, src in ((per, r["vals"]), (raw, r["raw"])):
            t = tgt.setdefault(r["model"], dict.fromkeys(FIELDS, 0))
            for k in FIELDS:
                t[k] += src[k]
    return per, raw


def fmt_tokens(t):
    return "%d / %d / %d / %d" % (t["in"], t["cw5"] + t["cw1"], t["cr"], t["out"])


# ---------------------------------------------------------------- calibration store
CAL_START, CAL_END = "<!-- calib:start -->", "<!-- calib:end -->"


def read_cost_log():
    try:
        with open(COST_LOG, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def calib_lines():
    txt = read_cost_log()
    if CAL_START not in txt:
        return []
    body = txt.split(CAL_START, 1)[1].split(CAL_END, 1)[0]
    return [l for l in body.splitlines() if l.startswith("calib")]


def get_factor(tier=None):
    """-> (usd_per_pctW_all, usd_per_pctW_opus or None, confidence, tier) or None."""
    for l in calib_lines():
        m = re.match(r"calib\[(\S+)\] all=(\S+) opus=(\S+) conf=(\S+)", l)
        if m and (tier is None or m.group(1) == tier):
            a = None if m.group(2) == "none" else float(m.group(2))
            o = None if m.group(3) == "none" else float(m.group(3))
            return a, o, m.group(4), m.group(1)
    return None


def write_calib(lines, notes):
    txt = read_cost_log()
    block = CAL_START + "\n" + "\n".join(lines + notes) + "\n" + CAL_END
    if CAL_START in txt:
        pre = txt.split(CAL_START, 1)[0]
        post = txt.split(CAL_END, 1)[1] if CAL_END in txt else ""
        txt = pre + block + post
    else:
        txt = txt.rstrip("\n") + "\n\n## calibration\n" + block + "\n"
    with open(COST_LOG, "w", encoding="utf-8") as fh:
        fh.write(txt)


def stored_start():
    for l in calib_lines():
        m = re.match(r"calib-start at=(\S+) all=(\S+) opus=(\S+)", l)
        if m:
            return {"at": parse_ts(m.group(1)),
                    "all": None if m.group(2) == "none" else float(m.group(2)),
                    "opus": None if m.group(3) == "none" else float(m.group(3))}
    return None


def parse_usage_paste(text):
    """Weekly meters from a pasted /usage screen. Returns {"all": pct|None, "opus": pct|None, "sonnet": ...}.

    Heuristic (format not documented in the repo): a line holding a percentage whose own text or the
    previous line mentions 'week' counts as a weekly meter; 'opus' / 'sonnet' in the same context selects
    that meter, anything else ('all models') is the all-models meter. Always echo the result to the user."""
    lines = text.splitlines()
    out = {"all": None, "opus": None, "sonnet": None}
    for i, l in enumerate(lines):
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", l)
        if not m:
            continue
        ctx = (lines[i - 1] if i else "") + " " + l
        low = ctx.lower()
        if "week" not in low:
            continue
        pct = float(m.group(1))
        if "opus" in low:
            key = "opus"
        elif "sonnet" in low:
            key = "sonnet"
        else:
            key = "all"
        if out[key] is None:
            out[key] = pct
    return out


def arg_text(v):
    if v and v.startswith("@"):
        with open(v[1:], encoding="utf-8") as fh:
            return fh.read()
    return v


def fnum(x):
    return "none" if x is None else "%.6g" % x


def cmd_calibrate(a):
    now = dt.datetime.now(dt.timezone.utc)
    notes = []
    if a.before and not a.after:
        p = parse_usage_paste(arg_text(a.before))
        if p["all"] is None:
            print("Could not find a weekly all-models percentage in the paste; parsed: %s" % p)
            return 2
        lines = [l for l in calib_lines() if not l.startswith("calib-start")]
        lines.append("calib-start at=%s all=%s opus=%s" % (now.isoformat(), fnum(p["all"]), fnum(p["opus"])))
        write_calib(lines, [])
        print("Start stored %s: weekly all-models %.1f%%, Opus %s, Sonnet %s" % (
            now.isoformat(timespec="seconds"), p["all"], p["opus"], p["sonnet"]))
        print("Do not use this account elsewhere until the end paste.")
        return 0
    if not a.after:
        print("calibrate needs --before and/or --after")
        return 2
    if a.before:
        pb = parse_usage_paste(arg_text(a.before))
        t0 = parse_ts(a.before_time) if a.before_time else None
        if t0 is None:
            st = stored_start()
            t0 = st["at"] if st else None
        if t0 is None:
            print("No start timestamp: pass --before-time <ISO> or run calibrate --before first")
            return 2
    else:
        st = stored_start()
        if not st:
            print("No stored start paste; run calibrate --before first")
            return 2
        t0, pb = st["at"], {"all": st["all"], "opus": st["opus"]}
    pa = parse_usage_paste(arg_text(a.after))
    t1 = now
    if pa["all"] is None or pb.get("all") is None:
        print("Could not parse weekly all-models percentages: before=%s after=%s" % (pb, pa))
        return 2
    recs, meta = load(project_folders("*"))
    win = lambda r: bool(r["ts"]) and t0 <= parse_ts(r["ts"]) <= t1
    per, _ = totals(recs, win)
    proxy_all = sum(cost_usd(m, t) for m, t in per.items())
    proxy_opus = sum(cost_usd(m, t) for m, t in per.items() if "opus" in m)
    d_all = pa["all"] - pb["all"]
    d_opus = None
    if pa["opus"] is not None and pb.get("opus") is not None:
        d_opus = pa["opus"] - pb["opus"]
    f_all = proxy_all / d_all if d_all > 0 and proxy_all > 0 else None
    f_opus = proxy_opus / d_opus if d_opus and d_opus > 0 and proxy_opus > 0 else None
    low = []
    if d_all < 2:
        low.append("meter moved %.1f%% (<2%%)" % d_all)
    if a.other_use:
        low.append("other use reported in the window")
    if f_all is None:
        low.append("no positive meter change")
    conf = "LOW-CONFIDENCE" if low else "ok"
    tier = a.tier or "unspecified"
    lines = [l for l in calib_lines() if not l.startswith("calib-start") and not l.startswith("calib[%s]" % tier)]
    lines.append("calib[%s] all=%s opus=%s conf=%s" % (tier, fnum(f_all), fnum(f_opus), conf.replace(" ", "_")))
    notes = ["",
             "Last calibration: tier %s, window %s -> %s UTC, meter all-models %.1f%% -> %.1f%% (+%.1f), "
             "Opus meter %s -> %s, proxy $%.2f over the window (%s; Opus-only $%.2f). Prices as of %s (INFERRED proxy). %s%s" % (
                 tier, t0.isoformat(timespec="seconds"), t1.isoformat(timespec="seconds"), pb["all"], pa["all"], d_all,
                 pb.get("opus"), pa["opus"], proxy_all, "sessions in ALL ~/.claude/projects folders", proxy_opus,
                 PRICES_DATE, conf, (" (" + "; ".join(low) + ")") if low else ""),
             "Units: usd per 1 %W. Rows: `calib[tier] all=<usd per 1%W, all-models meter> opus=<usd per 1%W, Opus meter or none> conf=<..>`."]
    write_calib(lines, notes)
    print("\n".join(notes[1:2]))
    print("Factor all-models: %s USD per 1 %%W; Opus meter: %s; confidence: %s" % (fnum(f_all), fnum(f_opus), conf))
    if UNKNOWN_MODELS:
        print("Unknown models priced as sonnet-5: %s" % sorted(UNKNOWN_MODELS))
    return 0


# ---------------------------------------------------------------- report
def is_worktree():
    return os.path.isfile(os.path.join(ROOT, ".git"))


def append_row(row, prompt_id):
    if is_worktree():
        os.makedirs(LOG_D, exist_ok=True)
        p = os.path.join(LOG_D, "%s.md" % (prompt_id or "unknown"))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("\n### cost-log row (merge into data/usage-log.txt)\n%s\n" % row)
        return p
    txt = read_cost_log()
    lines = txt.splitlines()
    idx = next((i for i, l in enumerate(lines) if l.lower().startswith("| date |")), None)
    if idx is None:
        print("usage-log.txt has no table header '| date |'; row not written:\n" + row)
        return None
    j = idx + 1
    while j < len(lines) and lines[j].startswith("|"):
        j += 1
    lines.insert(j, row)
    with open(COST_LOG, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return COST_LOG


def cmd_report(a):
    since = parse_ts(a.since) if a.since else None
    folders = project_folders("-work-af-cg*")
    recs, meta = load(folders)
    sel_sids = None
    label = "all -work-af-cg* sessions"
    if a.session == "current":
        cf = cwd_folder()
        cands = [(info["last"], sid) for sid, info in meta.items()
                 if info["last"] and any(f.startswith(cf + os.sep) for f in info["files"])
                 and not any(os.sep + "subagents" + os.sep in f for f in info["files"] if False)]
        main_sess = []
        for sid, info in meta.items():
            if any(os.path.dirname(f) == cf for f in info["files"]) and info["last"]:
                main_sess.append((info["last"], sid))
        if not main_sess:
            print("No sessions in %s" % cf)
            return 2
        sel_sids = {max(main_sess)[1]}
        label = "current session %s" % next(iter(sel_sids))
    elif a.session:
        sel_sids = {a.session}
        label = "session %s" % a.session
    elif a.prompt:
        sel_sids = {sid for sid, info in meta.items() if info["prompt"] == a.prompt}
        label = "prompt %s (%d session(s))" % (a.prompt, len(sel_sids))
        if not sel_sids:
            print("No session with a 'PROMPT %s —' header found" % a.prompt)
            return 2

    def select(r):
        if sel_sids is not None and r["sid"] not in sel_sids:
            return False
        if since and (not r["ts"] or parse_ts(r["ts"]) < since):
            return False
        return True

    per, raw = totals(recs, select)
    if not per:
        print("No usage records for %s" % label)
        return 1
    fac = get_factor(a.tier)
    usd_total = 0.0
    print("Usage for %s (de-duplicated by message.id + requestId)" % label)
    print("%-22s %12s %12s %14s %10s %9s" % ("model", "input", "cache-write", "cache-read", "output", "proxy $"))
    opus_usd = 0.0
    for m in sorted(per):
        t = per[m]
        c = cost_usd(m, t)
        usd_total += c
        if "opus" in m:
            opus_usd += c
        print("%-22s %12d %12d %14d %10d %9.2f" % (m, t["in"], t["cw5"] + t["cw1"], t["cr"], t["out"], c))
    print("API-equivalent proxy total: $%.2f (prices %s, INFERRED)" % (usd_total, PRICES_DATE))
    pctw = None
    if fac and fac[0]:
        pctw = usd_total / fac[0]
        print("%%W (all-models meter, tier %s, %s): %.2f" % (fac[3], fac[2], pctw))
        if fac[1] and opus_usd:
            print("%%W (Opus meter): %.2f" % (opus_usd / fac[1]))
    else:
        print("%W: no calibration factor yet (run calibrate); proxy dollars only")
    if a.raw:
        rn = sum(sum(t[k] for k in FIELDS) for t in raw.values())
        dn = sum(sum(t[k] for k in FIELDS) for t in per.values())
        print("raw sum %d tokens vs de-duplicated %d (x%.2f over-count)" % (rn, dn, rn / dn if dn else 0))
    if UNKNOWN_MODELS:
        print("WARNING unknown models priced as sonnet-5: %s" % sorted(UNKNOWN_MODELS))
    sess_meta = [meta[s] for s in (sel_sids or meta) if s in meta]
    # wall time from the selected usage records (honours --since), not the whole session's span
    tss = [parse_ts(r["ts"]) for r in recs.values() if r["ts"] and select(r)]
    wall = (max(tss) - min(tss)) if tss else None
    if wall:
        print("Wall time (first to last record): %s" % str(wall).split(".")[0])
    if a.log:
        prompts = sorted({i["prompt"] for i in sess_meta if i["prompt"]})
        efforts = sorted({i["effort"] for i in sess_meta if i["effort"]})
        pid = a.prompt or (prompts[0] if prompts else "")
        if not pid and is_worktree():
            pid = os.path.basename(ROOT)  # .claude/worktrees/<prompt-id>, named per CLAUDE.md § Parallel sessions
        row = "| %s | %s | %s | %s | %s | $%.2f | | %s | | %s | | | usage.py (INFERRED %%W) |" % (
            dt.datetime.now().strftime("%Y-%m-%d"), pid or "?", ", ".join(sorted(s[:8] for s in (sel_sids or []))) or "all",
            "/".join(sorted(per)) + (" · " + "/".join(efforts) if efforts else ""),
            "; ".join("%s %s" % (m, fmt_tokens(per[m])) for m in sorted(per)), usd_total,
            ("%.2f" % pctw) if pctw is not None else "n/a",
            str(wall).split(".")[0] if wall else "")
        dest = append_row(row, pid)
        print("Logged row to %s" % dest)
    return 0


def main(argv):
    if argv and argv[0] == "calibrate":
        ap = argparse.ArgumentParser(prog="usage.py calibrate")
        ap.add_argument("--before")
        ap.add_argument("--after")
        ap.add_argument("--before-time", help="ISO timestamp of the before paste (default: stored start)")
        ap.add_argument("--tier", help="plan tier of this subscription, e.g. 5x or 20x")
        ap.add_argument("--other-use", action="store_true", help="other use of the account reported in the window")
        return cmd_calibrate(ap.parse_args(argv[1:]))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session")
    ap.add_argument("--prompt")
    ap.add_argument("--since")
    ap.add_argument("--log", action="store_true")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--tier")
    return cmd_report(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
