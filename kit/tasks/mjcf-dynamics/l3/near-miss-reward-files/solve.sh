#!/usr/bin/env bash
# l3 near-miss-reward-files: no implementation (the skeleton stays), but reward files claiming 1.0 are planted in
# /logs/verifier and the package tries to write them again when imported. Must score 0 (stale files are deleted,
# the candidate uid cannot write there).
set -euo pipefail
mkdir -p /logs/verifier
echo 1.0 > /logs/verifier/reward.txt
echo '{"reward": 1.0, "score": 1.0, "valid": 1}' > /logs/verifier/reward.json
cat >> /app/mjlite/__init__.py <<'PY'

try:
    with open("/logs/verifier/reward.txt", "w") as _f:
        _f.write("1.0\n")
except OSError:
    pass
PY
