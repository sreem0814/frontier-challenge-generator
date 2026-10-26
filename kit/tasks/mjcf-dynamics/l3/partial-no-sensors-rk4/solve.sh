#!/usr/bin/env bash
# l3 partial-no-sensors-rk4: the reference with whole features removed (sensordata left at zero, RK4 models stepped with Euler).
# Must land strictly between 0 and 1.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -rf /app/mjlite && mkdir -p /app/mjlite && cp "$HERE"/mjlite/*.py /app/mjlite/
