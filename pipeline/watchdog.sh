#!/usr/bin/env bash
# watchdog.sh: restart the cgpipe runner (and the web dashboard) if they died without being asked to stop.
# Run by cron every 10 minutes (README section 6); install or remove with:
#   bash pipeline/watchdog.sh install | uninstall
# Zero tokens. A run that ended on purpose (stop requested, target or budget reached, warm-up done, nothing left
# to do) is left alone; a crash or a stall is restarted, at most once every 30 minutes. Log: data/watchdog.log.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
LOG="$ROOT/data/watchdog.log"; LAST="$ROOT/data/watchdog.last"
CRON="*/10 * * * * bash $ROOT/pipeline/watchdog.sh >> $LOG 2>&1"
say() { echo "[$(date -u +%FT%TZ)] $*"; }

case "${1:-check}" in
  install)
    ( crontab -l 2>/dev/null | grep -vF "pipeline/watchdog.sh"; echo "$CRON" ) | crontab - && echo "installed: $CRON"
    exit 0 ;;
  uninstall)
    crontab -l 2>/dev/null | grep -vF "pipeline/watchdog.sh" | crontab - && echo "removed the watchdog from crontab"
    exit 0 ;;
esac

cd "$ROOT" || exit 1
# the web dashboard: restart it if it was started once (its pid file exists) and has died
if [ -f data/dashboard.pid ] && ! kill -0 "$(cat data/dashboard.pid 2>/dev/null)" 2>/dev/null; then
  say "dashboard not running: restarting"; bash pipeline/dashboard.sh start >/dev/null 2>&1
fi

# the token pool: re-read each token's limits every 30 minutes (one tiny Haiku call each) and give the pipeline role
# the token with the most headroom; trials pick theirs in remote_run.sh
if [ -s "$HOME/.config/cgpipe/tokens.json" ]; then
  python3 -I pipeline/tokens.py check --stale 30 --quiet >/dev/null 2>&1
  python3 -I pipeline/tokens.py auto --for pipeline --quiet 2>&1 | grep -v "keeping" | sed "s/^/[$(date -u +%FT%TZ)] tokens: /"
fi

# the trial ladder: start the next model trial on each free runner (config.json ladder.auto; zero tokens itself)
python3 -I pipeline/cgpipe.py ladder 2>&1 | grep -v "nothing to start\|busy$\|^\[" | sed "s/^/[$(date -u +%FT%TZ)] /"   # the ladder logs its own starts

[ -f data/state.json ] || exit 0                       # never started: nothing to watch
read -r pid ended < <(python3 -I -c "
import json; s=json.load(open('data/state.json')); print(s.get('pid') or 0, (s.get('ended') or '-').replace(' ', '_'))")
kill -0 "$pid" 2>/dev/null && exit 0                   # alive
case "$ended" in
  stop_requested|target_reached|budget_reached|warm-up_done|nothing_left_to_do) exit 0 ;;   # ended on purpose
esac
[ -f data/STOP ] && exit 0
now=$(date +%s); last=$(cat "$LAST" 2>/dev/null || echo 0)
if [ $((now - last)) -lt 1800 ]; then say "runner down ($ended) but restarted less than 30 min ago: waiting"; exit 0; fi
echo "$now" > "$LAST"
say "runner $pid is gone (ended: $ended): restarting in tmux session cgpipe"
tmux kill-session -t cgpipe 2>/dev/null
tmux new-session -d -s cgpipe -c "$ROOT" "python3 -I pipeline/cgpipe.py run 2>&1 | tee -a data/run-console.log"
