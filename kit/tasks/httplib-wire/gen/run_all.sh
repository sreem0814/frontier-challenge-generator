#!/bin/bash
# gen/run_all.sh <cand.jsonl.gz> <results dir>: run candidates on every build (inside the dev container, /w = task dir)
set -e
C=$1; D=$2; mkdir -p $D
run() { python3 -I /w/gen/run_variant.py /w/harbor/tests $C /w/build/$1_probe /w/build/$1_server $D/$2.json --port $3; }
run ref ref1 21000; run ref ref2 21100
# third reference run under CPU load (compiles in the background), like a graded run where the suite compiles
( for i in 1 2 3 4; do g++ -std=c++17 -O1 -I/w/build/ref -fsyntax-only /w/harbor/tests/harness/probe.cc & done; wait; \
  for i in 1 2 3 4; do g++ -std=c++17 -O1 -I/w/build/ref -fsyntax-only /w/harbor/tests/harness/server.cc & done; wait ) &
LOAD=$!
run ref ref3 21200; wait $LOAD; run stub stub 21300; run stub stub2 21300
for v in noH noB noQ noM noR noN core; do run $v $v 21400; done
