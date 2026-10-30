#!/usr/bin/env bash
# l3 variant near-miss-shellout: xlsdump hands the file to an external interpreter through os/exec instead of parsing it in Go (the system-tool shortcut).
# Expected score: 0 (forbidden construct: os/exec).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DST=/app/calamine-go
mkdir -p "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"
