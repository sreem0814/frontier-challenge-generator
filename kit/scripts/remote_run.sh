#!/usr/bin/env bash
# remote_run.sh: run Harbor trials of tasks/<task>/harbor/ on a trial runner (vm2 or vm3, see CG_RUNNER_HOST), from VM 1.
#
#   remote_run.sh check
#   remote_run.sh run <task|path> --keys claude|openai|qwen|codex|xai|none [--label L] [--cheat] [--stop-on-pass]
#                      [--wait-timeout HOURS] [--detach] [--local] -- <harbor run args>
#   remote_run.sh pull <task> <runid> [--local]        fetch a finished (or --detach) run
#   remote_run.sh stop <task> <runid> [--local]        send C-c to the run's tmux session
#   remote_run.sh status [--local]
#   remote_run.sh prepull <image...> [--local]
#   remote_run.sh pack <task> --keys K [--label L] [--cheat] -- <harbor args>     manual fallback -> ~/cg-outbox/
#   remote_run.sh --unpack <zip> [--task T]            from ~/cg-inbox into tasks/<T>/runs/
#
# Only tasks/<task>/harbor/ ever leaves VM 1, and only after the leak guard passes. Env values are never printed;
# `--keys` selects which variables of CG's keys file on the runner, ~/cg.env, a run sees (claude -> CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_FORCE_OAUTH;
# openai -> OPENAI_API_KEY (the GPT stand-in); qwen -> OPENROUTER_API_KEY (the second-model check: -a terminus-2
# -m openrouter/qwen/<model>, label qwen; terminus-2 calls the model from the runner, so no agent host is opened); codex -> CODEX_FORCE_AUTH_JSON=1, i.e. the target's ~/.codex/auth.json (ChatGPT login); xai -> XAI_API_KEY; none -> nothing). `--local` runs the same flow on VM 1's Docker
# (fallback only, when the user chooses it). Harbor 0.24.0 layout: <jobs>/<job>/<trial>/{result.json,verifier/reward.txt|json}.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF_DIR/.." && pwd)"
DENYLIST="$SELF_DIR/leak-denylist.txt"
VM2_SCRIPT="$SELF_DIR/vm2-run.sh"
HOST="${CG_RUNNER_HOST:-vm2}"   # a trial runner: vm2 or vm3 (pipeline/vm/, README section 10)
LOCAL=0
REMOTE_BASE='cg-runs'   # relative to the target's home (rsync does not expand $HOME)
CLONE_TB="${TB_CLONES:-$HOME/tb-clones}/terminal-bench"
SSH_OPTS=(-o ConnectTimeout=20 -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=6)

die() { echo "remote_run.sh: $*" >&2; exit 1; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

# ---------- transport (ssh with one retry on connection failure, or local) ----------
T() { # T <bash script text> [args...]: run on the target, script via stdin
  local script="$1"; shift
  if [ "$LOCAL" = 1 ]; then printf '%s\n' "$script" | bash -s -- "$@"; return; fi
  local rc=0
  printf '%s\n' "$script" | ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$@" || rc=$?
  if [ "$rc" = 255 ]; then   # connection failure: the first call after idle can time out while Tailscale re-routes
    log "ssh to $HOST failed (255); retrying once" >&2; sleep 5
    printf '%s\n' "$script" | ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$@" && return 0 || rc=$?
  fi
  return "$rc"
}
rs_to() {   # rs_to <local dir/> <target path> [rsync opts]
  local src="$1" dst="$2"; shift 2
  if [ "$LOCAL" = 1 ]; then mkdir -p "$HOME/$dst"; rsync -a "$@" "$src" "$HOME/$dst/"; return; fi
  T "mkdir -p $dst"
  rsync -a "$@" -e "ssh ${SSH_OPTS[*]}" "$src" "$HOST:$dst/" || { sleep 5; rsync -a "$@" -e "ssh ${SSH_OPTS[*]}" "$src" "$HOST:$dst/"; }
}
rs_from() { # rs_from <target dir> <local dir>
  local src="$1" dst="$2"; mkdir -p "$dst"
  if [ "$LOCAL" = 1 ]; then rsync -a "$HOME/$src/" "$dst/"; return; fi
  rsync -a -e "ssh ${SSH_OPTS[*]}" "$HOST:$src/" "$dst/" || { sleep 5; rsync -a -e "ssh ${SSH_OPTS[*]}" "$HOST:$src/" "$dst/"; }
}

# ---------- guards ----------
resolve_harbor_dir() { # accepts <task> or a path; prints the validated absolute path or dies
  local arg="$1" cand
  if [[ "$arg" == */* ]]; then cand="$arg"; else
    [[ "$arg" =~ ^[A-Za-z0-9._-]+$ ]] || die "bad task name '$arg'"
    cand="$ROOT/tasks/$arg/harbor"
  fi
  [ -L "${cand%/}" ] && die "refused: $cand is a symlink"
  [ -d "$cand" ] || die "refused: $cand is not a directory"
  cand="$(cd "$cand" && pwd -P)"
  local real_root; real_root="$(cd "$ROOT" && pwd -P)"
  [[ "$cand" =~ ^"$real_root"/tasks/[A-Za-z0-9._-]+/harbor$ ]] || die "refused: $cand is not tasks/<task>/harbor/ under $real_root"
  echo "$cand"
}
leak_guard() { # leak_guard <harbor dir>: no spec/guideline/proposal phrases, no symlinks leaving the folder
  local d="$1" pats hits
  [ -f "$DENYLIST" ] || die "missing $DENYLIST"
  pats="$(mktemp)"; grep -h -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$DENYLIST" \
    $( [ -f "$HOME/.config/cgpipe/denylist.txt" ] && echo "$HOME/.config/cgpipe/denylist.txt" ) >"$pats"
  hits="$(grep -r -I -i -l -E -f "$pats" "$d" 2>/dev/null || true)"; rm -f "$pats"
  if [ -n "$hits" ]; then
    echo "$hits" | sed "s#^$d/#  #" >&2
    die "refused: deny-list phrase found in the file(s) above (matching text not shown). Remove it from harbor/ or fix the deny-list."
  fi
  while IFS= read -r l; do
    t="$(readlink -f "$l")"; [[ "$t" == "$d"/* ]] || die "refused: symlink $l points outside harbor/"
  done < <(find "$d" -type l)
  log "leak guard passed ($(find "$d" -type f | wc -l) files)"
}
harbor_hash() { # sorted file list + sha256 of each
  (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | cut -c1-16
}
scan_redact() { # scan_redact <dir>: key-shaped strings -> [REDACTED], count only
  python3 -I - "$1" <<'PY'
import os, re, sys
pat = re.compile(rb"(sk-ant-[A-Za-z0-9_\-]{16,}|sk-proj-[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9]{32,}|xai-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_\-]{30,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
                 rb"|(?<=CLAUDE_CODE_OAUTH_TOKEN=)[^\s\"']{16,}|(?<=OPENAI_API_KEY=)[^\s\"']{16,}|(?<=OPENROUTER_API_KEY=)[^\s\"']{16,}|sk-or-v1-[0-9a-f]{64}|(?<=XAI_API_KEY=)[^\s\"']{16,}|(?<=ANTHROPIC_API_KEY=)[^\s\"']{16,})")
files = hits = 0
for root, _, fs in os.walk(sys.argv[1]):
    for f in fs:
        p = os.path.join(root, f)
        if os.path.islink(p): continue
        try:
            b = open(p, "rb").read()
        except OSError:
            continue
        nb, n = pat.subn(b"[REDACTED]", b)
        if n:
            open(p, "wb").write(nb); files += 1; hits += n
print("key-pattern scan: %d match(es) redacted in %d file(s)" % (hits, files))
PY
}

# ---------- subcommands ----------
cmd_check() {
  log "checking $HOST (ConnectTimeout 20 s, one retry)"
  T 'export PATH="$HOME/.local/bin:$PATH"
echo "host: $(hostname)  user: $(whoami)"
echo "docker: $(docker version --format "{{.Server.Version}}" 2>&1 | head -1)"
echo "harbor: $(harbor --version 2>&1 | head -1)"
echo "tmux: $(tmux -V 2>&1 | head -1)  rsync: $(rsync --version | head -1 | sed -E "s/^rsync +version +([0-9.]+).*/\1/")"
echo "nproc: $(nproc)"; free -m | awk "NR==2{printf \"mem: total %d MiB, available %d MiB\\n\", \$2, \$7}"
echo "disk: $(df -h ~ | awk "NR==2{print \$4\" free of \"\$2}")"; echo "load: $(cut -d" " -f1-3 /proc/loadavg)"
echo "janitor: $(tail -1 ~/.runner/cleanup.log 2>/dev/null || echo "no ~/.runner/cleanup.log (run pipeline/vm/setup.sh)")"
[ -f ~/.runner/DISK_LOW ] && echo "WARNING: DISK_LOW is set: the Windows drive is nearly full; new runs are refused"
KF=~/cg.env
if [ -f "$KF" ]; then
  echo "$KF: mode $(stat -c %a "$KF")"
  for k in CLAUDE_CODE_OAUTH_TOKEN CLAUDE_FORCE_OAUTH; do
    if grep -qE "^(export )?$k=.+" "$KF"; then echo "  $k: set"; else echo "  $k: missing"; fi
  done
  grep -qE "^(export )?ANTHROPIC_API_KEY=.+" "$KF" && echo "  WARNING: ANTHROPIC_API_KEY is set in $KF; it would override the subscription token. Remove it."
else echo "keys file: ~/cg.env missing (run pipeline/vm/setup.sh)"; fi
[ -n "${ANTHROPIC_API_KEY:-}" ] && echo "WARNING: ANTHROPIC_API_KEY is set in the login environment of the target"
true'
}

cmd_run() {
  local task="" keys="" label="run" cheat=0 stop=0 wait_h=8 detach=0
  [ $# -ge 1 ] || die "usage: run <task> --keys K [...] -- <harbor args>"
  task="$1"; shift
  while [ $# -gt 0 ]; do case "$1" in
    --keys) keys="${2:?}"; shift 2 ;; --label) label="${2:?}"; shift 2 ;; --cheat) cheat=1; shift ;;
    --stop-on-pass) stop=1; shift ;; --wait-timeout) wait_h="${2:?}"; shift 2 ;; --detach) detach=1; shift ;;
    --local) LOCAL=1; shift ;; --) shift; break ;; *) die "unknown option $1" ;;
  esac; done
  local hargs=("$@")
  case "$keys" in claude|openai|qwen|codex|xai|none) ;; *) die "--keys must be claude, openai, qwen, codex, xai or none" ;; esac
  [[ "$label" =~ ^[A-Za-z0-9._-]+$ ]] || die "bad --label"
  local hdir; hdir="$(resolve_harbor_dir "$task")"
  local tname; tname="$(basename "$(dirname "$hdir")")"
  leak_guard "$hdir"
  # model trials: give this runner the pool token with the most headroom first (pipeline/tokens.py; no-op without a pool)
  if [ "$keys" = claude ] && [ "$LOCAL" != 1 ] && [ -s "$HOME/.config/cgpipe/tokens.json" ] && [ -f "$ROOT/../pipeline/tokens.py" ]; then
    python3 -I "$ROOT/../pipeline/tokens.py" auto --for "$HOST" --quiet || log "token pool: auto failed; using the token installed on $HOST"
    msg="$(python3 -I "$ROOT/../pipeline/tokens.py" ready "$HOST")" || die "not starting: $msg (a trial would stop at once and look hard; add a token or wait)"
  fi
  local hash; hash="$(harbor_hash "$hdir")"
  local stamp; stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local runid="$label-$stamp" session="tb-$tname-$label-$stamp"
  local rbase="$REMOTE_BASE/$tname/$hash"
  log "task $tname, harbor hash $hash, run $runid, keys $keys, cheat $cheat, stop-on-pass $stop, target $([ $LOCAL = 1 ] && echo local || echo $HOST)"

  [ "$LOCAL" = 1 ] || ! T 'test -f "$HOME/.runner/DISK_LOW"' 2>/dev/null || die "refused: $HOST reports DISK_LOW (its Windows drive is nearly full; see README section 10)"
  rs_to "$hdir/" "$rbase/harbor" --delete
  local hack_file=""
  if [ "$cheat" = 1 ]; then
    local hp="$CLONE_TB/docs/prompts/hack-trial-prompt.md"
    [ -f "$hp" ] || die "hack prompt not found at $hp (clones finished?)"
    local tmpd; tmpd="$(mktemp -d)"; cp "$hp" "$tmpd/"
    rs_to "$tmpd/" "$rbase"; rm -rf "$tmpd"; hack_file="$rbase/hack-trial-prompt.md"
  fi
  local conf; conf="$(mktemp)"
  {
    printf 'TASK=%q\nHASH=%q\nRUNID=%q\nKEYS=%q\nCHEAT=%q\nSTOP_ON_PASS=%q\nSESSION=%q\n' "$tname" "$hash" "$runid" "$keys" "$cheat" "$stop" "$session"
    printf 'RUNDIR="$HOME/%s/runs/%s"\nHARBOR_DIR="$HOME/%s/harbor"\nHACK_FILE="%s"\n' "$rbase" "$runid" "$rbase" "${hack_file:+\$HOME/$hack_file}"
    printf 'HARBOR_ARGS=('; printf ' %q' "${hargs[@]}"; printf ' )\n'
  } >"$conf"
  local cdir; cdir="$(mktemp -d)"; cp "$conf" "$cdir/run.conf"; cp "$VM2_SCRIPT" "$cdir/vm2-run.sh"; rm -f "$conf"
  printf '%s\n' "$hash" >"$cdir/harbor-hash.txt"
  rs_to "$cdir/" "$rbase/runs/$runid"; rm -rf "$cdir"

  T 'tmux new-session -d -s "$1" "bash $HOME/cg-runs/$2/$3/runs/$4/vm2-run.sh $HOME/cg-runs/$2/$3/runs/$4/run.conf"; tmux ls | grep -F "$1"' "$session" "$tname" "$hash" "$runid"
  log "started tmux session $session on target. Stop with: remote_run.sh stop $tname $runid"
  echo "$tname $hash $runid $session $([ "$LOCAL" = 1 ] && echo local || echo "$HOST")" >>"$ROOT/scripts/.runs.log" 2>/dev/null || true
  [ "$detach" = 1 ] && { log "detached; fetch later with: remote_run.sh pull $tname $runid (hash $hash)"; return 0; }

  local deadline=$(( $(date +%s) + wait_h * 3600 )) n=0
  until T 'test -f "$HOME/cg-runs/$1/$2/runs/$3/DONE"' "$tname" "$hash" "$runid" 2>/dev/null; do
    [ "$(date +%s)" -lt "$deadline" ] || { log "wait timeout; run continues on target. Fetch with: remote_run.sh pull $tname $runid"; return 3; }
    n=$((n + 1))
    if [ $((n % 6)) = 0 ]; then
      T 'f="$HOME/cg-runs/$1/$2/runs/$3"; echo "  $(tail -1 "$f/load.log" 2>/dev/null)  trials with result: $(find "$f/jobs" -mindepth 3 -maxdepth 3 -name result.json 2>/dev/null | wc -l)"' "$tname" "$hash" "$runid" 2>/dev/null || true
    fi
    sleep 20
  done
  log "run finished on target (exit code $(T 'cat "$HOME/cg-runs/$1/$2/runs/$3/exit-code"' "$tname" "$hash" "$runid" 2>/dev/null || echo '?'))"
  pull_run "$tname" "$hash" "$runid" "$cheat" "$label"
}

pull_run() { # pull_run <task> <hash> <runid> <cheat 0|1> <label>
  local tname="$1" hash="$2" runid="$3" cheat="$4" label="$5"
  local dest="$ROOT/tasks/$tname/runs/$([ "$cheat" = 1 ] && echo 'cheat/')${runid}"
  rs_from "$REMOTE_BASE/$tname/$hash/runs/$runid" "$dest"
  [ -f "$dest/harbor-hash.txt" ] || echo "$hash" >"$dest/harbor-hash.txt"
  T 'touch "$HOME/cg-runs/$1/$2/runs/$3/PULLED"' "$tname" "$hash" "$runid" 2>/dev/null || true   # the janitor may now delete it
  scan_redact "$dest"
  log "results in ${dest#"$ROOT"/} (load.log, run.log, jobs/, harbor-hash.txt)"
  [ -f "$dest/load.log" ] && awk '{for(i=1;i<=NF;i++){split($i,a,"=");if(a[1]=="cpu"){c=a[2]+0;if(c>mc)mc=c}if(a[1]=="mem"){m=a[2]+0;if(m>mm)mm=m}}}END{printf "  peak cpu %d%%, peak mem %d%%\n",mc,mm}' "$dest/load.log"
  return 0
}

cmd_pull() {
  local task="${1:?task}" runid="${2:?runid}"; shift 2
  [ "${1:-}" = --local ] && LOCAL=1
  local hash; hash="$(grep -F "$task " "$ROOT/scripts/.runs.log" 2>/dev/null | grep -F " $runid " | awk '{print $2}' | tail -1)"
  [ -n "$hash" ] || die "run $runid not in scripts/.runs.log; pass the hash via TB_HASH=<hash>"
  pull_run "$task" "${TB_HASH:-$hash}" "$runid" "$([[ "$runid" == cheat* ]] && echo 1 || echo 0)" "${runid%%-*}"
}

cmd_stop() {
  local task="${1:?task}" runid="${2:?runid}"; shift 2
  [ "${1:-}" = --local ] && LOCAL=1
  local session; session="$(grep -F "$task " "$ROOT/scripts/.runs.log" | grep -F " $runid " | awk '{print $4}' | tail -1)"
  [ -n "$session" ] || die "no session recorded for $runid"
  T 'tmux send-keys -t "$1" C-c; sleep 30; tmux has-session -t "$1" 2>/dev/null && tmux send-keys -t "$1" C-c; true' "$session"
  log "sent C-c to $session (the run script deletes its temporary env file when harbor exits)"
}

cmd_status() {
  [ "${1:-}" = --local ] && LOCAL=1
  T 'tmux ls 2>&1 | grep "^tb-" || echo "no tb-* tmux sessions"; ls -d "$HOME"/.tb-env.* 2>/dev/null | sed "s/^/leftover env file: /"; docker ps --format "{{.Names}} {{.Status}}" | head -20; true'
}

cmd_prepull() {
  [ $# -ge 1 ] || die "usage: prepull <image...>"
  local imgs=() a; for a in "$@"; do case "$a" in --local) LOCAL=1 ;; *) imgs+=("$a") ;; esac; done
  T 'for i in "$@"; do docker pull "$i" || echo "FAILED $i"; done' "${imgs[@]}"
}

cmd_pack() {
  local task="${1:?task}" keys="" label="run" cheat=0; shift
  while [ $# -gt 0 ]; do case "$1" in
    --keys) keys="${2:?}"; shift 2 ;; --label) label="${2:?}"; shift 2 ;; --cheat) cheat=1; shift ;; --) shift; break ;; *) die "unknown option $1" ;;
  esac; done
  local hargs=("$@")
  case "$keys" in claude|openai|qwen|codex|xai|none) ;; *) die "--keys must be claude, openai, qwen, codex, xai or none" ;; esac
  local hdir; hdir="$(resolve_harbor_dir "$task")"; local tname; tname="$(basename "$(dirname "$hdir")")"
  leak_guard "$hdir"
  local hash; hash="$(harbor_hash "$hdir")"
  local stage; stage="$(mktemp -d)"; local pk="$stage/$tname-$hash"; mkdir -p "$pk"
  cp -a "$hdir" "$pk/harbor"; cp "$VM2_SCRIPT" "$pk/vm2-run.sh"
  if [ "$cheat" = 1 ]; then cp "$CLONE_TB/docs/prompts/hack-trial-prompt.md" "$pk/" || die "hack prompt missing"; fi
  {
    printf 'TASK=%q\nHASH=%q\nKEYS=%q\nCHEAT=%q\nSTOP_ON_PASS=0\nSESSION=%q\n' "$tname" "$hash" "$keys" "$cheat" "tb-$tname-$label"
    printf 'HARBOR_ARGS=('; printf ' %q' "${hargs[@]}"; printf ' )\n'
  } >"$pk/run.conf.in"
  cat >"$pk/run.sh" <<'EOS'
#!/usr/bin/env bash
# Manual run on VM 2 (start with: bash run.sh <label>). Needs ~/cg.env (chmod 600) with the keys the run uses, docker, harbor, tmux.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
RUNID="${1:-run}-$(date -u +%Y%m%dT%H%M%SZ)"
RUNDIR="$PWD/runs/$RUNID"; mkdir -p "$RUNDIR"
{ cat run.conf.in
  printf 'RUNID=%q\nRUNDIR=%q\nHARBOR_DIR=%q\nHACK_FILE=%q\n' "$RUNID" "$RUNDIR" "$PWD/harbor" "$PWD/hack-trial-prompt.md"
} >"$RUNDIR/run.conf"
cp vm2-run.sh "$RUNDIR/"
SESSION="tb-manual-$RUNID"
if command -v tmux >/dev/null; then
  tmux new-session -d -s "$SESSION" "bash '$RUNDIR/vm2-run.sh' '$RUNDIR/run.conf'"; echo "running in tmux session $SESSION; attach with: tmux attach -t $SESSION"
  until [ -f "$RUNDIR/DONE" ]; do sleep 20; done
else bash "$RUNDIR/vm2-run.sh" "$RUNDIR/run.conf"; fi
cat "$RUNDIR/run.log" | tail -3
OUT="$PWD/$(basename "$PWD")-results-$RUNID.zip"
python3 -m zipfile -c "$OUT" "runs/$RUNID"   # python3 is on every Ubuntu; VM 2 has no zip/unzip
echo "results zip: $OUT (copy it to VM 1 ~/cg-inbox/)"
EOS
  chmod +x "$pk/run.sh" "$pk/vm2-run.sh"
  mkdir -p "$HOME/cg-outbox"
  (cd "$stage" && zip -qr "$HOME/cg-outbox/$tname-$hash.zip" "$tname-$hash"); rm -rf "$stage"
  log "wrote ~/cg-outbox/$tname-$hash.zip. On VM 2: python3 -m zipfile -e <zip> . (VM 2 has no unzip), cd into the folder, then bash run.sh $label; copy the results zip to VM 1 ~/cg-inbox/ and run: remote_run.sh --unpack <zip> --task $tname"
}

cmd_unpack() {
  local z="${1:?zip}" task=""; shift || true
  while [ $# -gt 0 ]; do case "$1" in --task) task="${2:?}"; shift 2 ;; *) die "unknown option $1" ;; esac; done
  [ -f "$z" ] || z="$HOME/cg-inbox/$z"; [ -f "$z" ] || die "zip not found"
  [ -n "$task" ] || task="$(basename "$z" | sed -E 's/-[0-9a-f]{16}-results.*//')"
  [ -d "$ROOT/tasks/$task" ] || die "tasks/$task does not exist"
  local tmp; tmp="$(mktemp -d)"; unzip -q "$z" -d "$tmp"
  local dest="$ROOT/tasks/$task/runs/manual-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$dest"; cp -a "$tmp"/. "$dest"/; rm -rf "$tmp"
  scan_redact "$dest"; log "unpacked into ${dest#"$ROOT"/}"
}

main() {
  [ $# -ge 1 ] || { sed -n '2,19p' "${BASH_SOURCE[0]}"; exit 2; }
  local c="$1"; shift
  case "$c" in
    check) [ "${1:-}" = --local ] && LOCAL=1; cmd_check ;;
    run) cmd_run "$@" ;; pull) cmd_pull "$@" ;; stop) cmd_stop "$@" ;; status) cmd_status "$@" ;;
    prepull) cmd_prepull "$@" ;; pack) cmd_pack "$@" ;; --unpack|unpack) cmd_unpack "$@" ;;
    -h|--help|help) sed -n '2,19p' "${BASH_SOURCE[0]}" ;;
    *) die "unknown subcommand $c" ;;
  esac
}
main "$@"
