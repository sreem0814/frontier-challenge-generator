#!/usr/bin/env bash
# l3 variant near-miss-vendored-dep: imports a module the agent dropped into vendor/ and go.mod by hand; the grader restores the shipped go.mod, go.sum and vendor/ before building.
# Expected score: 0 (go build fails).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
mkdir -p "$DST/vendor/github.com/acme"
cp -a "$HERE/vendored/github.com/acme/xlsfast" "$DST/vendor/github.com/acme/"
printf '\nrequire github.com/acme/xlsfast v0.1.0\n' >> "$DST/go.mod"
printf '# github.com/acme/xlsfast v0.1.0\n## explicit\ngithub.com/acme/xlsfast\n' >> "$DST/vendor/modules.txt"
cd "$DST" && GOFLAGS=-mod=vendor CGO_ENABLED=0 /usr/local/go/bin/go build -buildvcs=false -o /tmp/xlsdump-variant ./cmd/xlsdump
