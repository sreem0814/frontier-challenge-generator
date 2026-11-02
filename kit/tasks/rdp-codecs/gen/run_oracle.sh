#!/usr/bin/env bash
# run_oracle.sh <case dir> [jobs]: decode DIR/cases.bin with the pristine 3.32.2 build (in the authoring
# container); results to DIR/oracle.txt. Builds harness/codec_runner_oracle on first use.
set -euo pipefail
D="$1"; J="${2:-4}"; DUMP="${3:-}"
G="$(cd "$(dirname "$0")" && pwd)"
P=pristine/freerdp-3.32.2; B=oracle-build
docker run --rm --user "$(id -u):$(id -g)" -v "$G":/w -w /w -e D="$D" -e J="$J" -e DUMP="$DUMP" -e P="$P" -e B="$B" cg-rdp-author bash -c '
set -e
[ -n "$DUMP" ] && mkdir -p "$DUMP"
if [ ! -x harness/codec_runner_oracle ] || [ harness/codec_runner.c -nt harness/codec_runner_oracle ]; then
  gcc -O2 -Wall -o harness/codec_runner_oracle harness/codec_runner.c -I$P/include -I$B/include -I$P/winpr/include \
    -I$B/winpr/include -L$B/libfreerdp -L$B/winpr/libwinpr -lfreerdp3 -lwinpr3 \
    -Wl,-rpath,/w/$B/libfreerdp -Wl,-rpath,/w/$B/winpr/libwinpr
fi
python3 -I casegen/shard.py "$D/cases.bin" "$J" "$D/shard"
ls "$D"/shard.*.bin | xargs -P "$J" -I{} sh -c "WLOG_LEVEL=WARN harness/codec_runner_oracle {} --timeout 60 --logdir /tmp ${DUMP:+--dump $DUMP} > {}.out"
cat "$D"/shard.*.bin.out > "$D/oracle.txt"; rm -f "$D"/shard.*
'
wc -l "$D/oracle.txt"
