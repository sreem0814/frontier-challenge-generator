#!/usr/bin/env bash
# selfcheck/run.sh: run the grader's checks that do not need sealed data, on your working tree.
# Usage: bash /app/selfcheck/run.sh [-v]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PKGS="proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc"

echo "== 1. build: go build ./... (includes selfcheck/api.go, the exported API check)"
if ! go build ./...; then
  echo "BUILD FAILED: the grader scores this 0"
  exit 1
fi

echo "== 2. files the grader takes from your tree: non-test .go files directly in $PKGS"
echo "   changes anywhere else are discarded (the grader restores the base files):"
git status --porcelain --untracked-files=all | awk '{print $NF}' |
  grep -v -E '^(proto/codec|mtproxy/obfuscated2|crypto|exchange|mtproto|mtproto/salts|rpc)/[^/]+\.go$' | sed 's/^/     /' || true

echo "== 3. forbidden imports and directives (each scores 0)"
bad=0
for p in $PKGS; do
  imps=$(go list -f '{{join .Imports " "}}' "./$p")
  for i in $imps; do
    case "$i" in unsafe|C|os/exec|syscall|plugin|runtime/cgo|golang.org/x/sys*) echo "   $p imports $i"; bad=1 ;; esac
  done
  if grep -n -E '//[[:space:]]*go:(linkname|cgo_)' "$p"/*.go 2>/dev/null; then bad=1; fi
done
[ "$bad" = 0 ] && echo "   none"

echo "== 4. sample vectors and round trips"
go run ./selfcheck "$@"

echo "== 5. integration tests (the module's own tests that go through these packages; each run alone)"
pass=0; total=0
while read -r pkg test; do
  [ -n "$pkg" ] || continue
  total=$((total + 1))
  if go test -count=1 -v -timeout 90s -run "^${test}\$" "./$pkg" 2>&1 | grep -q -E "^--- PASS: ${test} "; then
    pass=$((pass + 1))
  else
    echo "   FAIL $pkg $test"
  fi
done < selfcheck/integration.txt
echo "integration $pass/$total (weight 0.08)"
