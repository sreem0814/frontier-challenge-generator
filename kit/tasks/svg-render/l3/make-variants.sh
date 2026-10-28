#!/usr/bin/env bash
# Copy harbor/solution/ref/ into every l3 variant that needs it (variants with a NEEDS_REF marker file).
# Run before kit/scripts/l3_run.sh; the copies are git-ignored (../.gitignore).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for v in "$HERE"/*/; do
  [ -f "$v/NEEDS_REF" ] || continue
  rsync -a --delete "$HERE/../harbor/solution/ref/" "$v/ref/"
  echo "ref -> ${v%/}"
done
