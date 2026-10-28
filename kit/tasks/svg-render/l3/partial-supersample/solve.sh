#!/usr/bin/env bash
# l3 variant partial-supersample: the reference pipeline rendered at 4x and box-filtered down (a different
# anti-aliasing method). Pattern tiles then come out sharper than the contract's device-resolution tiles, so a
# few pattern cases fail: it must land strictly between 0 and 1, close to 1 (about 0.99).
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "src/main.rs"; s = open(p).read()
old = '''    let mut pixmap = tiny_skia::Pixmap::new(size.width(), size.height()).ok_or("cannot allocate the image")?;
    let ts = tiny_skia::Transform::from_scale(
        size.width() as f32 / tree.size().width(),
        size.height() as f32 / tree.size().height(),
    );
    resvg::render(&tree, ts, &mut pixmap.as_mut());

    let mut rgba = pixmap.take();'''
new = '''    const K: u32 = 4;
    let mut big = tiny_skia::Pixmap::new(size.width() * K, size.height() * K).ok_or("cannot allocate the image")?;
    let ts = tiny_skia::Transform::from_scale(
        (size.width() * K) as f32 / tree.size().width(),
        (size.height() * K) as f32 / tree.size().height(),
    );
    resvg::render(&tree, ts, &mut big.as_mut());
    let bw = (size.width() * K) as usize;
    let src = big.data();
    let mut rgba = vec![0u8; (size.width() * size.height() * 4) as usize];
    for y in 0..size.height() as usize {
        for x in 0..size.width() as usize {
            for c in 0..4 {
                let mut s = 0u32;
                for dy in 0..K as usize {
                    for dx in 0..K as usize {
                        s += src[((y * K as usize + dy) * bw + x * K as usize + dx) * 4 + c] as u32;
                    }
                }
                rgba[(y * size.width() as usize + x) * 4 + c] = ((s + (K * K / 2)) / (K * K)) as u8;
            }
        }
    }'''
assert old in s; open(p, "w").write(s.replace(old, new))
PY
cargo build --release --offline
