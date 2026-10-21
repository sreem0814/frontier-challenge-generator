#!/usr/bin/env bash
# VM 2 side of remote_run.sh (also shipped inside `pack` zips). Runs inside a tmux session.
# Usage: vm2-run.sh <run.conf>
# run.conf (written by remote_run.sh, bash syntax) sets:
#   TASK HASH RUNID KEYS CHEAT STOP_ON_PASS SESSION RUNDIR HARBOR_DIR HACK_FILE ENV_SRC; HARBOR_ARGS (array)
# Never prints env values. The temporary env file holds only the variables KEYS selects and is deleted on exit.
set -uo pipefail
CONF="${1:?usage: vm2-run.sh <run.conf>}"
# shellcheck disable=SC1090
source "$CONF"
export PATH="$HOME/.local/bin:$PATH"
ENV_SRC="${ENV_SRC:-$HOME/cg.env}"   # CG's keys file on the runner (pipeline/vm/setup.sh)
cd "$RUNDIR" || exit 2

ENVF="$(mktemp "$HOME/.tb-env.XXXXXX")"
chmod 600 "$ENVF"
SAMPLER_PID="" WATCHER_PID=""
redact_run_dir() {
  # Replace the exact values of the selected variables with [REDACTED] in everything under RUNDIR (count only).
  [ -s "$ENVF" ] || return 0
  ENVF="$ENVF" RUNDIR="$RUNDIR" python3 -I - <<'PY'
import os
vals = []
for line in open(os.environ["ENVF"], encoding="utf-8", errors="replace"):
    k, _, v = line.rstrip("\n").partition("=")
    v = v.strip().strip('"').strip("'")
    if len(v) >= 8:
        vals.append(v.encode())
import json
def strings(o):
    if isinstance(o, dict):
        for x in o.values(): yield from strings(x)
    elif isinstance(o, list):
        for x in o: yield from strings(x)
    elif isinstance(o, str):
        yield o
try:  # --keys codex: also redact every token-like value of ~/.codex/auth.json
    if open(os.environ["ENVF"]).read().startswith("CODEX_FORCE_AUTH_JSON"):
        vals += [v.encode() for v in strings(json.load(open(os.path.expanduser("~/.codex/auth.json")))) if len(v) >= 20]
except (OSError, ValueError):
    pass
n = 0
for root, _, files in os.walk(os.environ["RUNDIR"]):
    for f in files:
        p = os.path.join(root, f)
        try:
            if os.path.islink(p) or os.path.getsize(p) > 200_000_000:
                continue
            b = open(p, "rb").read()
        except OSError:
            continue
        o = b
        for v in vals:
            b = b.replace(v, b"[REDACTED]")
        if b != o:
            open(p, "wb").write(b)
            n += 1
print("redacted exact key values in %d file(s)" % n)
PY
}
cleanup() {
  [ -n "$SAMPLER_PID" ] && kill "$SAMPLER_PID" 2>/dev/null
  [ -n "$WATCHER_PID" ] && kill "$WATCHER_PID" 2>/dev/null
  redact_run_dir >>"$RUNDIR/run.log" 2>&1 || true
  rm -f "$ENVF"
}
trap cleanup EXIT
trap 'INTERRUPTED=1' INT TERM   # harbor gets the same signal and cleans up; we carry on to our own cleanup

# --- env file: only the variables this run needs, never ANTHROPIC_API_KEY ---
case "$KEYS" in
  claude) VARS="CLAUDE_CODE_OAUTH_TOKEN CLAUDE_FORCE_OAUTH" ;;
  openai) VARS="OPENAI_API_KEY" ;;
  qwen)   VARS="OPENROUTER_API_KEY" ;;   # the spec's second model (Qwen) through OpenRouter; terminus-2 -m openrouter/qwen/<model>
  codex)  VARS=""   # ChatGPT login: Harbor uploads ~/.codex/auth.json into the trial (CODEX_FORCE_AUTH_JSON)
          [ -s "$HOME/.codex/auth.json" ] || { echo "codex: ~/.codex/auth.json missing (run: codex login --device-auth)" >&2; echo 2 >"$RUNDIR/exit-code"; touch "$RUNDIR/DONE"; exit 2; }
          printf 'CODEX_FORCE_AUTH_JSON=1\n' >>"$ENVF" ;;
  xai)    VARS="XAI_API_KEY" ;;
  none)   VARS="" ;;
  *) echo "bad --keys $KEYS" >&2; exit 2 ;;
esac
for v in $VARS; do
  line="$(grep -E "^(export )?$v=" "$ENV_SRC" 2>/dev/null | tail -1)"
  if [ -n "$line" ] && [ -n "${line#*=}" ]; then
    printf '%s\n' "${line#export }" >>"$ENVF"
  else
    echo "key $v: missing in $ENV_SRC" >&2
    if [ "$v" = CLAUDE_CODE_OAUTH_TOKEN ] || [ "$KEYS" != claude ]; then echo 2 >"$RUNDIR/exit-code"; touch "$RUNDIR/DONE"; exit 2; fi
  fi
done
echo "env file: $(wc -l <"$ENVF") variable(s) selected for --keys $KEYS" | tee -a "$RUNDIR/run.log"

# --- CPU / memory every 10 s ---
sample() {
  local prev_total=0 prev_idle=0 total idle cpu mem load
  while :; do
    read -r _ u n s i w q sq st _ </proc/stat
    total=$((u + n + s + i + w + q + sq + st)); idle=$((i + w))
    if [ "$prev_total" -gt 0 ] && [ "$total" -gt "$prev_total" ]; then
      cpu=$(( 100 * ( (total - prev_total) - (idle - prev_idle) ) / (total - prev_total) ))
    else cpu=0; fi
    prev_total=$total; prev_idle=$idle
    mem=$(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf "%d", 100*(t-a)/t}' /proc/meminfo)
    load=$(cut -d' ' -f1 /proc/loadavg)
    printf '%s cpu=%s%% mem=%s%% load1=%s containers=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$cpu" "$mem" "$load" \
      "$(docker ps -q 2>/dev/null | wc -l)" >>"$RUNDIR/load.log"
    sleep 10
  done
}
: >"$RUNDIR/load.log"
sample & SAMPLER_PID=$!

# --- stop at the first passing trial (Harbor has no such flag, checked in `harbor run --help`, v0.24.0) ---
first_pass() {
  # a trial passed if verifier/reward.txt > 0 or any value in verifier/reward.json > 0
  find "$RUNDIR/jobs" -path '*/verifier/reward.txt' -o -path '*/verifier/reward.json' 2>/dev/null | python3 -I -c '
import sys, json
for p in sys.stdin.read().split():
    try:
        t = open(p).read().strip()
        v = [float(t)] if p.endswith(".txt") else [float(x) for x in json.loads(t).values() if isinstance(x, (int, float))]
        if any(x > 0 for x in v):
            print(p); break
    except Exception:
        pass
'
}
watch_pass() {
  local hit
  while :; do
    sleep 10
    hit="$(first_pass)"
    if [ -n "$hit" ]; then
      echo "$(date -u +%FT%TZ) first passing trial: ${hit#"$RUNDIR"/}; sending C-c to tmux session $SESSION" >>"$RUNDIR/run.log"
      tmux send-keys -t "$SESSION" C-c
      sleep 60
      tmux send-keys -t "$SESSION" C-c   # second press in case Harbor is still shutting down
      return
    fi
  done
}
if [ "${STOP_ON_PASS:-0}" = 1 ]; then
  if [ -n "${SESSION:-}" ] && command -v tmux >/dev/null; then watch_pass & WATCHER_PID=$!
  else echo "stop-on-pass needs a tmux session; running without it" | tee -a "$RUNDIR/run.log"; fi
fi

# --- run ---
EXTRA=()
[ "${CHEAT:-0}" = 1 ] && EXTRA+=(--extra-instruction-path "$HACK_FILE")
# the timer daemon: the platform arms /app/timer.sh at trial start, Harbor does not (it runs `sleep infinity`), and an
# agent with no budget signal gives up early (the requirements' timer section). For agent trials, start it with the
# trial's real budget (the task's agent timeout times --agent-timeout-multiplier) through a compose overlay.
AGENT=""; MULT=1; prev=""
for x in "${HARBOR_ARGS[@]}"; do
  [ "$prev" = "-a" ] && AGENT="$x"; [ "$prev" = "--agent-timeout-multiplier" ] && MULT="$x"; prev="$x"
done
if [ -n "$AGENT" ] && [ "$AGENT" != oracle ] && [ "$AGENT" != nop ] && [ -f "$HARBOR_DIR/environment/timer.sh" ]; then
  BUDGET="$(python3 -c 'import re,sys; t=open(sys.argv[1]).read(); m=re.search(r"(?ms)^\[agent\].*?^timeout_sec\s*=\s*(\d+)", t); print(int(int(m.group(1))*float(sys.argv[2])) if m else "")' "$HARBOR_DIR/task.toml" "$MULT" 2>/dev/null)"
  if [ -n "$BUDGET" ]; then
    printf 'services:\n  main:\n    command: ["sh", "-c", "TASK_BUDGET_SECS=%s /app/timer.sh >/dev/null 2>&1 & exec sleep infinity"]\n' "$BUDGET" >"$RUNDIR/timer-compose.yaml"
    EXTRA+=(--extra-docker-compose "$RUNDIR/timer-compose.yaml")
    echo "timer: armed with $BUDGET s (agent $AGENT, multiplier $MULT)" | tee -a "$RUNDIR/run.log"
  fi
fi
echo "$(date -u +%FT%TZ) harbor run start (task $TASK, hash $HASH, run $RUNID)" | tee -a "$RUNDIR/run.log"
env -u OPENAI_API_KEY -u XAI_API_KEY -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u CLAUDE_CODE_OAUTH_TOKEN -u CLAUDE_FORCE_OAUTH -u CODEX_FORCE_AUTH_JSON -u CODEX_AUTH_JSON_PATH \
  harbor run -p "$HARBOR_DIR" --env-file "$ENVF" -o "$RUNDIR/jobs" --job-name "$RUNID" "${EXTRA[@]}" "${HARBOR_ARGS[@]}" \
  >>"$RUNDIR/harbor.out" 2>&1
rc=$?
echo "$(date -u +%FT%TZ) harbor run end rc=$rc interrupted=${INTERRUPTED:-0}" | tee -a "$RUNDIR/run.log"
echo "$rc" >"$RUNDIR/exit-code"
[ -n "$SAMPLER_PID" ] && kill "$SAMPLER_PID" 2>/dev/null; SAMPLER_PID=""
[ -n "$WATCHER_PID" ] && kill "$WATCHER_PID" 2>/dev/null; WATCHER_PID=""
redact_run_dir >>"$RUNDIR/run.log" 2>&1 || true
touch "$RUNDIR/DONE"
exit "$rc"
