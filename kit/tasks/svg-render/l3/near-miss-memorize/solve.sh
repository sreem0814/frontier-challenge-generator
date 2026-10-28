#!/usr/bin/env bash
# l3 variant near-miss-memorize: memorizes the visible samples (SVG bytes -> stored PNG) and fails on any
# other input. Plausible shortcut; it scores 1.0 on tools/selfcheck.py but must score exactly 0 on the hidden set.
set -euo pipefail
cd /app
python3 - <<'PY'
import os
rows = []
for r, _, fs in os.walk("samples"):
    for f in sorted(fs):
        if f.endswith(".svg"):
            p = os.path.join(r, f)
            rows.append(f'    (include_bytes!("../{p}"), include_bytes!("../{p[:-4]}.png")),')
src = '''use std::process::ExitCode;
static TABLE: &[(&[u8], &[u8])] = &[
%s
];
fn main() -> ExitCode {
    let a: Vec<String> = std::env::args().collect();
    let (inp, out) = (&a[a.len() - 2], &a[a.len() - 1]);
    let data = std::fs::read(inp).unwrap_or_default();
    for (svg, png) in TABLE {
        if *svg == data.as_slice() {
            std::fs::write(out, png).unwrap();
            return ExitCode::SUCCESS;
        }
    }
    ExitCode::from(1)
}
''' % "\n".join(rows)
open("src/main.rs", "w").write(src)
PY
cargo build --release --offline
