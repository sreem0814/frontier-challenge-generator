#!/usr/bin/env bash
# Configure (first run only) and build the parts of Fluent Bit this task needs.
# The grader uses exactly these cmake options and targets on a fresh copy of the tree.
set -euo pipefail
SRC=/app/fluent-bit
BUILD=${BUILD_DIR:-/app/fluent-bit/build}
JOBS=${JOBS:-8}
if [ ! -f "$BUILD/CMakeCache.txt" ]; then
  cmake -S "$SRC" -B "$BUILD" \
    -DFLB_TESTS_RUNTIME=On -DFLB_TESTS_INTERNAL=On -DFLB_USE_SIMDUTF=No \
    -DFLB_WASM=No -DFLB_LUAJIT=No -DFLB_KAFKA=No -DFLB_EXAMPLES=No -DFLB_BACKTRACE=No \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=On >/dev/null
fi
make -C "$BUILD" -j"$JOBS" fluent-bit-shared fluent-bit-bin flb-rt-filter_modify flb-it-record_accessor
