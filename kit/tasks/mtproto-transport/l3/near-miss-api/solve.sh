#!/usr/bin/env bash
# l3 variant near-miss-api: the full reference, but RSAPublicDecrypt (unused by the callers) is renamed. The callers
# still build; selfcheck/api.go does not, so the clean-tree build gate must score it exactly 0.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd /app
for d in proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc; do
  find "$d" -maxdepth 1 -name '*.go' -delete
  cp "$HERE/ref/$d"/*.go "$d/"
done
sed -i 's/^func RSAPublicDecrypt(/func rsaPublicDecrypt(/' crypto/rsa.go
go build ./crypto ./exchange ./mtproto ./telegram
