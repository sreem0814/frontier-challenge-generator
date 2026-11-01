#!/usr/bin/env bash
# l3 variant near-miss-tg: the full reference plus an edit to the generated package tg/ (outside the four
# packages; the grader cannot restore it from its snapshot). The integrity gate must score it exactly 0.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd /app
for d in proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc; do
  find "$d" -maxdepth 1 -name '*.go' -delete
  cp "$HERE/ref/$d"/*.go "$d/"
done
files=(tg/*.go)
printf '\n// local note\n' >> "${files[0]}"
go build ./tg
