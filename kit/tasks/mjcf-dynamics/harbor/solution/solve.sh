#!/usr/bin/env bash
# Reference solution: installs the full mjlite package (MJCF compiler, smooth dynamics, integrators, sensors)
# over the skeleton in /app/mjlite. Produces the deliverable only.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -rf /app/mjlite
mkdir -p /app/mjlite
cp "$HERE"/mjlite/*.py /app/mjlite/
python3 /app/tools/selfcheck.py -j 4 | tail -3
