#!/usr/bin/env bash
# l3 variant partial-core-1: the narrow solution of build/core.json, the part a strong agent writes first: the
# reference codecs, obfuscation and crypto package; exchange, mtproto, mtproto/salts and rpc stay stubs. Must land
# strictly between 0 and 1, within 0.1 of core_share.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd /app
for d in proto/codec mtproxy/obfuscated2 crypto; do
  find "$d" -maxdepth 1 -name '*.go' -delete
  cp "$HERE/ref/$d"/*.go "$d/"
done
go build ./...
