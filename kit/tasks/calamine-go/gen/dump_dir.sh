#!/usr/bin/env bash
# dump_dir.sh <workbook dir> <out dir>: run the calamine 0.37.0 dumper once per workbook (30 s cap each),
# inside the rust container with no network. A crash or timeout leaves no JSON (the case is not scored).
set -uo pipefail
IN="$1"; OUT="$2"
mkdir -p "$OUT"
for f in "$IN"/*; do
  case "$f" in *.xls|*.xlsx|*.xlsm|*.xlsb|*.ods) ;; *) continue ;; esac
  b=$(basename "$f")
  timeout 30 /w/jdump/target/release/jdump "$OUT" "$f" >/dev/null 2>&1 || { rm -f "$OUT/$b.json"; echo "dump failed: $b"; }
done
