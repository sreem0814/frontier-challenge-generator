#!/usr/bin/env bash
# l3 variant partial-bitmap-updates: must land strictly between 0 and 1 (about 0.45). Only the
# interleaved, planar, NSCodec and ClearCodec decoders are restored; RemoteFX, progressive and ZGFX stay
# stubs.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
cd /app && ./build.sh >/dev/null
