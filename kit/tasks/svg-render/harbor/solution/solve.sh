#!/usr/bin/env bash
# Reference renderer: the resvg 0.48 pipeline (usvg tree builder + tiny-skia rasterizer), vendored as
# source under ref/, behind the svgrender CLI in ref/src/main.rs. It replaces the starter crate in /app
# and builds offline exactly the way the grader rebuilds the workspace.
set -euo pipefail
REF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ref"
cd /app
rm -rf src Cargo.toml Cargo.lock .cargo crates vendor target
cp -a "$REF"/. /app/
cargo build --release --offline
first="$(find samples -name '*.svg' | LC_ALL=C sort | head -1)"
./target/release/svgrender --width 300 "$first" /tmp/svgrender-smoke.png
rm -f /tmp/svgrender-smoke.png
