#!/usr/bin/env bash
# l3 variant edge-outside-shift14: the reference, then +14 on every premultiplied channel of every pixel (alpha included,
# clamped at 255) before the PNG is written. A uniform error of 14 levels is outside the 10-level tolerance on every pixel, transparent ones included: must score exactly 0.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "src/main.rs"; s = open(p).read()
old = "    let mut rgba = pixmap.take();\n"
new = "    let mut rgba = pixmap.take();\n    for v in rgba.iter_mut() { *v = v.saturating_add(14); }\n"
assert old in s; open(p, "w").write(s.replace(old, new))
PY
cargo build --release --offline
