#!/usr/bin/env bash
# l3 variant near-miss-read-expected: xlsdump looks for the grader's expected dump under /tests instead of parsing the workbook (the candidate uid cannot read /tests while it runs).
# Expected score: 0 (no output for any workbook).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
