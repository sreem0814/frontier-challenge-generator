#!/usr/bin/env bash
# tests/test.sh: harden, collect evidence, then hand every scoring decision to compute_reward.py.
# The agent had root in this container until a moment ago, so trust nothing it could have touched.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH BASH_ENV ENV \
      GCONV_PATH PROMPT_COMMAND CDPATH CFLAGS CXXFLAGS LDFLAGS CPATH \
      CPLUS_INCLUDE_PATH C_INCLUDE_PATH LIBRARY_PATH GCC_EXEC_PREFIX COMPILER_PATH CCACHE_DIR
umask 022

# A loader preload would act on every dynamic program below (python3 included): move it aside and let
# collect.py record it as tampering.
if [ -e /etc/ld.so.preload ]; then mv -f /etc/ld.so.preload /etc/ld.so.preload.found; fi

OUT=/logs/verifier
mkdir -p "$OUT"
chown root:root "$OUT" 2>/dev/null; chmod 755 "$OUT"     # the candidate (uid 65534) must not write reward files
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json "$OUT"/evidence.json
chmod 700 /tests 2>/dev/null || true                      # candidate code must not read the verifier's files

# Leftovers from the agent's session: stop them by uid, never by name (pkill -f would hit the harness).
CAND_UID=65534
pkill -KILL -U "$CAND_UID" 2>/dev/null || true

python3 -I -E -s /tests/collect.py --out "$OUT/evidence.json" --uid "$CAND_UID"
pkill -KILL -U "$CAND_UID" 2>/dev/null || true             # nothing of the candidate's may outlive the run
rm -rf /tmp/ock-verify

exec python3 -I -E -s /tests/compute_reward.py           # its exit code is the run's
