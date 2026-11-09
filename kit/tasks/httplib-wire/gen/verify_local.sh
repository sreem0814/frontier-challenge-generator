#!/bin/bash
# gen/verify_local.sh <header> <label>: run harbor/tests/test.sh against a header in the dev image (no network).
set -u
T="$(cd "$(dirname "$0")/.." && pwd)"
W="$T/build/vl/$2"
docker run --rm -v "$T/build":/b cg-httplib-dev rm -rf "/b/vl/$2" >/dev/null 2>&1
mkdir -p "$W/app" "$W/logs"
cp -r "$T/harbor/tests" "$W/tests"; rm -rf "$W/tests/__pycache__"
cp "$1" "$W/app/httplib.h"
docker run --rm --network none --cpus 8 --memory 12g -v "$W/tests":/tests -v "$W/app":/app -v "$W/logs":/logs \
  cg-httplib-dev bash -c 'bash /tests/test.sh >/dev/null 2>&1; echo "rc=$?"; cat /logs/verifier/reward.json; echo; \
  python3 -c "import json;print(json.load(open(\"/logs/verifier/details.json\"))[\"additional_data\"][\"reason\"])"; \
  chown -R '"$(id -u):$(id -g)"' /logs /tests'
