#!/usr/bin/env bash
# tests/test.sh: harden, collect evidence, then hand every scoring decision to compute_reward.py.
# The agent had root in this container until a moment ago, so trust nothing it could have touched:
# the Go toolchain is checked against its shipped digest, go.mod/go.sum/vendor are restored from
# tests/data/pristine, and all candidate code (go build, xlsdump) runs as uid 65534.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONSAFEPATH LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH BASH_ENV ENV \
      SHELLOPTS BASHOPTS GCONV_PATH PROMPT_COMMAND CDPATH GOFLAGS GOROOT GOPATH GOENV GOTOOLCHAIN \
      GOPROXY GOCACHE CGO_ENABLED GOWORK GOEXPERIMENT GODEBUG 2>/dev/null   # SHELLOPTS/BASHOPTS are readonly in bash
umask 022

OUT=/logs/verifier
mkdir -p "$OUT"
chown root:root "$OUT" 2>/dev/null; chmod 755 "$OUT"     # the candidate (uid 65534) must not write reward files
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json "$OUT"/evidence.json

# Leftovers from the agent's session (user "agent", uid 1000) and from candidate runs (uid 65534):
# stop them by uid, never by name (pkill -f would hit the harness).
AGENT_UID=1000
CAND_UID=65534
pkill -KILL -U "$AGENT_UID" 2>/dev/null || true
pkill -KILL -U "$CAND_UID" 2>/dev/null || true

# Hidden data and grader code must be unreadable by the candidate uid while its code runs.
chown -R root:root /tests 2>/dev/null; chmod 700 /tests 2>/dev/null || true

# collect.py builds xlsdump from a clean copy, runs the gates and the hidden workbooks, and always
# writes evidence.json, even when the build fails. -I -S: no user site, no .pth or sitecustomize hooks.
python3 -I -S -E -s /tests/collect.py --out "$OUT/evidence.json" --uid "$CAND_UID"
pkill -KILL -U "$CAND_UID" 2>/dev/null || true             # nothing of the candidate's may outlive the run
pkill -KILL -U "$AGENT_UID" 2>/dev/null || true

exec python3 -I -S -E -s /tests/compute_reward.py         # its exit code is the run's
