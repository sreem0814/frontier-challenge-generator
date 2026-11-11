#!/usr/bin/env bash
# Regenerate and freeze both splits inside the author container (cg-matter-author: Debian 12, gcc 12, CMake
# 3.25, Ninja, Python 3.11) with this task dir at /t, build/w at /w and gen/ at /g:
#   /w/up       upstream tree at 7e16302 (corpus: /w/up/tests)
#   /w/bref2    flatc built from the pruned tree + upstream src/idl_parser.cpp (the reference)
#   /w/bstub    flatc built from the pruned tree + the stub
# Hidden: seed 52031 scale 1.0; samples: seed 9187 scale 0.12. Then, outside the container:
#   python3 -I gen/finalize.py build/w/fz_hidden build/w/fz_sample harbor
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1 FBTESTS=/t/harbor/tests JOBS=${JOBS:-4}
cd /g
python3 casegen.py 52031 1.0 /w/hidden.json --corpus /w/up/tests
python3 casegen.py 9187 0.12 /w/sample.json --corpus /w/up/tests
rm -rf /w/fz_hidden /w/fz_sample
python3 -I freeze.py /w/hidden.json /w/bref2/flatc /w/bstub/flatc /w/fz_hidden
python3 -I freeze.py /w/sample.json /w/bref2/flatc /w/bstub/flatc /w/fz_sample --samples
