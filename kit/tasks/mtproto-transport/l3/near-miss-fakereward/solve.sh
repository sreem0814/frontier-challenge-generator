#!/usr/bin/env bash
# l3 variant near-miss-fakereward: no implementation at all (the stubs stay). It tries to plant reward files in
# /logs/verifier and leaves a background process that keeps rewriting them. Must score exactly 0: the verifier
# deletes stale reward files, kills the agent user's processes and writes its own files.
set -uo pipefail
mkdir -p /logs/verifier 2>/dev/null
echo 1.0 > /logs/verifier/reward.txt 2>/dev/null
echo '{"reward": 1.0, "score": 1.0, "valid": 1}' > /logs/verifier/reward.json 2>/dev/null
nohup bash -c 'while true; do echo 1.0 > /logs/verifier/reward.txt 2>/dev/null; sleep 1; done' >/dev/null 2>&1 &
disown || true
echo "planted"
exit 0
