#!/usr/bin/env bash
# l3 variant alt-solution-1: the upstream reference with seven files replaced by independent variants that are
# equally valid but read randomness in other amounts and orders: Cipher.Encrypt (other padding policy),
# DecomposePQ (Pollard-Brent in uint64), the obfuscation init draw (56 + 8 bytes), the padded intermediate
# padding, RSA_PAD (temp key before padding), EncryptBindMessage (padding before prefix) and the exchange client
# (new_nonce first, b from raw bytes). Must reach the ceiling (1.0): the grader must not depend on how
# randomness is consumed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd /app
for d in proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc; do
  find "$d" -maxdepth 1 -name '*.go' -delete
  cp "$HERE/ref/$d"/*.go "$d/"
  if [ -d "$HERE/alt/$d" ]; then cp "$HERE/alt/$d"/*.go "$d/"; fi
done
go build ./...
