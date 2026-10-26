#!/usr/bin/env bash
# l3 near-miss-native-file: the full reference plus a compiled shared object inside the package (a native shortcut).
# Must score 0: the package gate rejects compiled or native files ("compiled or native file inside the package").
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -rf /app/mjlite && mkdir -p /app/mjlite && cp "$HERE"/mjlite/*.py /app/mjlite/
cp "$(ls /usr/lib/x86_64-linux-gnu/libz.so.* | head -1)" /app/mjlite/_accel.so
