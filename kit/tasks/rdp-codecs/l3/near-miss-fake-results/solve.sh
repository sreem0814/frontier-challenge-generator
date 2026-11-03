#!/usr/bin/env bash
# l3 variant near-miss-fake-results: must score 0. interleaved.c gains a constructor that prints a
# "success" result line for every sequence and step as soon as the library loads. The grader hashes the
# buffers the runner writes itself, so printed lines without the right image earn nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$HERE"/codec/. /app/libfreerdp/codec/
cd /app && ./build.sh >/dev/null
