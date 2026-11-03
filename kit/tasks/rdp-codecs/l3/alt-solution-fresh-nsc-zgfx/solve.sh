#!/usr/bin/env bash
# l3 variant alt-solution-fresh-nsc-zgfx: must reach 1.0. The upstream sources for five codecs, plus
# NSCodec (nsc.c) and ZGFX (zgfx.c) decoders written independently from /app/docs/bitmap-codecs.txt, so a
# second implementation of those formats must pass every case (checks that the notes are sufficient and
# that the grader does not depend on upstream's internal structure).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
cd /app && ./build.sh >/dev/null
