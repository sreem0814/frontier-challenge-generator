#!/usr/bin/env bash
# l3 variant partial-no-filters: the reference with every filter skipped (the filtered group is drawn as if it
# had no filter). Real but incomplete work: must land strictly between 0 and 1.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "crates/resvg/src/render.rs"; s = open(p).read()
old = "crate::filter::apply(filter, transform, &mut sub_pixmap);"
assert old in s; open(p, "w").write(s.replace(old, "let _ = (filter, &sub_pixmap);"))
PY
cargo build --release --offline
