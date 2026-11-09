#!/bin/bash
# gen/make_app.sh: assemble harbor/environment/app/ (everything the image ships under /app except timer.sh).
set -euo pipefail
T="$(cd "$(dirname "$0")/.." && pwd)"
S=$T/spike/src
A=$T/harbor/environment/app
rm -rf "$A/docs" "$A/example" "$A/httplib.h" "$A/LICENSE"
mkdir -p "$A/docs" "$A/tools"
python3 -I "$T/gen/strip.py" "$S/httplib.h" "$A/httplib.h"
cp "$S/LICENSE" "$A/LICENSE"
cp "$S/README.md" "$S/README-sse.md" "$S/README-stream.md" "$S/README-websocket.md" "$A/docs/"
cp -r "$S/docs-src/pages/en" "$A/docs/guide"
rm -rf "$A/docs/guide/llm-app"                  # an LLM web-app tutorial, unrelated to the task
cp -r "$S/example" "$A/example"
rm -f "$A/example/"*.vcxproj "$A/example/"*.sln "$A/example/ca-bundle.crt"
cp "$T/harbor/tests/harness/probe.cc" "$T/harbor/tests/harness/server.cc" "$T/harbor/tests/wire.py" "$A/tools/"
grep -c "removed from this tree" "$A/httplib.h"
