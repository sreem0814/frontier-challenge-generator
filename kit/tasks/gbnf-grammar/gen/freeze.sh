#!/usr/bin/env bash
# freeze.sh <seed> <scale> <prefix> <outdir>: generate one case set and run it through the reference and stub runners.
# Runs inside the authoring image with /w = build/w and /g = gen.
set -euo pipefail
SEED=$1 SCALE=$2 PFX=$3 D=/w/$4
mkdir -p "$D"
cd /w
python3 -I /g/casegen.py stage1 --seed "$SEED" --scale "$SCALE" --prefix "$PFX" --dir "$D"
./rref "$D/lconv.txt" --models full/models > "$D/lconv.out"
python3 -I /g/casegen.py lwalk --dir "$D"
./walker "$D/walk.txt" > "$D/walk.out"
python3 -I /g/casegen.py stage2 --dir "$D"
for i in 1 2 3; do ./rref "$D/cases.txt" --models full/models > "$D/ref$i.out"; done
./rstub "$D/cases.txt" --models full/models > "$D/stub.out"
./refmatch "$D/lmatch.txt" > "$D/lmatch.out"
echo "freeze.sh: $D done"
