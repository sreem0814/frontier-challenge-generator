#!/usr/bin/env bash
# l3 variant alt-solution-json: the reference library with a different JSON writer (encoding/json, indented, keys in another order, floats in exponent form). Shows the grader compares values, not bytes.
# Expected score: the ceiling (1.0).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
