#!/usr/bin/env bash
# l3 variant near-miss-unsafe: the full reference plus one helper in crypto that imports unsafe. Builds and passes
# every case, but the forbidden-import gate must score it exactly 0.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd /app
for d in proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc; do
  find "$d" -maxdepth 1 -name '*.go' -delete
  cp "$HERE/ref/$d"/*.go "$d/"
done
cp "$HERE/xor_fast.go" crypto/xor_fast.go
go build ./...
