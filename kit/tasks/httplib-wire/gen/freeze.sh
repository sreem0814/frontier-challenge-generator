#!/bin/bash
# gen/freeze.sh: build the frozen case set and the samples (run inside the dev container, /w = task dir).
# Needs the probe/server builds in /w/build (bh.sh) for ref, stub (h/), noH..noN.
set -e
cd /w/build
python3 -I /w/gen/write_candidates.py cand_hidden.jsonl.gz 20261021 h 3
python3 -I /w/gen/write_candidates.py cand_sample.jsonl.gz 777 s 1
/w/gen/run_all.sh /w/build/cand_hidden.jsonl.gz /w/build/rh
/w/gen/run_all.sh /w/build/cand_sample.jsonl.gz /w/build/rs
python3 -I /w/gen/build_set.py /w/harbor/tests cand_hidden.jsonl.gz rh set_hidden.jsonl.gz
python3 -I /w/gen/build_set.py /w/harbor/tests cand_sample.jsonl.gz rs set_sample.jsonl.gz
