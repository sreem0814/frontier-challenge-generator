#!/usr/bin/env bash
# Build build/libchipcore.a from this tree with exactly the options the grader uses.
#   ./build.sh            configure if needed, then build
#   ./build.sh clean      remove build/ first
set -euo pipefail
cd "$(dirname "$0")"
[ "${1:-}" = clean ] && rm -rf build
if [ ! -f build/build.ninja ]; then
  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo >/dev/null
fi
ninja -C build chipcore
