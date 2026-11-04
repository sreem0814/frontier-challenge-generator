#!/usr/bin/env bash
# freeze.sh: regenerate the hidden set (seed 7301) and the samples (seed 4409) and freeze them into the bundle.
# Runs inside the authoring image: docker run -v <build/w>:/w -v <gen>:/g -v <harbor>:/hb cg-matter-author /g/freeze.sh
set -euo pipefail
cd /w
python3 -I /g/casegen.py --seed 7301 --scale 1.0 --prefix h > hidden_cases.txt
python3 -I /g/casegen.py --seed 4409 --scale 0.12 --prefix s > sample_cases.txt
for r in rfull rsan rstub; do ninja -C /w/$r >/dev/null; done
for set in hidden sample; do
  for i in 1 2 3; do /w/rfull/case_runner ${set}_cases.txt > $set.ref$i.out; done
  timeout 1200 setarch x86_64 -R /w/rsan/case_runner ${set}_cases.txt > $set.san.out 2>/dev/null || true
  /w/rstub/case_runner ${set}_cases.txt > $set.stub.out
done
python3 -I /g/freeze.py /w /hb || true
