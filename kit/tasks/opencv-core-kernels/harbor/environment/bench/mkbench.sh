#!/usr/bin/env bash
# mkbench.sh <opencv source dir> <opencv build dir> <output binary>: link cvbench against a static opencv_core build.
set -euo pipefail
SRC="$1"; B="$2"; OUT="$3"
HERE="$(cd "$(dirname "$0")" && pwd)"
EXTRA=$(ls "$B"/3rdparty/lib/*.a 2>/dev/null || true)
"${CXX:-g++}" -O2 -std=c++17 -static -I"$B" -I"$SRC/include" -I"$SRC/modules/core/include" "$HERE/cvbench.cpp" \
    "$B/lib/libopencv_core.a" $EXTRA -lz -ldl -lpthread -o "$OUT"
