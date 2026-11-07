#!/usr/bin/env bash
# Build libllama, llama-common and check/case_runner from this tree with exactly the options the grader uses.
#   ./build.sh            configure if needed, then build (incremental)
#   ./build.sh clean      remove build/ first
set -euo pipefail
cd "$(dirname "$0")"
[ "${1:-}" = clean ] && rm -rf build
if [ ! -f build/build.ninja ]; then
  cmake -S check -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DTREE="$PWD" >/dev/null
fi
ninja -C build case_runner
