#!/usr/bin/env bash
# Host side: run smoke_test.sh for one repo in two throwaway containers sharing a work volume.
# Phase 1 (network on): clone + fetch deps. Phase 2 (--network none): build + list + 3 test runs.
# usage: run_one.sh <name> <url> <ref> <outroot> [cpus=4] [mem=8g] [cache=warm|cold]
set -u
NAME=$1; URL=$2; REF=$3; OUTROOT=$4; CPUS=${5:-4}; MEM=${6:-8g}; CACHE=${7:-warm}
IMG=${IMG:-cgpipe-smoke:1}
HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$OUTROOT/$NAME"; rm -rf "$OUT"; mkdir -p "$OUT"
VOL="cgsmoke-work-$NAME-$$"
docker volume create "$VOL" >/dev/null
if [ "$CACHE" = warm ]; then
  CV=(-v cg-cargo:/root/.cargo/registry -v cg-gomod:/root/go/pkg/mod -v cg-gobuild:/root/.cache/go-build
      -v cg-pip:/root/.cache/pip -v cg-npm:/root/.npm -v cg-corepack:/root/.cache/node/corepack -v cg-ccache:/root/.cache/ccache)
else CV=(); fi
common=(--rm --cpus "$CPUS" --memory "$MEM" --pids-limit 4096 -v "$VOL":/work -v "$OUT":/out
        -v "$HERE/${SCRIPT:-smoke_test2.sh}":/cg/smoke_test.sh:ro "${CV[@]}" -e CCACHE_DIR=/root/.cache/ccache)
t0=$(date +%s)
docker run "${common[@]}" "$IMG" bash /cg/smoke_test.sh "$URL" "$REF" fetch > "$OUT/stdout.txt" 2>&1
t1=$(date +%s)
docker run --network none "${common[@]}" "$IMG" bash /cg/smoke_test.sh "$URL" "$REF" build 3 >> "$OUT/stdout.txt" 2>&1
t2=$(date +%s)
docker volume rm -f "$VOL" >/dev/null
echo "CG wall_fetch $((t1-t0))" >> "$OUT/stdout.txt"; echo "CG wall_build_test $((t2-t1))" >> "$OUT/stdout.txt"
python3 -I "$HERE/parse_results.py" "$OUT" | python3 -I -c "import json,sys; d=json.load(sys.stdin); d.update(name='$NAME', wall_fetch=$((t1-t0)), wall_build_test=$((t2-t1)), cache='$CACHE'); print(json.dumps(d))"
