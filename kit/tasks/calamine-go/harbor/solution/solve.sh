#!/usr/bin/env bash
# Reference solution: installs the Go port of calamine 0.37.0 (solution/calamine-go/) into /app/calamine-go.
# It produces the deliverable only; it never writes /logs/verifier or touches /tests.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
cd "$DST"
export GOFLAGS=-mod=vendor GOTOOLCHAIN=local GOPROXY=off CGO_ENABLED=0
/usr/local/go/bin/go vet -buildvcs=false ./calamine ./cmd/xlsdump
/usr/local/go/bin/go build -buildvcs=false -trimpath -o /tmp/xlsdump-reference ./cmd/xlsdump
echo "reference installed in $DST (test build: /tmp/xlsdump-reference)"
