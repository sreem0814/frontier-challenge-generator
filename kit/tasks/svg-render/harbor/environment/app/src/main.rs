//! svgrender: rasterize an SVG file to an RGBA PNG.
//!
//! Usage: svgrender [--width N] <input.svg> <output.png>
//!
//! This is the starting point: argument parsing only. Rendering is not implemented yet.

use std::process::ExitCode;

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
            width = Some(v.parse::<u32>().map_err(|_| format!("bad --width {v}"))?);
        } else if let Some(v) = a.strip_prefix("--width=") {
            width = Some(v.parse::<u32>().map_err(|_| format!("bad --width {v}"))?);
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

fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(a) => a,
        Err(e) => {
            eprintln!("{e}");
            return ExitCode::from(2);
        }
    };
    let _ = (args.width, &args.input, &args.output);
    eprintln!("svgrender: rendering is not implemented");
    ExitCode::from(1)
}
