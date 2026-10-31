#!/usr/bin/env bash
# tests/test.sh: harden, collect evidence, then hand every scoring decision to compute_reward.py.
# The agent had root in this container until a moment ago, so trust nothing it could have touched.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH BASH_ENV ENV \
      SHELLOPTS BASHOPTS GCONV_PATH PROMPT_COMMAND CDPATH \
      GOFLAGS GOPROXY GOSUMDB GOTOOLCHAIN GOROOT GOPATH GOMODCACHE GOCACHE GOENV GOEXPERIMENT GODEBUG \
      GOOS GOARCH CGO_ENABLED CC CXX CGO_CFLAGS CGO_LDFLAGS GOTMPDIR GOINSECURE GOPRIVATE GONOSUMDB GONOPROXY
umask 022

OUT=/logs/verifier
mkdir -p "$OUT"
chown root:root "$OUT" 2>/dev/null; chmod 755 "$OUT"     # the candidate (uid 65534) must not write reward files
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json "$OUT"/evidence.json

# The sealed data under /tests must not be readable by the candidate uid (best effort: a read-only mount stays as is).
chown -R root:root /tests 2>/dev/null; chmod -R go-rwx /tests 2>/dev/null || true

# Leftovers from the agent's session (it ran as the unprivileged user "agent") and from earlier verifier runs:
# stop them by uid, never by name (pkill -f would hit the harness).
CAND_UID=65534
pkill -KILL -U agent 2>/dev/null || true
pkill -KILL -U "$CAND_UID" 2>/dev/null || true

# collect.py assembles a clean module tree (pristine files from /tests plus the agent's four packages),
# checks the toolchain and module cache, builds, runs the behavioural cases and the integration tests
# (candidate code runs as uid 65534 in its own process group with timeouts) and always writes evidence.json.
python3 -I -E -s /tests/collect.py --out "$OUT/evidence.json" --uid "$CAND_UID"
pkill -KILL -U "$CAND_UID" 2>/dev/null || true             # nothing of the candidate's may outlive the run

exec python3 -I -E -s /tests/compute_reward.py           # its exit code is the run's
