#!/usr/bin/env bash
# l3 variant partial-core-only: the reference cell/formula/merged/names dump without the VBA, picture, property, table and pivot output (the per-sheet hyperlinks stay).
# Expected score: about 4/7 plus part of the objects bucket.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
