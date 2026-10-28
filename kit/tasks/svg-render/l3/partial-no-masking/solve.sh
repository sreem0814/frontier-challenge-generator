#!/usr/bin/env bash
# l3 variant partial-no-masking: the reference with clip paths and masks ignored (content is drawn unclipped
# and unmasked). Real but incomplete work: must land strictly between 0 and 1.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "crates/resvg/src/render.rs"; s = open(p).read()
for old in ("crate::clip::apply(clip_path, transform, &mut sub_pixmap);",
            "crate::mask::apply(mask, ctx, transform, &mut sub_pixmap);"):
    assert old in s
    s = s.replace(old, "let _ = (&sub_pixmap, transform);")
s = s.replace("if let Some(clip_path) = group.clip_path()", "if let Some(_clip_path) = group.clip_path()")
s = s.replace("if let Some(mask) = group.mask()", "if let Some(_mask) = group.mask()")
open(p, "w").write(s)
PY
cargo build --release --offline
