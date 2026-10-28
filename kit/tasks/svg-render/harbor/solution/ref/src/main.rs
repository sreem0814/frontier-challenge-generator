//! svgrender (reference build): the resvg 0.48 render pipeline (usvg tree + tiny-skia rasterizer)
//! behind the task's CLI contract.
//!
//! Usage: svgrender [--width N] <input.svg> <output.png>
//!
//! The output is an 8-bit RGBA PNG (straight alpha, sRGB). With `--width N` the image is scaled
//! uniformly so that its width is N pixels; the height keeps the aspect ratio (rounded up).
//! On any error nothing is written and the exit status is non-zero.

use std::io::Write;
use std::process::ExitCode;

use resvg::tiny_skia;
use resvg::usvg;

struct Args {
    width: Option<u32>,
    input: String,
    output: String,
}

fn parse_args() -> Result<Args, String> {
    let mut width = None;
    let mut positional = Vec::new();
    let mut it = std::env::args().skip(1);
    while let Some(a) = it.next() {
        if a == "--width" {
            let v = it.next().ok_or("--width needs a value")?;
            width = Some(parse_width(&v)?);
        } else if let Some(v) = a.strip_prefix("--width=") {
            width = Some(parse_width(v)?);
        } else {
            positional.push(a);
        }
    }
    if positional.len() != 2 {
        return Err("usage: svgrender [--width N] <input.svg> <output.png>".into());
    }
    let output = positional.pop().unwrap();
    let input = positional.pop().unwrap();
    Ok(Args { width, input, output })
}

fn parse_width(v: &str) -> Result<u32, String> {
    match v.parse::<u32>() {
        Ok(n) if n > 0 && n <= 16384 => Ok(n),
        _ => Err(format!("bad --width {v}")),
    }
}

fn render(args: &Args) -> Result<Vec<u8>, String> {
    let data = std::fs::read(&args.input).map_err(|e| format!("cannot read {}: {e}", args.input))?;
    let opt = usvg::Options::default();
    let tree = usvg::Tree::from_data(&data, &opt).map_err(|e| format!("cannot parse SVG: {e}"))?;

    let base = tree.size().to_int_size();
    let size = match args.width {
        Some(w) => base.scale_to_width(w).ok_or("cannot scale to the requested width")?,
        None => base,
    };
    let mut pixmap = tiny_skia::Pixmap::new(size.width(), size.height()).ok_or("cannot allocate the image")?;
    let ts = tiny_skia::Transform::from_scale(
        size.width() as f32 / tree.size().width(),
        size.height() as f32 / tree.size().height(),
    );
    resvg::render(&tree, ts, &mut pixmap.as_mut());

    let mut rgba = pixmap.take();
    demultiply(&mut rgba);
    Ok(png::encode_rgba(size.width(), size.height(), &rgba))
}

/// tiny-skia stores premultiplied RGBA; PNG wants straight alpha.
fn demultiply(data: &mut [u8]) {
    for p in data.chunks_exact_mut(4) {
        let a = p[3];
        if a != 0 && a != 255 {
            let af = a as f64 / 255.0;
            for c in &mut p[..3] {
                *c = ((*c as f64) / af + 0.5).min(255.0) as u8;
            }
        }
    }
}

fn write_atomically(path: &str, bytes: &[u8]) -> Result<(), String> {
    let tmp = format!("{path}.part");
    let mut f = std::fs::File::create(&tmp).map_err(|e| format!("cannot create {tmp}: {e}"))?;
    f.write_all(bytes).map_err(|e| format!("cannot write {tmp}: {e}"))?;
    f.sync_all().ok();
    drop(f);
    std::fs::rename(&tmp, path).map_err(|e| format!("cannot rename to {path}: {e}"))
}

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    match render(&args).and_then(|png| write_atomically(&args.output, &png)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("svgrender: {e}");
            let _ = std::fs::remove_file(&args.output);
            ExitCode::from(1)
        }
    }
}

/// A small PNG writer: 8-bit RGBA, filter 0 or 1 per row (whichever has the smaller sum of
/// absolute values), zlib stream made of stored deflate blocks. No compression library needed.
mod png {
    const SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A];

    pub fn encode_rgba(width: u32, height: u32, rgba: &[u8]) -> Vec<u8> {
        assert_eq!(rgba.len(), width as usize * height as usize * 4);
        let mut out = Vec::with_capacity(rgba.len() + rgba.len() / 8 + 1024);
        out.extend_from_slice(&SIGNATURE);

        let mut ihdr = Vec::with_capacity(13);
        ihdr.extend_from_slice(&width.to_be_bytes());
        ihdr.extend_from_slice(&height.to_be_bytes());
        ihdr.extend_from_slice(&[8, 6, 0, 0, 0]); // depth 8, RGBA, deflate, adaptive filter, no interlace
        chunk(&mut out, b"IHDR", &ihdr);

        let raw = filter_rows(width as usize, height as usize, rgba);
        chunk(&mut out, b"IDAT", &zlib_stored(&raw));
        chunk(&mut out, b"IEND", &[]);
        out
    }

    fn filter_rows(width: usize, height: usize, rgba: &[u8]) -> Vec<u8> {
        let stride = width * 4;
        let mut raw = Vec::with_capacity((stride + 1) * height);
        let mut sub = vec![0u8; stride];
        for y in 0..height {
            let row = &rgba[y * stride..(y + 1) * stride];
            for x in 0..stride {
                let left = if x >= 4 { row[x - 4] } else { 0 };
                sub[x] = row[x].wrapping_sub(left);
            }
            let cost = |r: &[u8]| r.iter().map(|&b| (b as i8).unsigned_abs() as u64).sum::<u64>();
            if cost(&sub) < cost(row) {
                raw.push(1);
                raw.extend_from_slice(&sub);
            } else {
                raw.push(0);
                raw.extend_from_slice(row);
            }
        }
        raw
    }

    fn zlib_stored(data: &[u8]) -> Vec<u8> {
        let mut z = Vec::with_capacity(data.len() + data.len() / 65535 * 5 + 16);
        z.extend_from_slice(&[0x78, 0x01]);
        let mut blocks = data.chunks(65535).peekable();
        if blocks.peek().is_none() {
            z.extend_from_slice(&[1, 0, 0, 0xFF, 0xFF]);
        }
        while let Some(block) = blocks.next() {
            let last = blocks.peek().is_none();
            z.push(if last { 1 } else { 0 });
            let len = block.len() as u16;
            z.extend_from_slice(&len.to_le_bytes());
            z.extend_from_slice(&(!len).to_le_bytes());
            z.extend_from_slice(block);
        }
        z.extend_from_slice(&adler32(data).to_be_bytes());
        z
    }

    fn chunk(out: &mut Vec<u8>, kind: &[u8; 4], body: &[u8]) {
        out.extend_from_slice(&(body.len() as u32).to_be_bytes());
        let start = out.len();
        out.extend_from_slice(kind);
        out.extend_from_slice(body);
        let crc = crc32(&out[start..]);
        out.extend_from_slice(&crc.to_be_bytes());
    }

    fn crc32(bytes: &[u8]) -> u32 {
        static TABLE: std::sync::OnceLock<[u32; 256]> = std::sync::OnceLock::new();
        let table = TABLE.get_or_init(|| {
            let mut t = [0u32; 256];
            for (n, slot) in t.iter_mut().enumerate() {
                let mut c = n as u32;
                for _ in 0..8 {
                    c = if c & 1 != 0 { 0xEDB8_8320 ^ (c >> 1) } else { c >> 1 };
                }
                *slot = c;
            }
            t
        });
        let mut c = 0xFFFF_FFFFu32;
        for &b in bytes {
            c = table[((c ^ b as u32) & 0xFF) as usize] ^ (c >> 8);
        }
        c ^ 0xFFFF_FFFF
    }

    fn adler32(bytes: &[u8]) -> u32 {
        const MOD: u32 = 65521;
        let (mut a, mut b) = (1u32, 0u32);
        for chunk in bytes.chunks(5552) {
            for &x in chunk {
                a += x as u32;
                b += a;
            }
            a %= MOD;
            b %= MOD;
        }
        (b << 16) | a
    }
}
