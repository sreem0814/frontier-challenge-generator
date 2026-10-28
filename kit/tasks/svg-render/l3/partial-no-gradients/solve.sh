#!/usr/bin/env bash
# l3 variant partial-no-gradients: the reference with linear and radial gradients painted as the solid colour
# of their first stop. Real but incomplete work: must land strictly between 0 and 1.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "crates/resvg/src/path.rs"; s = open(p).read()
n = 0
for kind, var in (("linear", "lg"), ("radial", "rg")):
    for op in ("fill.opacity()", "stroke.opacity()"):
        old = f"paint.shader = convert_{kind}_gradient({var}, {op})?;"
        if old in s:
            s = s.replace(old, f"solid_first_stop(&mut paint, {var}.stops(), {op});"); n += 1
assert n == 4, n
s += '''
fn solid_first_stop(paint: &mut tiny_skia::Paint, stops: &[usvg::Stop], opacity: usvg::Opacity) {
    if let Some(st) = stops.first() {
        let a = (st.opacity().get() * opacity.get() * 255.0).round().clamp(0.0, 255.0) as u8;
        paint.set_color_rgba8(st.color().red, st.color().green, st.color().blue, a);
    }
}
'''
open(p, "w").write(s)
PY
cargo build --release --offline
