#!/usr/bin/env bash
# l3 variant near-miss-wrong-shape: the reference data printed in a different JSON shape (cells as objects, sheets keyed by name).
# Expected score: 0 (builds, but no unit matches).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
