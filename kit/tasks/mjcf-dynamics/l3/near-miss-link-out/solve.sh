#!/usr/bin/env bash
# l3 near-miss-link-out: the full reference plus a symbolic link from the package to the grader's data directory,
# which would expose reference outputs if the snapshot followed it. Must score 0: links in the package are a gate.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rm -rf /app/mjlite && mkdir -p /app/mjlite && cp "$HERE"/mjlite/*.py /app/mjlite/
ln -s /tests/data /app/mjlite/answers
