#!/usr/bin/env bash
# l3_run.sh: L3 of the evaluation ladder (Docker, no model, no keys). Copied 2026-10-20 from /work/tb-ws (written
# there 2026-10-08) and adapted to continuous 0-1 rewards; procedure in kit/BUILD.md (L3).
#
#   l3_run.sh <task> [--local] [--only build,oracle,nop,variants,det] [--det-n 50] [--cpus "1 2"] [--oracle-k 2]
#             [--variant-dir DIR]   run only DIR as a variant and report its reward (no pass rule; recall_check.sh)
#
# Steps (each prints PASS/FAIL; the script exits 1 if any step fails, after running the rest):
#   oracle    remote_run.sh run <task> --keys none -- -a oracle -k 2 -n 1   every trial reaches the ceiling
#             (task.toml [metadata] oracle_reward_threshold, default 1) and trials agree within 0.05
#   nop       remote_run.sh run <task> --keys none -- -a nop -k 2     reward exactly 0 with valid = 1 on both runs
#   variants  every tasks/<task>/l3/<variant>/ (a drop-in for harbor/solution/) is run as the oracle of a derived
#             task tasks/<task>--l3-<variant>/harbor/ (git-ignored copy): near-miss-* and edge-outside-* must
#             score 0; alt-solution* and edge-inside-* must reach the ceiling; partial-* must land strictly
#             between 0 and the ceiling (partial credit works)
#   det       on the target: build the agent image once, run solve.sh once (plus any [[verifier.collect]]
#             commands), copy the task.toml artifacts out, then run the verifier image N times per CPU count
#             with those artifacts mounted read-only and tests/ mounted at /tests; every verdict must be identical
# All Harbor runs go through remote_run.sh (leak guard, --keys none, the runner host unless --local). Only harbor/ folders and
# this script's own commands reach the target. Wall time per step is appended to data/l3-runs.tsv.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF_DIR/.." && pwd)"
RR="$SELF_DIR/remote_run.sh"
HOST="${CG_RUNNER_HOST:-vm2}"
SSH_OPTS=(-o ConnectTimeout=20 -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=20)
LOCAL=0 ONLY="oracle,nop,variants,det" DET_N=50 CPUS="" ORACLE_K=2 CEIL=1 VDIR=""

die() { echo "l3_run.sh: $*" >&2; exit 2; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }
T() { # run a bash script (stdin) on the target
  local script="$1"; shift
  if [ "$LOCAL" = 1 ]; then printf '%s\n' "$script" | bash -s -- "$@"; return; fi
  local rc=0
  printf '%s\n' "$script" | ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$@" || rc=$?
  if [ "$rc" = 255 ]; then sleep 5; printf '%s\n' "$script" | ssh "${SSH_OPTS[@]}" "$HOST" bash -s -- "$@" && return 0 || rc=$?; fi
  return "$rc"
}
harbor_hash() { (cd "$1" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | cut -c1-16; }
cost_log() { # cost_log <step> <seconds> <result>
  local f="$ROOT/data/l3-runs.tsv"
  mkdir -p "$(dirname "$f")"
  printf '| %s | L3 %s | %s | %s s wall | %s | %s |\n' "$(date -u +%FT%TZ)" "$1" "$TASK" "$2" "$3" "$([ $LOCAL = 1 ] && echo local || echo "$HOST")" >>"$f"
}

# rewards <runs dir> <label>: prints one reward per trial of the newest run with that label ("ERR" if none)
rewards() {
  local d; d="$(ls -1dt "$1"/"$2"-* 2>/dev/null | head -1)"
  [ -n "$d" ] || { echo "ERR(no run dir)"; return; }
  python3 -I - "$d" <<'PY'
import json, os, sys
d = sys.argv[1]
out = []
for root, dirs, files in os.walk(os.path.join(d, "jobs")):
    if os.path.basename(root) == "verifier" or "result.json" not in files:
        continue
    if os.path.basename(os.path.dirname(root)) == "jobs":  # job-level result.json
        continue
    v = os.path.join(root, "verifier")
    r = None
    for f in ("reward.json", "reward.txt"):  # Harbor prefers reward.json
        p = os.path.join(v, f)
        if os.path.isfile(p):
            t = open(p).read().strip()
            try:
                if f.endswith(".txt"):
                    r = float(t)
                else:
                    j = json.loads(t)
                    r = float(j["reward"]) if int(j.get("valid", 1)) == 1 else "ERR(valid=0)"
            except Exception:
                r = "ERR"
            break
    if r is None:
        try:
            res = json.load(open(os.path.join(root, "result.json")))
            ex = res.get("exception_info") or res.get("exception")
            r = "ERR(" + (str(ex.get("exception_type")) if isinstance(ex, dict) else "no reward") + ")"
        except Exception:
            r = "ERR(no reward)"
    out.append(str(r))
print(" ".join(out) if out else "ERR(no trials)")
PY
}

expect() { # expect <want 0|1|mid> <reward list> -> 0 if every reward matches; 1 = ceiling with spread <= 0.05
  local want="$1"; shift
  [ -n "$*" ] || return 1
  case "$*" in *ERR*) return 1 ;; esac
  python3 -I -c '
import sys
want, ceil, rs = sys.argv[1], float(sys.argv[2]), [float(x) for x in sys.argv[3:]]
if want == "any":
    ok = True
elif want == "0":
    ok = all(r == 0.0 for r in rs)
elif want == "1":
    ok = all(r >= ceil - 1e-9 for r in rs) and max(rs) - min(rs) <= 0.05
else:
    ok = all(0.0 < r < ceil for r in rs)
sys.exit(0 if ok else 1)' "$want" "$CEIL" $*
}

run_harbor() { # run_harbor <task-name> <label> <harbor args...>
  local t="$1" label="$2"; shift 2
  "$RR" run "$t" --keys none --label "$label" $([ $LOCAL = 1 ] && echo --local) -- "$@" >"$LOGDIR/$t-$label.log" 2>&1 || true
  rewards "$ROOT/tasks/$t/runs" "$label"
}

step() { # step <name> <want> <task-name> <label> <harbor args...>
  local name="$1" want="$2" t="$3" label="$4"; shift 4
  local t0; t0=$(date +%s)
  log "$name: running ($t, $*)"
  local r; r="$(run_harbor "$t" "$label" "$@")"
  local dt=$(( $(date +%s) - t0 )) res
  if expect "$want" $r; then res="PASS"; else res="FAIL"; FAILS=$((FAILS + 1)); fi
  log "$res $name: rewards [$r], want $want, ${dt}s (log: ${LOGDIR#"$ROOT"/}/$t-$label.log)"
  echo "| $name | want $want | $r | $res | ${dt}s |" >>"$SUMMARY"
  cost_log "$name" "$dt" "$res rewards [$r]"
}

derive_variant() { # derive_variant <variant dir> -> prints derived task name
  local v="$1" vname; vname="$(basename "$v")"
  local dt="$TASK--l3-$vname" dd="$ROOT/tasks/$TASK--l3-$vname"
  rm -rf "$dd"; mkdir -p "$dd"
  cp -a "$HDIR" "$dd/harbor"; rm -rf "$dd/harbor/solution"; cp -a "$v" "$dd/harbor/solution"
  chmod +x "$dd/harbor/solution/solve.sh"
  echo "$dt"
}

det_step() {
  local hash; hash="$(harbor_hash "$HDIR")"
  local rdir="cg-runs/$TASK/$hash/harbor"
  local cpus="$CPUS"
  if [ -z "$cpus" ]; then
    local tc; tc="$(python3 -I -c "import re,sys; m=re.search(r'^\s*cpus\s*=\s*(\d+)', open(sys.argv[1]).read(), re.M); print(m.group(1) if m else 1)" "$HDIR/task.toml")"
    if [ "$tc" = 1 ]; then cpus="1 2"; else cpus="1 $tc"; fi
  fi
  local t0; t0=$(date +%s)
  log "det: verifier x$DET_N at CPU counts [$cpus] on $([ $LOCAL = 1 ] && echo VM1 || echo "$HOST") ($rdir)"
  local out rc=0
  out="$(T "$DET_SCRIPT" "$rdir" "$TASK" "$DET_N" "${cpus// /,}" 2>&1)" || rc=$?   # comma-joined: ssh re-splits spaced args
  printf '%s\n' "$out" | tail -25 | sed 's/^/  /'
  printf '%s\n' "$out" >"$LOGDIR/$TASK-det.log"
  local dt=$(( $(date +%s) - t0 )) res
  local want_n got_n; want_n=$(wc -w <<<"$cpus"); got_n=$(printf '%s\n' "$out" | grep -c "^cpus=.* n=$DET_N " || true)
  if [ "$rc" = 0 ] && [ "$got_n" = "$want_n" ] && printf '%s\n' "$out" | grep -q '^DET PASS'; then res=PASS
  else res=FAIL; FAILS=$((FAILS + 1)); [ "$got_n" = "$want_n" ] || log "det: ran $got_n of $want_n CPU counts"; fi
  log "$res det (${dt}s)"
  echo "| det x$DET_N cpus [$cpus] | identical | $(printf '%s\n' "$out" | grep '^cpus=' | tr '\n' ' ') | $res | ${dt}s |" >>"$SUMMARY"
  cost_log "det" "$dt" "$res $(printf '%s\n' "$out" | grep '^cpus=' | tr '\n' ' ')"
}

# The target-side determinism script (bash; args: <harbor dir relative to $HOME> <task> <N> <cpu list>).
DET_SCRIPT='set -uo pipefail
H="$HOME/$1"; TASK="$2"; N="$3"; CPUS="${4//,/ }"
[ -d "$H" ] || { echo "DET FAIL: $H missing (run the oracle step first so remote_run.sh syncs harbor/)"; exit 1; }
W="$(mktemp -d "$HOME/l3det.XXXXXX")"
TAG="$(echo "l3det-$TASK" | tr "[:upper:]" "[:lower:]")"
trap "docker rm -f l3det-$TASK-agent >/dev/null 2>&1; docker run --rm -v \"$W\":/w --entrypoint sh $TAG-agent -c \"rm -rf /w/* /w/.[!.]*\" >/dev/null 2>&1; rm -rf \"$W\"" EXIT
docker build -q -t "$TAG-agent" "$H/environment" >"$W/build-agent.log" 2>&1 || { echo "DET FAIL: agent image build"; tail -5 "$W/build-agent.log"; exit 1; }
MODE="$(python3 -I -c "import tomllib,sys; print((tomllib.load(open(sys.argv[1],\"rb\")).get(\"verifier\") or {}).get(\"environment_mode\",\"shared\"))" "$H/task.toml")"
if [ "$MODE" = separate ] && [ -f "$H/tests/Dockerfile" ]; then
  docker build -q -t "$TAG-verifier" "$H/tests" >"$W/build-verifier.log" 2>&1 || { echo "DET FAIL: verifier image build"; tail -5 "$W/build-verifier.log"; exit 1; }
  VIMG="$TAG-verifier"
else VIMG="$TAG-agent"; fi
docker rm -f "l3det-$TASK-agent" >/dev/null 2>&1
docker run -d --name "l3det-$TASK-agent" "$TAG-agent" sleep infinity >/dev/null
docker cp "$H/solution" "l3det-$TASK-agent:/solution" >/dev/null
WD="$(docker inspect -f "{{.Config.WorkingDir}}" "$TAG-agent")"; WD="${WD:-/app}"
docker exec -w "$WD" "l3det-$TASK-agent" bash /solution/solve.sh >"$W/solve.log" 2>&1 || { echo "DET FAIL: solve.sh failed"; tail -5 "$W/solve.log"; exit 1; }
python3 -I - "$H/task.toml" >"$W/collect.txt" <<PY
import tomllib, sys
t = tomllib.load(open(sys.argv[1], "rb"))
for c in (t.get("verifier") or {}).get("collect") or []:
    print(c.get("command", "").replace("\n", " "))
PY
while IFS= read -r c; do [ -n "$c" ] && docker exec "l3det-$TASK-agent" bash -c "$c" >>"$W/solve.log" 2>&1; done <"$W/collect.txt"
ARTS="$(python3 -I -c "import tomllib,sys; print(\"\n\".join(tomllib.load(open(sys.argv[1],\"rb\")).get(\"artifacts\") or []))" "$H/task.toml")"
MOUNTS=()
if [ -n "$ARTS" ]; then
  while IFS= read -r a; do
    [ -n "$a" ] || continue
    mkdir -p "$W/art$(dirname "$a")"
    docker cp "l3det-$TASK-agent:$a" "$W/art$a" >/dev/null 2>&1 || { echo "DET FAIL: artifact $a not produced"; exit 1; }
    MOUNTS+=(-v "$W/art$a:$a:ro")
  done <<<"$ARTS"
else
  docker cp "l3det-$TASK-agent:$WD" "$W/art-wd" >/dev/null; MOUNTS+=(-v "$W/art-wd:$WD:ro")
fi
echo "artifacts: $(echo "$ARTS" | grep -c .) mounted read-only; verifier image $VIMG; tests mounted at /tests"
ALL=""
for C in $CPUS; do
  declare -A SEEN=(); start=$(date +%s)
  for i in $(seq 1 "$N"); do
    L="$W/logs-$C-$i"; mkdir -p "$L/verifier"
    docker run --rm --cpus "$C" --network none "${MOUNTS[@]}" -v "$H/tests:/tests:ro" -v "$L:/logs" "$VIMG" bash /tests/test.sh >"$L/out.txt" 2>&1
    if [ -f "$L/verifier/reward.txt" ]; then r="$(tr -d "[:space:]" <"$L/verifier/reward.txt")"
    elif [ -f "$L/verifier/reward.json" ]; then r="$(tr -d "[:space:]" <"$L/verifier/reward.json")"
    else r="none"; fi
    SEEN[$r]=$(( ${SEEN[$r]:-0} + 1 ))
    [ "$i" = 1 ] && [ "$C" = "${CPUS%% *}" ] && { echo "first run output (tail):"; tail -3 "$L/out.txt" | sed "s/^/    /"; }
    rm -rf "$L"
  done
  line="cpus=$C n=$N"; for k in "${!SEEN[@]}"; do line="$line reward[$k]=${SEEN[$k]}"; ALL="$ALL $k"; done
  echo "$line ($(( $(date +%s) - start ))s)"
  unset SEEN
done
# the spec: repeated runs agree within 0.05 (timing-based rewards are never bit-identical)
if echo $ALL | tr " " "\n" | grep -qv "^[0-9.]*$"; then echo "DET FAIL: a run left no numeric reward:$ALL"; exit 1; fi
LO="$(echo $ALL | tr " " "\n" | grep . | sort -g | head -1)"; HI="$(echo $ALL | tr " " "\n" | grep . | sort -g | tail -1)"
if awk -v a="$LO" -v b="$HI" "BEGIN{exit !(b-a<=0.05)}"; then echo "DET PASS: rewards within 0.05 ($ALL) across all runs and CPU counts"; else echo "DET FAIL: rewards differ by more than 0.05:$ALL"; exit 1; fi'

# ---------- main ----------
[ $# -ge 1 ] || { sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 2; }
TASK="$1"; shift
while [ $# -gt 0 ]; do case "$1" in
  --local) LOCAL=1; shift ;; --only) ONLY="${2:?}"; shift 2 ;; --det-n) DET_N="${2:?}"; shift 2 ;;
  --cpus) CPUS="${2:?}"; shift 2 ;; --oracle-k) ORACLE_K="${2:?}"; shift 2 ;;
  --variant-dir) VDIR="$(cd "${2:?}" && pwd)"; ONLY=variants; shift 2 ;; *) die "unknown option $1" ;;
esac; done
[[ "$TASK" =~ ^[A-Za-z0-9._-]+$ ]] || die "task must be a name under tasks/"
HDIR="$ROOT/tasks/$TASK/harbor"; [ -d "$HDIR" ] || die "$HDIR missing"
CEIL="$(python3 -I -c 'import tomllib,sys; print((tomllib.load(open(sys.argv[1],"rb")).get("metadata") or {}).get("oracle_reward_threshold", 1))' "$HDIR/task.toml" 2>/dev/null || echo 1)"
LOGDIR="$ROOT/tasks/$TASK/runs/l3-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$LOGDIR"
SUMMARY="$LOGDIR/summary.md"; FAILS=0
printf '# L3 %s (%s)\n\n| step | expected | rewards | result | wall |\n|---|---|---|---|---|\n' "$TASK" "$(date -u +%FT%TZ)" >"$SUMMARY"
T0=$(date +%s)
has() { [[ ",$ONLY," == *",$1,"* ]]; }

has oracle && step "oracle x$ORACLE_K (build + ceiling $CEIL, spread <= 0.05)" 1 "$TASK" l3-oracle -a oracle -k "$ORACLE_K" -n 1
has nop && step "nop x2 (reward 0 on both runs, spec: twice each)" 0 "$TASK" l3-nop -a nop -k 2 -n 1
if [ -n "$VDIR" ]; then
  [ -f "$VDIR/solve.sh" ] || die "$VDIR/solve.sh missing"
  step "$(basename "$VDIR") (report only)" any "$(derive_variant "$VDIR")" "l3-$(basename "$VDIR")" -a oracle
elif has variants; then
  for v in "$ROOT/tasks/$TASK"/l3/*/; do
    v="${v%/}"; [ -f "$v/solve.sh" ] || continue
    n="$(basename "$v")"
    case "$n" in near-miss*|edge-outside*) want=0 ;; alt-solution*|edge-inside*) want=1 ;; partial*) want=mid ;; *) log "skip $n (unknown kind)"; continue ;; esac
    grep -q 'echo "TODO"' "$v/solve.sh" && { log "skip $n (template placeholder)"; continue; }
    d="$(derive_variant "$v")"
    step "$n" "$want" "$d" "l3-$n" -a oracle
  done
fi
has det && det_step
TOT=$(( $(date +%s) - T0 ))
printf '\nTotal wall %ss, %s failing step(s).\n' "$TOT" "$FAILS" >>"$SUMMARY"
printf 'HARBOR-HASH: %s\nFAILING-STEPS: %s\nSTEPS-RUN: %s\n' "$(harbor_hash "$HDIR")" "$FAILS" "$ONLY" >>"$SUMMARY"
cost_log "total" "$TOT" "$([ $FAILS = 0 ] && echo PASS || echo "FAIL ($FAILS)")"
log "L3 $TASK: $([ $FAILS = 0 ] && echo PASS || echo "FAIL ($FAILS step(s))") in ${TOT}s; summary ${SUMMARY#"$ROOT"/}"
[ "$FAILS" = 0 ]
