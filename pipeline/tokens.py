#!/usr/bin/env python3
"""tokens.py: a pool of named Claude OAuth tokens that CG's three roles can use interchangeably.

Roles: pipeline (VM 1: spike containers and the runner's own claude calls), vm2 and vm3 (each runner's ~/cg.env, used
by model trials). The pool lives in ~/.config/cgpipe/ (mode 600), never in this folder; token values are never
printed, logged or passed on a command line.

  python3 -I pipeline/tokens.py add <name> [--plan "max 5x"]   paste the token at a hidden prompt (your own terminal)
  python3 -I pipeline/tokens.py remove <name>
  python3 -I pipeline/tokens.py rename <old> <new> [--plan P]
  python3 -I pipeline/tokens.py adopt <name> --from pipeline|vm2|vm3 [--plan P]   take a token already installed there
  python3 -I pipeline/tokens.py list                              names, plans, roles, last limits (no token values)
  python3 -I pipeline/tokens.py check [name ...] [--stale MIN]    one tiny Haiku call per token reads both limits
  python3 -I pipeline/tokens.py use <name> --for pipeline|vm2|vm3
  python3 -I pipeline/tokens.py auto [--for ROLE ...] [--quiet]   give each role the token with the most headroom
  python3 -I pipeline/tokens.py reserve <name> [--off]          keep a token out of `auto` (e.g. VM 1's own login account)
  python3 -I pipeline/tokens.py ready <role>                      exit 1 if the role's token is at a limit (for scripts)

`auto` re-checks readings older than 20 minutes, skips tokens at 90% or more of either limit, and prefers giving each
role its own token. The watchdog runs `check --stale 30` and `auto --for pipeline`; remote_run.sh runs
`auto --for <runner>` before each model trial. Readings go to ~/.config/cgpipe/token-usage.json for the dashboard.
"""
import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import time

CONF = os.path.expanduser("~/.config/cgpipe")
POOL = os.path.join(CONF, "tokens.json")
USAGE = os.path.join(CONF, "token-usage.json")
PIPE_ENV = os.path.join(CONF, "env")
IMAGE = "cgpipe-spike:1"
ROLES = ("pipeline", "vm2", "vm3")
TOKEN_RE = re.compile(r"^sk-ant-[A-Za-z0-9_-]{60,200}$")
FULL = 0.9


def load(p, default):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(p, obj):
    os.makedirs(CONF, mode=0o700, exist_ok=True)
    tmp = p + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1)
    os.replace(tmp, p)


def fp(token):
    return hashlib.sha256(token.encode()).hexdigest()[:8]


def pool():
    return load(POOL, {"tokens": {}, "roles": {}})


def ssh(host, script, stdin="", timeout=40):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, script],
                          input=stdin, capture_output=True, text=True, timeout=timeout)


def installed(role):
    """The token currently installed for a role (read, never shown)."""
    if role == "pipeline":
        text = open(PIPE_ENV).read() if os.path.exists(PIPE_ENV) else ""
    else:
        text = ssh(role, "cat ~/cg.env 2>/dev/null").stdout
    m = re.search(r"^CLAUDE_CODE_OAUTH_TOKEN=(\S+)", text, re.M)
    return m.group(1) if m else ""


def install(role, token):
    """Put the token in place for a role, keeping the file's other lines; the value travels on stdin only."""
    if role == "pipeline":
        old = open(PIPE_ENV).read().splitlines() if os.path.exists(PIPE_ENV) else []
        lines = [l for l in old if not l.startswith("CLAUDE_CODE_OAUTH_TOKEN=")] + [f"CLAUDE_CODE_OAUTH_TOKEN={token}"]
        fd = os.open(PIPE_ENV + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(PIPE_ENV + ".tmp", PIPE_ENV)
        return True
    script = ("python3 -c 'import os,sys\n"
              "p=os.path.expanduser(\"~/cg.env\"); t=sys.stdin.read().strip()\n"
              "old=open(p).read().splitlines() if os.path.exists(p) else [\"# CG trial keys (Claude Code agent). Stays on this runner.\"]\n"
              "keep=[l for l in old if not l.startswith(\"CLAUDE_CODE_OAUTH_TOKEN=\")]\n"
              "keep+=[] if any(l.startswith(\"CLAUDE_FORCE_OAUTH=\") for l in keep) else [\"CLAUDE_FORCE_OAUTH=1\"]\n"
              "fd=os.open(p+\".tmp\",os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); f=os.fdopen(fd,\"w\")\n"
              "f.write(\"\\n\".join(keep+[\"CLAUDE_CODE_OAUTH_TOKEN=\"+t])+\"\\n\"); f.close(); os.replace(p+\".tmp\",p); print(\"ok\")'")
    return ssh(role, script, stdin=token + "\n").stdout.strip() == "ok"


def check_one(token):
    """One tiny Haiku call in the spike container; returns both windows from its rate_limit_event."""
    env = dict(os.environ, CLAUDE_CODE_OAUTH_TOKEN=token)
    try:
        p = subprocess.run(["docker", "run", "--rm", "-i", "-e", "CLAUDE_CODE_OAUTH_TOKEN", IMAGE, "claude", "-p",
                            "--model", "haiku", "--output-format", "stream-json", "--verbose", "--max-turns", "1",
                            "--no-session-persistence", "--tools", ""],
                           input="Reply with the single word ok", capture_output=True, text=True, timeout=180, env=env)
    except subprocess.TimeoutExpired:
        return {"error": "timed out", "checked": time.time()}
    out = {"checked": time.time()}
    for line in p.stdout.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "rate_limit_event":
            info = e.get("rate_limit_info") or {}
            out["status"] = info.get("status")
            for win, w in (info.get("unifiedWindows") or {}).items():
                out[win] = [w.get("utilization"), w.get("resetsAt")]
    if "five_hour" not in out and "seven_day" not in out:
        tail = (p.stderr or p.stdout or "").strip().splitlines()[-1:] or [""]
        out["error"] = ("no limit reading: " + tail[0])[:160]
        out["error"] = out["error"].replace(token, "<token>")
    return out


def headroom(u):
    """0 = full, 1 = empty; a reading whose window has reset counts as empty."""
    now = time.time()
    worst = 0.0
    for win in ("five_hour", "seven_day"):
        w = u.get(win)
        if w and w[0] is not None and (not w[1] or w[1] > now):
            worst = max(worst, float(w[0]))
    return 0.0 if u.get("error") and not (u.get("five_hour") or u.get("seven_day")) else 1.0 - worst


def fmt(w):
    if not w or w[0] is None:
        return "-"
    when = dt.datetime.fromtimestamp(w[1], dt.timezone.utc).strftime("%a %H:%MZ") if w[1] else "?"
    return f"{w[0]:.0%} (resets {when})" if not w[1] or w[1] > time.time() else f"reset at {when}"


def cmd_add(a):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,30}", a.name):
        sys.exit("name: lowercase letters, digits, - and _ (up to 31 characters)")
    tok = ("".join(sys.stdin.read().split()) if a.stdin            # --stdin joins a token wrapped across lines
           else getpass.getpass(f"Paste the OAuth token for {a.name} (hidden), then Enter: ").strip())
    if not TOKEN_RE.match(tok) or tok.count("sk-ant-") != 1:
        sys.exit("That doesn't look like one token (it starts with sk-ant- and is about 100 characters). Nothing saved.")
    P = pool()
    dup = next((n for n, t in P["tokens"].items() if t["token"] == tok and n != a.name), None)
    if dup:
        sys.exit(f"That token is already in the pool as {dup} (use `rename {dup} {a.name}`). Nothing saved.")
    P["tokens"][a.name] = {"plan": a.plan or "", "token": tok, "added": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    save(POOL, P)
    print(f"Saved {a.name} (fingerprint {fp(tok)}). Checking its limits...")
    U = load(USAGE, {})
    U[a.name] = check_one(tok)
    save(USAGE, U)
    cmd_list(a)


def cmd_adopt(a):
    tok = installed(a.source)
    if not tok:
        sys.exit(f"No token is installed for {a.source}.")
    P = pool()
    for n, t in P["tokens"].items():
        if t["token"] == tok:
            sys.exit(f"The token installed for {a.source} is already in the pool as {n}.")
    P["tokens"][a.name] = {"plan": a.plan or "", "token": tok, "added": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    P["roles"][a.source] = a.name
    save(POOL, P)
    print(f"Adopted the token installed for {a.source} as {a.name} (fingerprint {fp(tok)}).")


def cmd_remove(a):
    P = pool()
    if a.name not in P["tokens"]:
        sys.exit(f"No token named {a.name}.")
    del P["tokens"][a.name]
    used = [r for r, n in P["roles"].items() if n == a.name]
    for r in used:
        del P["roles"][r]
    save(POOL, P)
    U = load(USAGE, {})
    U.pop(a.name, None)
    save(USAGE, U)
    print(f"Removed {a.name}." + (f" It was in use for {', '.join(used)}: run `tokens.py auto` to give those roles another token"
                                  " (the old token stays installed there until then)." if used else ""))


def cmd_rename(a):
    P, U = pool(), load(USAGE, {})
    if a.old not in P["tokens"] or a.new in P["tokens"]:
        sys.exit(f"Need an existing {a.old} and an unused {a.new}.")
    P["tokens"][a.new] = P["tokens"].pop(a.old)
    if a.plan:
        P["tokens"][a.new]["plan"] = a.plan
    P["roles"] = {r: (a.new if n == a.old else n) for r, n in P["roles"].items()}
    if a.old in U:
        U[a.new] = U.pop(a.old)
    save(POOL, P)
    save(USAGE, U)
    print(f"Renamed {a.old} to {a.new}.")


def cmd_list(a):
    P, U = pool(), load(USAGE, {})
    inst = {}
    for role in ROLES:
        try:
            t = installed(role)
        except (OSError, subprocess.TimeoutExpired):
            t = ""
        inst[role] = next((n for n, x in P["tokens"].items() if x["token"] == t), "(not in pool)" if t else "(none)")
    print(f"{'name':<12} {'plan':<14} {'fingerprint':<11} {'used by':<18} {'session (5 h)':<26} {'weekly':<26} checked")
    for n, t in sorted(P["tokens"].items()):
        u = U.get(n, {})
        by = (",".join(r for r in ROLES if inst[r] == n) or "-") + (" (reserved)" if t.get("reserved") else "")
        ago = f"{(time.time() - u['checked']) / 60:.0f} min ago" if u.get("checked") else "never"
        print(f"{n:<12} {t.get('plan', ''):<14} {fp(t['token']):<11} {by:<18} {fmt(u.get('five_hour')):<26} {fmt(u.get('seven_day')):<26} {ago}"
              + (f"  [{u['error']}]" if u.get("error") else ""))
    for r in ROLES:
        if inst[r].startswith("("):
            print(f"{r}: {inst[r]}")


def cmd_check(a):
    P, U = pool(), load(USAGE, {})
    names = a.names or sorted(P["tokens"])
    for n in names:
        if n not in P["tokens"]:
            print(f"{n}: not in the pool")
            continue
        if a.stale and time.time() - U.get(n, {}).get("checked", 0) < a.stale * 60:
            continue
        U[n] = check_one(P["tokens"][n]["token"])
        save(USAGE, U)
        if not a.quiet:
            print(f"{n}: session {fmt(U[n].get('five_hour'))}, weekly {fmt(U[n].get('seven_day'))}"
                  + (f" [{U[n]['error']}]" if U[n].get("error") else ""))


def cmd_use(a):
    P = pool()
    if a.name not in P["tokens"]:
        sys.exit(f"No token named {a.name}.")
    for role in a.roles:
        ok = install(role, P["tokens"][a.name]["token"])
        P["roles"][role] = a.name
        print(f"{role}: {'now uses' if ok else 'FAILED to install'} {a.name}")
    save(POOL, P)


def cmd_auto(a):
    P, U = pool(), load(USAGE, {})
    if not P["tokens"]:
        if not a.quiet:
            print("The pool is empty: add tokens with `tokens.py add <name>`.")
        return
    for n, t in P["tokens"].items():          # refresh readings older than 20 minutes
        if time.time() - U.get(n, {}).get("checked", 0) > 1200:
            U[n] = check_one(t["token"])
            save(USAGE, U)
    roles = a.roles or list(ROLES)
    taken = {P["roles"].get(r) for r in ROLES if r not in roles}
    for role in roles:
        cur = P["roles"].get(role)
        ranked = sorted((n for n in P["tokens"] if not P["tokens"][n].get("reserved")),
                        key=lambda n: (n in taken, -headroom(U.get(n, {}))))
        best = next((n for n in ranked if headroom(U.get(n, {})) > 1 - FULL), None)
        if best is None:
            print(f"{role}: every token is at {FULL:.0%} or more of a limit; keeping {cur or 'what is installed'}")
            continue
        if cur in P["tokens"] and not P["tokens"][cur].get("reserved") and cur not in taken and headroom(U.get(cur, {})) > 1 - FULL and headroom(U.get(cur, {})) >= headroom(U.get(best, {})) - 0.15:
            best = cur                         # don't switch for a small gain
        if best != cur or installed(role) != P["tokens"][best]["token"]:
            ok = install(role, P["tokens"][best]["token"])
            if ok:
                P["roles"][role] = best
            print(f"{role}: {'switched to' if ok else 'FAILED to install'} {best} (headroom {headroom(U.get(best, {})):.0%})")
        elif not a.quiet:
            print(f"{role}: keeps {best} (headroom {headroom(U.get(best, {})):.0%})")
        taken.add(best)
    save(POOL, P)


def cmd_reserve(a):
    P = pool()
    if a.name not in P["tokens"]:
        sys.exit(f"No token named {a.name}.")
    P["tokens"][a.name]["reserved"] = not a.off
    save(POOL, P)
    print(f"{a.name}: {'reserved (auto never assigns it)' if not a.off else 'available to auto'}")


def cmd_ready(a):
    P, U = pool(), load(USAGE, {})
    n = P["roles"].get(a.role)
    if not n or n not in P["tokens"]:
        return
    u = U.get(n, {})
    for win in ("five_hour", "seven_day"):
        w = u.get(win)
        if w and w[0] is not None and w[0] >= 0.95 and (not w[1] or w[1] > time.time()):
            print(f"{a.role} uses {n}, whose {'session' if win == 'five_hour' else 'weekly'} limit is at {w[0]:.0%} until {fmt(w).split('resets ')[-1].rstrip(')')}")
            sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("add"); x.add_argument("name"); x.add_argument("--plan", default="")
    x.add_argument("--stdin", action="store_true", help="read the token from stdin (lines are joined)"); x.set_defaults(f=cmd_add)
    x = sp.add_parser("adopt"); x.add_argument("name"); x.add_argument("--from", dest="source", choices=ROLES, required=True)
    x.add_argument("--plan", default=""); x.set_defaults(f=cmd_adopt)
    x = sp.add_parser("remove"); x.add_argument("name"); x.set_defaults(f=cmd_remove)
    x = sp.add_parser("rename"); x.add_argument("old"); x.add_argument("new"); x.add_argument("--plan", default="")
    x.set_defaults(f=cmd_rename)
    x = sp.add_parser("list"); x.set_defaults(f=cmd_list)
    x = sp.add_parser("check"); x.add_argument("names", nargs="*"); x.add_argument("--stale", type=float, default=0)
    x.add_argument("--quiet", action="store_true"); x.set_defaults(f=cmd_check)
    x = sp.add_parser("use"); x.add_argument("name"); x.add_argument("--for", dest="roles", nargs="+", choices=ROLES, required=True)
    x.set_defaults(f=cmd_use)
    x = sp.add_parser("auto"); x.add_argument("--for", dest="roles", nargs="+", choices=ROLES)
    x.add_argument("--quiet", action="store_true"); x.set_defaults(f=cmd_auto)
    x = sp.add_parser("reserve"); x.add_argument("name"); x.add_argument("--off", action="store_true"); x.set_defaults(f=cmd_reserve)
    x = sp.add_parser("ready"); x.add_argument("role", choices=ROLES); x.set_defaults(f=cmd_ready)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
