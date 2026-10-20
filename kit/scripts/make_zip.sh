#!/usr/bin/env bash
# make_zip.sh: deterministic submission zip of tasks/<task>/harbor/ (written 2026-10-20).
#
#   make_zip.sh <task>      -> tasks/<task>/build/<task>.zip with task.toml at the zip root
#
# Refuses unless L0 passes. Sorted entries, fixed timestamps and modes, so the same files give the same zip.
set -euo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SELF_DIR/.." && pwd)"
TASK="${1:?usage: make_zip.sh <task>}"
H="$ROOT/tasks/$TASK/harbor"; [ -d "$H" ] || { echo "make_zip.sh: $H missing" >&2; exit 2; }
"$HOME/.local/bin/uv" run --no-project --python 3.12 python -I "$SELF_DIR/l0_check.py" "$TASK" >/dev/null \
  || { echo "make_zip.sh: L0 fails; see tasks/$TASK/build/l0-report.md" >&2; exit 1; }
OUT="$ROOT/tasks/$TASK/build/$TASK.zip"
python3 -I - "$H" "$OUT" <<'PY'
import os, sys, zipfile
src, out = sys.argv[1], sys.argv[2]
files = sorted(os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for rel in files:
        p = os.path.join(src, rel)
        zi = zipfile.ZipInfo(rel, date_time=(2020, 1, 1, 0, 0, 0))
        zi.external_attr = (0o755 if os.access(p, os.X_OK) else 0o644) << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        data = open(p, "rb").read()
        if rel == "task.toml":       # the repo holds the placeholder "cg/"; the zip gets the private prefix
            org = open(os.path.expanduser("~/.config/cgpipe/org")).read().strip()
            data = data.replace(b'name = "cg/', f'name = "{org}/'.encode(), 1)
        z.writestr(zi, data)
print(f"{out}: {len(files)} files, {os.path.getsize(out)} bytes")
PY
sha256sum "$OUT"
