#!/usr/bin/env bash
# l3 variant near-miss-tamper-base: must score 0 (gate: pristine tree modified). The full upstream
# decoders, plus an edit to the read-only starting copy in /usr/src/freerdp-3.32.2.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
echo "/* local note */" >> /usr/src/freerdp-3.32.2/libfreerdp/codec/color.c
cd /app && ./build.sh >/dev/null
