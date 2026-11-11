#!/usr/bin/env bash
# Build flatc from this tree with exactly the CMake options the grader uses (Release, no tests, gcc 12, Ninja).
#   ./build.sh            configure if needed, then build (incremental)
#   ./build.sh clean      remove build/ first
set -euo pipefail
cd "$(dirname "$0")"
[ "${1:-}" = clean ] && rm -rf build
if [ ! -f build/build.ninja ]; then
  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DFLATBUFFERS_BUILD_TESTS=OFF \
    -DFLATBUFFERS_BUILD_FLATLIB=OFF -DFLATBUFFERS_BUILD_FLATHASH=OFF \
    -DCMAKE_CXX_COMPILER=/usr/bin/x86_64-linux-gnu-g++-12 >/dev/null
fi
ninja -C build flatc
