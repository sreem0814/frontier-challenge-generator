#!/usr/bin/env bash
# l3 variant near-miss-unlinked-files: must score 0. The full upstream decoders, but saved as new files
# (restored_*.c) that no listed file includes. The build file list is fixed, so they are never compiled
# and the listed files stay stubs.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
cd /app && ./build.sh >/dev/null
