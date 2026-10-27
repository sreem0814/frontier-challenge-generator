#!/usr/bin/env bash
# tests/test.sh: harden, collect evidence, then hand every scoring decision to compute_reward.py.
# The agent had root in this container until a moment ago, so trust nothing it could have touched.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH BASH_ENV ENV \
      GCONV_PATH PROMPT_COMMAND CDPATH CARGO_HOME RUSTFLAGS RUSTC_WRAPPER \
      CARGO_BUILD_RUSTC_WRAPPER CARGO_TARGET_DIR RUSTUP_TOOLCHAIN
unset SHELLOPTS BASHOPTS 2>/dev/null || true             # read-only in bash; listed for completeness
umask 022

OUT=/logs/verifier
mkdir -p "$OUT"
chown root:root "$OUT" 2>/dev/null; chmod 755 "$OUT"     # the renderer (uid 65534) must not write reward files
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json "$OUT"/evidence.json

# The frozen cases and expected images stay readable by root only (best effort: a read-only mount keeps its mode).
chown -R root:root /tests 2>/dev/null; chmod 700 /tests 2>/dev/null || true

# Leftovers from the agent's session: stop them by uid, never by name (pkill -f would hit the harness).
CAND_UID=65534
pkill -KILL -U "$CAND_UID" 2>/dev/null || true

# collect.py rebuilds /app from a clean copy and renders every frozen case as uid 65534 (own session,
# timeouts); it always writes evidence.json, even when the build fails.
python3 -I -E -s /tests/collect.py --out "$OUT/evidence.json" --uid "$CAND_UID"
pkill -KILL -U "$CAND_UID" 2>/dev/null || true             # nothing of the renderer's may outlive the run

exec python3 -I -E -s /tests/compute_reward.py           # its exit code is the run's
