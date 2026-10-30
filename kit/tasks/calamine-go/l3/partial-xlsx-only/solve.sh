#!/usr/bin/env bash
# l3 variant partial-xlsx-only: only the xlsx reader is wired in; xls, xlsb and ods report errors.
# Expected score: about 0.25.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
