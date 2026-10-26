#!/usr/bin/env bash
# dashboard.sh: manage the cgpipe web dashboard (README section 5).
#
#   bash pipeline/dashboard.sh start [--port 8765] [--interval 10]   start in the background
#   bash pipeline/dashboard.sh stop                                   stop it (the pipeline is not affected)
#   bash pipeline/dashboard.sh restart [--port N] [--interval N]      stop, then start
#   bash pipeline/dashboard.sh status                                 running? URL, page age, last log lines
#   bash pipeline/dashboard.sh logs                                   follow its log (Ctrl-C to quit)
#
# The dashboard rewrites data/dashboard.html every --interval seconds and serves it on http://127.0.0.1:PORT/
# (localhost only). It only reads pipeline state, so it can run whether or not the pipeline is running.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PIDF="$ROOT/data/dashboard.pid"
LOGF="$ROOT/data/dashboard.log"
PAGE="$ROOT/data/dashboard.html"
PORT=8765
INTERVAL=10

running_pid() {   # prints the PID if the recorded process is alive and is our dashboard
  [ -f "$PIDF" ] || return 1
  local pid; pid="$(cat "$PIDF" 2>/dev/null)"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && grep -q "cgpipe.py" "/proc/$pid/cmdline" 2>/dev/null && echo "$pid"
}

port_of() { tr '\0' ' ' <"/proc/$1/cmdline" 2>/dev/null | grep -oE -- '--port [0-9]+' | awk '{print $2}'; }

start() {
  if pid="$(running_pid)"; then
    echo "already running (pid $pid) at http://127.0.0.1:$(port_of "$pid")/"; return 0
  fi
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
    echo "port $PORT is already in use by another program: choose another with --port"; return 1
  fi
  mkdir -p "$ROOT/data"
  cd "$ROOT" || return 1
  setsid nohup python3 -I pipeline/cgpipe.py dashboard --port "$PORT" --interval "$INTERVAL" >>"$LOGF" 2>&1 </dev/null &
  echo $! >"$PIDF"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.5
    if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
      echo "started (pid $(cat "$PIDF")): http://127.0.0.1:$PORT/  (refreshes every ${INTERVAL}s)"; return 0
    fi
  done
  echo "did not come up; last log lines:"; tail -5 "$LOGF"; return 1
}

stop() {
  if pid="$(running_pid)"; then
    kill "$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.3; done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
    echo "stopped (pid $pid)"
  else
    echo "not running"
  fi
  rm -f "$PIDF"
}

status() {
  if pid="$(running_pid)"; then
    p="$(port_of "$pid")"
    echo "running: pid $pid, http://127.0.0.1:${p:-?}/"
    if [ -f "$PAGE" ]; then echo "page updated $(( $(date +%s) - $(stat -c %Y "$PAGE") ))s ago: $PAGE"; fi
    if (exec 3<>"/dev/tcp/127.0.0.1/${p:-0}") 2>/dev/null; then echo "server: answering"; else echo "server: NOT answering"; fi
  else
    echo "not running (start with: bash pipeline/dashboard.sh start)"
    rm -f "$PIDF"
  fi
  [ -f "$LOGF" ] && { echo "log (last 3 lines):"; tail -3 "$LOGF" | sed 's/^/  /'; }
  return 0
}

cmd="${1:-status}"; shift || true
while [ $# -gt 0 ]; do case "$1" in
  --port) PORT="$2"; shift 2 ;; --interval) INTERVAL="$2"; shift 2 ;;
  *) echo "unknown option $1"; exit 2 ;; esac; done
case "$cmd" in
  start) start ;; stop) stop ;; restart) stop; start ;; status) status ;;
  logs) touch "$LOGF"; tail -f "$LOGF" ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
