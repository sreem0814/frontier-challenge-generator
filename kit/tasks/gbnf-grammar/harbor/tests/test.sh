#!/usr/bin/env bash
# tests/test.sh: harden, collect evidence, then hand every scoring decision to compute_reward.py.
# The agent had root in this container until a moment ago, so trust nothing it could have touched.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONSAFEPATH PYTHONINSPECT LD_PRELOAD LD_AUDIT LD_LIBRARY_PATH \
      BASH_ENV ENV SHELLOPTS BASHOPTS GCONV_PATH PROMPT_COMMAND CDPATH CPATH CPLUS_INCLUDE_PATH C_INCLUDE_PATH \
      LIBRARY_PATH GCC_EXEC_PREFIX COMPILER_PATH CCACHE_DIR CC CXX CFLAGS CXXFLAGS LDFLAGS CMAKE_PREFIX_PATH 2>/dev/null
umask 022

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=/usr/bin/python3.11

# Leftovers from the agent's session: stop processes running from the workspace or scratch dirs (by PID,
# never by name; the harness and PID 1 are left alone), then everything of the candidate uid.
SWEEP1="$("$PY" -I -S "$TESTS_DIR/sweep.py" 2>/dev/null || echo '{}')"
CAND_UID=65534
pkill -KILL -U "$CAND_UID" 2>/dev/null || true

OUT=/logs/verifier
mkdir -p "$OUT"
chown root:root "$OUT" 2>/dev/null; chmod 755 "$OUT"     # the candidate (uid 65534) must not write reward files
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json "$OUT"/evidence.json

# Hidden cases and expected results stay readable by root only while candidate code runs.
chmod 700 "$TESTS_DIR" 2>/dev/null || true

# The verifier's interpreter, compiler toolchain and basic tools are checked against the package database first.
TAMPER="$(mktemp)"
for p in python3.11-minimal libpython3.11-minimal libpython3.11-stdlib util-linux procps libc6 libc6-dev \
         coreutils gcc-12 g++-12 cpp-12 libgcc-12-dev libstdc++-12-dev libstdc++6 libgcc-s1 binutils \
         binutils-x86-64-linux-gnu libbinutils linux-libc-dev; do
  # bookworm-slim never installs docs, man pages or lintian files; only changes to the rest count
  dpkg --verify "$p" 2>&1 | grep -v '^.\{9\} c ' \
    | grep -Ev ' /usr/share/(doc|man|lintian|locale|info)/' | sed "s#^#$p: #" >>"$TAMPER" || true
done

# collect.py verifies the pristine tree, rebuilds the library with the three implementation files from /app
# (as uid 65534), runs the hidden cases (one forked process per case, 10 s each), checks the converted grammars
# with the original engine and always writes evidence.json.
"$PY" -I -S "$TESTS_DIR/collect.py" --out "$OUT/evidence.json" --uid "$CAND_UID" --tamper "$TAMPER" \
  --sweep "$SWEEP1"
rm -f "$TAMPER"
pkill -KILL -U "$CAND_UID" 2>/dev/null || true             # nothing of the candidate's may outlive the run
"$PY" -I -S "$TESTS_DIR/sweep.py" >/dev/null 2>&1 || true
rm -f "$OUT"/reward.txt "$OUT"/reward.json "$OUT"/details.json

exec "$PY" -I -S "$TESTS_DIR/compute_reward.py"           # its exit code is the run's
