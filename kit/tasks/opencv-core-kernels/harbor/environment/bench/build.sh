#!/usr/bin/env bash
# build.sh: build opencv_core from /app/opencv into /app/build with the fixed configuration
# (cmake-args.txt), then link the benchmark tool against it as /app/bench/bin/cvbench.
# The same configuration is used when your work is measured; flags you pass here change nothing there.
set -euo pipefail
SRC=/app/opencv
B=/app/build
HERE="$(cd "$(dirname "$0")" && pwd)"
mapfile -t ARGS < "$HERE/cmake-args.txt"
if [ ! -f "$B/build.ninja" ]; then
  mkdir -p "$B"
  cmake -S "$SRC" -B "$B" "${ARGS[@]}" > "$B/configure.log" 2>&1 || { tail -30 "$B/configure.log"; exit 1; }
fi
ninja -C "$B" -j "${JOBS:-8}" opencv_core
mkdir -p "$HERE/bin"
bash "$HERE/mkbench.sh" "$SRC" "$B" "$HERE/bin/cvbench"
echo "built $HERE/bin/cvbench"
