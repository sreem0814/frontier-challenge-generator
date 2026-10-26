#!/usr/bin/env bash
# l3 partial-kinematics-only: the reference with whole features removed (compiler and position stage only; no forces, accelerations, inverse dynamics or stepping).
# Must land strictly between 0 and 1.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -rf /app/mjlite && mkdir -p /app/mjlite && cp "$HERE"/mjlite/*.py /app/mjlite/
