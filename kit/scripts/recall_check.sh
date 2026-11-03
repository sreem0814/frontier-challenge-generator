#!/usr/bin/env bash
# recall_check.sh: the one-shot recall check (kit/BUILD.md step 3b-1). One tool-less model call per target file asks
# a model to write its own implementation of that file in one go, from the public instruction, the file's current
# stub and what it already knows about the subject (no tools, no tests, no iteration); the files then run as a
# drop-in solution through l3_run.sh --variant-dir, scored by the task's own verifier on the runner. A high reward
# means the subject is so well known that a model writes it without working at it: the task is too easy as scoped.
# It never asks for upstream code verbatim (models rightly decline to reproduce long copyrighted files).
# Sealed grading: only harbor/instruction.md and files under harbor/environment/ enter the prompt, never tests/,
# solution/ or reference outputs. Model output is untrusted code: it runs only inside the Harbor trial container.
#
#   recall_check.sh <task> [--model sonnet] [--max-files 12] [--jobs 4] [--budget-usd 8] [--no-run] [--rescore]
#
# Needs tasks/<task>/build/targets.txt: one /app-relative path per line (the files the agent writes or restores),
# most important first, '#' comments allowed; an optional line "build: <command>" runs in /app after the copy, and
# an optional "check: <command with {}>" (e.g. "ruby -c {}") keeps a recalled file only if it passes, so one broken
# file leaves its stub in place instead of zeroing everything. --rescore reuses the files already generated.
# Uses the spike image and token (~/.config/cgpipe/env) on VM 1; runs the verifier on CG_RUNNER_HOST.
# Output: tasks/<task>/build/recall-<model>/ (solve.sh, files/, raw/) and one JSON line appended to
# tasks/<task>/build/gates.jsonl: {"kind": "recall", "model", "files", "reward", "at"}, which the dashboard reads.
set -euo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF_DIR/.." && pwd)"
ENVF="$HOME/.config/cgpipe/env"; IMAGE="cgpipe-spike:1"
MODEL=sonnet MAXF=12 JOBS=4 BUDGET=8 RUN=1 RESCORE=0
die() { echo "recall_check.sh: $*" >&2; exit 2; }
log() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

[ $# -ge 1 ] || { sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 2; }
TASK="$1"; shift
while [ $# -gt 0 ]; do case "$1" in
  --model) MODEL="${2:?}"; shift 2 ;; --max-files) MAXF="${2:?}"; shift 2 ;; --jobs) JOBS="${2:?}"; shift 2 ;;
  --budget-usd) BUDGET="${2:?}"; shift 2 ;; --no-run) RUN=0; shift ;; --rescore) RESCORE=1; shift ;;
  *) die "unknown option $1" ;;
esac; done
[[ "$TASK" =~ ^[A-Za-z0-9._-]+$ ]] || die "task must be a name under tasks/"
B="$ROOT/tasks/$TASK"; H="$B/harbor"; TG="$B/build/targets.txt"
[ -f "$TG" ] || die "$TG missing (BUILD.md step 3: list the files the agent writes, one /app-relative path per line)"
[ -s "$ENVF" ] || die "$ENVF missing (pipeline/setup-token.sh)"
docker image inspect "$IMAGE" >/dev/null 2>&1 || die "image $IMAGE missing (README section 5)"

OUT="$B/build/recall-$MODEL"
if [ "$RESCORE" = 1 ]; then [ -d "$OUT/files" ] || die "--rescore: no files in $OUT"; else rm -rf "$OUT"; mkdir -p "$OUT/files" "$OUT/raw"; fi
BUILD_CMD="$(sed -n 's/^build:[[:space:]]*//p' "$TG" | head -1)"
CHECK_CMD="$(sed -n 's/^check:[[:space:]]*//p' "$TG" | head -1)"
mapfile -t FILES < <(grep -v '^[[:space:]]*#' "$TG" | grep -v '^build:' | grep -v '^check:' | sed 's/[[:space:]]*$//; s|^/app/||; s|^/||' | grep . | grep -v '/$' | head -n "$MAXF")   # files only, not folders
[ "${#FILES[@]}" -gt 0 ] || die "no target files in $TG"
for f in "${FILES[@]}"; do [[ "$f" != *..* ]] || die "bad path $f"; done
PER_CALL="$(python3 -I -c "print(round($BUDGET / ${#FILES[@]}, 2))")"

gen_one() { # gen_one <index> <path>
  local i="$1" path="$2" stub
  stub="$(find "$H/environment" -type f -path "*/$path" 2>/dev/null | head -1)"
  {
    echo "You have no tools; answer in one message."
    echo "Below is the public instruction of a programming task. Write your own complete implementation of the file"
    echo "/app/$path for it, using the instruction, the stub below and what you know about the formats and APIs"
    echo "involved, so that it builds and works with the rest of /app. Write original code; do not reproduce"
    echo "upstream source verbatim. Output only the file content, inside one fenced code block, with no commentary."
    echo; echo "=== instruction.md ==="; cat "$H/instruction.md"
    echo; echo "=== all files the task asks for ==="; printf '%s\n' "${FILES[@]}"
    if [ -n "$stub" ]; then echo; echo "=== current content of /app/$path (a stub) ==="; head -c 60000 "$stub"; fi
  } >"$OUT/raw/$i.prompt"
  local name="cg-recall-$TASK-$i-$$"
  timeout 1500 docker run --rm -i --name "$name" --cpus 1 --memory 1g --env-file "$ENVF" "$IMAGE" claude -p \
      --model "$MODEL" --output-format text --no-session-persistence --tools "" --max-turns 1 \
      --max-budget-usd "$PER_CALL" <"$OUT/raw/$i.prompt" >"$OUT/raw/$i.out" 2>"$OUT/raw/$i.err" || true
  docker rm -f "$name" >/dev/null 2>&1 || true
  python3 -I - "$OUT/raw/$i.out" "$OUT/files/$path" <<'PY'
import os, re, sys
text = open(sys.argv[1], errors="replace").read()
blocks = re.findall(r"```[^\n]*\n(.*?)\n```", text, re.S)
body = max(blocks, key=len) if blocks else text
os.makedirs(os.path.dirname(sys.argv[2]) or ".", exist_ok=True)
open(sys.argv[2], "w").write(body + "\n")
PY
  log "  $path: $(wc -l <"$OUT/files/$path") lines"
}

log "recall $TASK: ${#FILES[@]} file(s) with $MODEL, $JOBS at a time, \$$PER_CALL cap per call$([ $RESCORE = 1 ] && echo ' (rescore: reusing files)')"
n=0
for i in "${!FILES[@]}"; do
  [ "$RESCORE" = 1 ] && break
  gen_one "$i" "${FILES[$i]}" &
  n=$((n + 1)); [ $((n % JOBS)) = 0 ] && wait
done
wait

{
  echo '#!/usr/bin/env bash'
  echo '# Generated by kit/scripts/recall_check.sh: model-recalled files, copied over /app (not a reference).'
  echo 'set -uo pipefail'
  echo 'HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"'
  if [ -n "$CHECK_CMD" ]; then   # keep only files that pass the check; the rest keep their stub
    echo 'kept=0; dropped=0'
    echo 'while IFS= read -r -d "" f; do rel="${f#"$HERE"/files/}"; tmp="$(mktemp)"; cp "$f" "$tmp"'
    printf '  if %s >/dev/null 2>&1; then mkdir -p "/app/$(dirname "$rel")"; cp "$f" "/app/$rel"; kept=$((kept+1)); else dropped=$((dropped+1)); fi; rm -f "$tmp"
' "${CHECK_CMD//\{\}/"\$tmp"}"
    echo 'done < <(find "$HERE/files" -type f -print0)'
    echo 'echo "recalled files kept: $kept, dropped by the check: $dropped"'
  else
    echo 'cp -r "$HERE"/files/. /app/'
  fi
  [ -n "$BUILD_CMD" ] && printf 'cd /app && { %s; } || echo "build failed (the verifier decides)"\n' "$BUILD_CMD"
  echo 'exit 0'
} >"$OUT/solve.sh"
chmod +x "$OUT/solve.sh"
[ "$RUN" = 1 ] || { log "files in ${OUT#"$ROOT"/}; --no-run: not scored"; exit 0; }

log "scoring on ${CG_RUNNER_HOST:-vm2} through l3_run.sh --variant-dir"
res="$(bash "$SELF_DIR/l3_run.sh" "$TASK" --variant-dir "$OUT" 2>&1 | tee "$OUT/raw/l3.log" | grep -E 'PASS|FAIL' | tail -3)" || true
reward="$(grep -o 'rewards \[[^]]*\]' <<<"$res" | head -1 | grep -oE '[0-9]+(\.[0-9]+)?' | head -1)"
# a zero from a failed build says only that one-shot code didn't compile: recorded as inconclusive, not as a clean pass
det="$(ls -t "$ROOT/tasks/$TASK--l3-recall-$MODEL"/runs/l3-recall-*/jobs/*/*/verifier/details.json 2>/dev/null | head -1)"
python3 -I - "$B/build/gates.jsonl" "$MODEL" "${#FILES[@]}" "${reward:-}" "$det" <<'PY'
import datetime, json, sys
p, model, n, r, det = sys.argv[1:6]
line = {"kind": "recall", "model": model, "files": int(n), "reward": float(r) if r else None,
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
try:
    reason = str((json.load(open(det)).get("additional_data") or {}).get("reason", "")) if det else ""
except (OSError, ValueError):
    reason = ""
if line["reward"] == 0 and "build" in reason.lower():
    line["inconclusive"] = "the one-shot code did not build: " + reason[:120]
open(p, "a").write(json.dumps(line) + "\n")
print(json.dumps(line))
PY
[ -n "${reward:-}" ] || { log "no reward: see ${OUT#"$ROOT"/}/raw/l3.log"; exit 1; }
