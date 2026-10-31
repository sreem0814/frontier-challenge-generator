#!/usr/bin/env bash
# Reference solution: the upstream implementation of the four packages at gotd/td v0.162.0 (solution/ref/,
# unmodified MIT source), copied over the API stubs. It writes only under /app and never touches /tests or
# the verifier's log directory.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)/ref"
cd /app
for d in proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc; do
  find "$d" -maxdepth 1 -name '*.go' -delete
  cp "$SRC/$d"/*.go "$d/"
done
go build ./...
echo "reference installed"
