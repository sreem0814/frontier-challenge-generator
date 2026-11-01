#!/usr/bin/env bash
# l3 variant partial-codec-only: only proto/codec is implemented (the reference codecs); obfuscation, crypto and
# exchange stay stubs. Must land strictly between 0 and 1, near the codec weight.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd /app
find proto/codec -maxdepth 1 -name '*.go' -delete
cp "$HERE/ref/proto/codec"/*.go proto/codec/
go build ./...
