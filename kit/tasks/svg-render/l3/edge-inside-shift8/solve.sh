#!/usr/bin/env bash
# l3 variant edge-inside-shift8: the reference, then +8 on every premultiplied channel of every pixel (alpha included,
# clamped at 255) before the PNG is written. A uniform error of 8 levels is inside the 10-level tolerance: must reach 1.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "src/main.rs"; s = open(p).read()
old = "    let mut rgba = pixmap.take();\n"
new = "    let mut rgba = pixmap.take();\n    for v in rgba.iter_mut() { *v = v.saturating_add(8); }\n"
assert old in s; open(p, "w").write(s.replace(old, new))
PY
cargo build --release --offline
