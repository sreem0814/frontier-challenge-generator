#!/usr/bin/env bash
# tests/test.sh: harden, collect evidence, then hand every scoring decision to compute_reward.py.
# The agent (user "agent", uid 1000) worked in /app until a moment ago, so trust nothing it could have touched:
# collect.py rebuilds a clean rubocop tree from tests/data/pristine.tar.gz plus /app/rubocop/lib only, and all
# candidate Ruby code runs as uid 65534 with /tests unreadable to it.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONSAFEPATH LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH BASH_ENV ENV \
      GCONV_PATH PROMPT_COMMAND CDPATH RUBYOPT RUBYLIB GEM_HOME GEM_PATH BUNDLE_GEMFILE BUNDLE_PATH \
      BUNDLE_APP_CONFIG 2>/dev/null
unset SHELLOPTS BASHOPTS 2>/dev/null || true             # read-only in bash; listed for completeness
umask 022

OUT=/logs/verifier
mkdir -p "$OUT"
chown root:root "$OUT" 2>/dev/null; chmod 755 "$OUT"     # candidate code (uid 65534) must not write reward files
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json "$OUT"/evidence.json

# Leftovers from the agent's session and from candidate runs: stop them by uid, never by name.
AGENT_UID=1000
CAND_UID=65534
pkill -KILL -U "$AGENT_UID" 2>/dev/null || true
pkill -KILL -U "$CAND_UID" 2>/dev/null || true

# The frozen cases and grader code stay readable by root only while candidate code runs.
chown -R root:root /tests 2>/dev/null; chmod 700 /tests 2>/dev/null || true

python3 -I -S -E -s /tests/collect.py --out "$OUT/evidence.json" --uid "$CAND_UID"
pkill -KILL -U "$CAND_UID" 2>/dev/null || true             # nothing of the candidate's may outlive the run
pkill -KILL -U "$AGENT_UID" 2>/dev/null || true

exec python3 -I -S -E -s /tests/compute_reward.py         # its exit code is the run's
