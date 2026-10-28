#!/usr/bin/env bash
# l3 variant near-miss-wrong-format: the real renderer, but it writes binary PPM/PAM (P7 RGBA) instead of PNG.
# Every output is unreadable as PNG, so it must score exactly 0 ("unreadable PNG").
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "src/main.rs"; s = open(p).read()
old = "Ok(png::encode_rgba(size.width(), size.height(), &rgba))"
new = '''{
        let mut out = format!("P7\\nWIDTH {}\\nHEIGHT {}\\nDEPTH 4\\nMAXVAL 255\\nTUPLTYPE RGB_ALPHA\\nENDHDR\\n", size.width(), size.height()).into_bytes();
        out.extend_from_slice(&rgba);
        let _ = png::encode_rgba;
        Ok(out)
    }'''
assert old in s; open(p, "w").write(s.replace(old, new))
PY
cargo build --release --offline
