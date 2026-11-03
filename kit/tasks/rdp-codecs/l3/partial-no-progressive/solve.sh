#!/usr/bin/env bash
# l3 variant partial-no-progressive: must land strictly between 0 and 1 (about 0.73). The upstream
# decoders for every codec except RemoteFX progressive, which stays a stub: the progressive bucket scores
# 0 and the six other buckets score 1.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
cd /app && ./build.sh >/dev/null
