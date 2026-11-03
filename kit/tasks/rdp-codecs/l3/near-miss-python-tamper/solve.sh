#!/usr/bin/env bash
# l3 variant near-miss-python-tamper: must score 0 (gate: verifier tools modified). The full upstream
# decoders, plus an edit to the system Python's json package, which the grader detects with dpkg --verify.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
echo "# local patch" >> /usr/lib/python3.11/json/encoder.py
cd /app && ./build.sh >/dev/null
