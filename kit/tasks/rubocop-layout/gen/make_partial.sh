#!/bin/sh
# make_partial.sh <out dir> <cop file regex>: stub tree + reference files for matching Layout cops + all removed mixins/correctors
set -e
out=$1; re=$2
rm -rf "$out"; mkdir -p "$out"; cp -r /app/rubocop/lib "$out/lib"
for f in /dev0/ref/lib/rubocop/cop/layout/*.rb; do b=$(basename $f .rb); if echo "$b" | grep -Eq "$re"; then cp "$f" "$out/lib/rubocop/cop/layout/"; fi; done
for f in /dev0/ref/lib/rubocop/cop/mixin/*.rb /dev0/ref/lib/rubocop/cop/correctors/*.rb; do d=$out/lib/${f#/dev0/ref/lib/}; [ -f "$d" ] || cp "$f" "$d"; done
