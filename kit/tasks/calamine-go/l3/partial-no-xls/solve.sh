#!/usr/bin/env bash
# l3 variant partial-no-xls: the reference with the whole .xls reader switched off (OpenXls never called).
# Expected score: about 0.75 (the xls format scores 0).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
