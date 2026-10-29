#!/usr/bin/env bash
# devbuild.sh: overlay the reference source on the shipped skeleton and build xlsdump into build/dev/xlsdump.
set -euo pipefail
T="$(cd "$(dirname "$0")/.." && pwd)"
SP=/tmp/claude-1000/-work-af-cg/790052d4-316c-4b98-bfcd-790db65c9691/scratchpad/im014
D="$T/build/dev/calamine-go"
rm -rf "$D"; mkdir -p "$D"
cp -a "$T/harbor/environment/calamine-go/." "$D/"
tar -xzf "$T/harbor/environment/calamine-go-vendor.tar.gz" -C "$D"
cp -a "$T/harbor/solution/calamine-go/." "$D/"
cd "$D"
export GOPATH=$SP/gopath GOMODCACHE=$SP/gopath/mod GOFLAGS=-mod=vendor GOTOOLCHAIN=local CGO_ENABLED=0 GOCACHE=$SP/gocache
$SP/go/bin/go vet ./... 2>&1 | grep -v "^#" | head -20 || true
$SP/go/bin/go build -trimpath -o "$T/build/dev/xlsdump" ./cmd/xlsdump
echo "built $T/build/dev/xlsdump"
