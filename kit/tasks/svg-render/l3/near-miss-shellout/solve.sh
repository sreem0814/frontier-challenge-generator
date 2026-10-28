#!/usr/bin/env bash
# l3 variant near-miss-shellout: no renderer of its own; it shells out to a system SVG converter
# (rsvg-convert, inkscape, ImageMagick). None is installed, so every case fails and it must score exactly 0.
set -euo pipefail
cd /app
cat > src/main.rs <<'RS'
use std::process::{Command, ExitCode};
fn main() -> ExitCode {
    let a: Vec<String> = std::env::args().collect();
    let (inp, out) = (&a[a.len() - 2], &a[a.len() - 1]);
    let tries: [Vec<String>; 3] = [
        vec!["rsvg-convert".into(), "-w".into(), "300".into(), "-o".into(), out.clone(), inp.clone()],
        vec!["inkscape".into(), inp.clone(), "--export-width=300".into(), format!("--export-filename={out}")],
        vec!["convert".into(), "-background".into(), "none".into(), inp.clone(), format!("png32:{out}")],
    ];
    for t in tries.iter() {
        if let Ok(s) = Command::new(&t[0]).args(&t[1..]).status() {
            if s.success() {
                return ExitCode::SUCCESS;
            }
        }
    }
    ExitCode::from(1)
}
RS
cargo build --release --offline
