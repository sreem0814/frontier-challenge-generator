#!/usr/bin/env bash
# Reference solution: restores the bitmap codec implementations of FreeRDP 3.32.2 (interleaved RLE,
# planar, NSCodec, RemoteFX with RLGR/DWT/quantization, RemoteFX progressive) into /app/libfreerdp/codec
# and rebuilds the library. Produces the deliverable only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
cd /app && ./build.sh >/dev/null
echo "codec sources restored and library rebuilt"
