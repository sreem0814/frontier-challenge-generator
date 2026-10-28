#!/usr/bin/env bash
# l3 variant alt-solution-scalar: a differently built and differently encoded renderer that is still correct.
# tiny-skia runs its scalar pipelines (no SIMD), straight alpha is computed with truncation instead of
# rounding, and the PNG writer picks greyscale, RGB, palette+tRNS or RGBA per image and filters every row
# with Paeth. Must reach 1: the grader must not depend on the reference's exact bytes or PNG flavour.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
python3 - <<'PY'
p = "crates/resvg/Cargo.toml"; s = open(p).read()
old = 'features = ["std", "simd"]'
assert old in s; open(p, "w").write(s.replace(old, 'features = ["std"]'))
p = "src/main.rs"; s = open(p).read()
old = "*c = ((*c as f64) / af + 0.5).min(255.0) as u8;"
assert old in s; s = s.replace(old, "*c = ((*c as f64) / af).min(255.0) as u8;")
old = "Ok(png::encode_rgba(size.width(), size.height(), &rgba))"
assert old in s; s = s.replace(old, "Ok(altpng::encode(size.width(), size.height(), &rgba))")
s += '''
mod altpng {
    use std::collections::HashMap;

    pub fn encode(w: u32, h: u32, rgba: &[u8]) -> Vec<u8> {
        let px: Vec<[u8; 4]> = rgba.chunks_exact(4).map(|p| [p[0], p[1], p[2], p[3]]).collect();
        let opaque = px.iter().all(|p| p[3] == 255);
        let grey = opaque && px.iter().all(|p| p[0] == p[1] && p[1] == p[2]);
        let mut palette: HashMap<[u8; 4], u8> = HashMap::new();
        let mut order: Vec<[u8; 4]> = Vec::new();
        let mut fits = true;
        for p in &px {
            if !palette.contains_key(p) {
                if order.len() == 256 { fits = false; break; }
                palette.insert(*p, order.len() as u8);
                order.push(*p);
            }
        }
        let (ctype, bpp, samples): (u8, usize, Vec<u8>) = if grey {
            (0, 1, px.iter().map(|p| p[0]).collect())
        } else if fits && !opaque {
            (3, 1, px.iter().map(|p| palette[p]).collect())
        } else if opaque {
            (2, 3, px.iter().flat_map(|p| [p[0], p[1], p[2]]).collect())
        } else {
            (6, 4, rgba.to_vec())
        };
        let stride = w as usize * bpp;
        let mut raw = Vec::with_capacity((stride + 1) * h as usize);
        for y in 0..h as usize {
            raw.push(4u8);
            for x in 0..stride {
                let cur = samples[y * stride + x] as i16;
                let a = if x >= bpp { samples[y * stride + x - bpp] as i16 } else { 0 };
                let b = if y > 0 { samples[(y - 1) * stride + x] as i16 } else { 0 };
                let c = if x >= bpp && y > 0 { samples[(y - 1) * stride + x - bpp] as i16 } else { 0 };
                let p = a + b - c;
                let (pa, pb, pc) = ((p - a).abs(), (p - b).abs(), (p - c).abs());
                let pred = if pa <= pb && pa <= pc { a } else if pb <= pc { b } else { c };
                raw.push((cur - pred) as u8);
            }
        }
        let mut out = vec![0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];
        let mut ihdr = Vec::new();
        ihdr.extend_from_slice(&w.to_be_bytes());
        ihdr.extend_from_slice(&h.to_be_bytes());
        ihdr.extend_from_slice(&[8, ctype, 0, 0, 0]);
        chunk(&mut out, b"IHDR", &ihdr);
        if ctype == 3 {
            let plte: Vec<u8> = order.iter().flat_map(|p| [p[0], p[1], p[2]]).collect();
            let trns: Vec<u8> = order.iter().map(|p| p[3]).collect();
            chunk(&mut out, b"PLTE", &plte);
            chunk(&mut out, b"tRNS", &trns);
        }
        let mut z = vec![0x78, 0x01];
        let blocks: Vec<&[u8]> = raw.chunks(65535).collect();
        for (i, b) in blocks.iter().enumerate() {
            z.push(if i + 1 == blocks.len() { 1 } else { 0 });
            z.extend_from_slice(&(b.len() as u16).to_le_bytes());
            z.extend_from_slice(&(!(b.len() as u16)).to_le_bytes());
            z.extend_from_slice(b);
        }
        let (mut s1, mut s2) = (1u32, 0u32);
        for &x in &raw { s1 = (s1 + x as u32) % 65521; s2 = (s2 + s1) % 65521; }
        z.extend_from_slice(&((s2 << 16) | s1).to_be_bytes());
        chunk(&mut out, b"IDAT", &z);
        chunk(&mut out, b"IEND", &[]);
        out
    }

    fn chunk(out: &mut Vec<u8>, kind: &[u8], body: &[u8]) {
        out.extend_from_slice(&(body.len() as u32).to_be_bytes());
        let mut crc = 0xFFFF_FFFFu32;
        for &b in kind.iter().chain(body.iter()) {
            crc ^= b as u32;
            for _ in 0..8 { crc = if crc & 1 != 0 { 0xEDB8_8320 ^ (crc >> 1) } else { crc >> 1 }; }
        }
        out.extend_from_slice(kind);
        out.extend_from_slice(body);
        out.extend_from_slice(&(crc ^ 0xFFFF_FFFF).to_be_bytes());
    }
}
'''
open(p, "w").write(s)
PY
cargo build --release --offline
