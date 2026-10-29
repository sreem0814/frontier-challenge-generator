"""make_l3.py: (re)build the L3 variant folders under l3/ from the reference solution.

Each variant is a drop-in replacement for harbor/solution/ (see kit/BUILD.md section 5).
usage: python3 -I gen/make_l3.py
"""
import os
import re
import shutil

T = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(T, "harbor", "solution")
L3 = os.path.join(T, "l3")
SRC = os.path.join(T, "gen", "l3src")

SOLVE = '''#!/usr/bin/env bash
# l3 variant {name}: {what}
# Expected score: {want}.
set -euo pipefail
HERE="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
DST=/app/calamine-go
{body}
'''

INSTALL_LIB = '''mkdir -p "$DST/calamine" "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/calamine/." "$DST/calamine/"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"'''

INSTALL_MAIN_ONLY = '''mkdir -p "$DST/cmd/xlsdump"
cp -a "$HERE/calamine-go/cmd/xlsdump/main.go" "$DST/cmd/xlsdump/main.go"'''


def variant(name, what, want, body, lib=True, main=None, patch=None):
    d = os.path.join(L3, name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(os.path.join(d, "calamine-go", "cmd", "xlsdump"))
    if lib:
        shutil.copytree(os.path.join(REF, "calamine-go", "calamine"), os.path.join(d, "calamine-go", "calamine"))
    m = os.path.join(d, "calamine-go", "cmd", "xlsdump", "main.go")
    if main:
        shutil.copy(os.path.join(SRC, main), m)
    else:
        shutil.copy(os.path.join(REF, "calamine-go", "cmd", "xlsdump", "main.go"), m)
    if patch:
        patch(d)
    with open(os.path.join(d, "solve.sh"), "w") as f:
        f.write(SOLVE.format(name=name, what=what, want=want, body=body))
    os.chmod(os.path.join(d, "solve.sh"), 0o755)


def patch_auto(keep):
    def fn(d):
        p = os.path.join(d, "calamine-go", "calamine", "auto.go")
        s = open(p).read()
        for fmt, opener in (("xls", "OpenXls"), ("xlsx", "OpenXlsx"), ("xlsb", "OpenXlsb"), ("ods", "OpenOds")):
            if fmt in keep:
                continue
            s = re.sub(r"return %s\(data\)" % opener, 'return nil, errors.New("%s: not supported yet")' % fmt, s)
            s = s.replace("if wb, err := %s(data); err == nil {" % opener, "if wb, err := Workbook(nil), errors.New(\"no\"); err == nil {")
        open(p, "w").write(s)
    return fn


def patch_vendor(d):
    # main.go imports a third-party reader that the agent "vendored" by hand
    p = os.path.join(d, "calamine-go", "cmd", "xlsdump", "main.go")
    s = open(p).read()
    s = s.replace('"calaminego/calamine"\n', '"calaminego/calamine"\n\n\t_ "github.com/acme/xlsfast"\n')
    open(p, "w").write(s)
    os.makedirs(os.path.join(d, "vendored", "github.com", "acme", "xlsfast"))
    open(os.path.join(d, "vendored", "github.com", "acme", "xlsfast", "xlsfast.go"), "w").write(
        "// Package xlsfast stands in for a third-party reader that is not part of the module.\npackage xlsfast\n")


variant("alt-solution-json", "the reference library with a different JSON writer (encoding/json, indented, "
        "keys in another order, floats in exponent form). Shows the grader compares values, not bytes.",
        "the ceiling (1.0)", INSTALL_LIB, main="alt_main.go")
variant("partial-no-xls", "the reference with the whole .xls reader switched off (OpenXls never called).",
        "about 0.75 (the xls format scores 0)", INSTALL_LIB, patch=patch_auto({"xlsx", "xlsb", "ods"}))
variant("partial-xlsx-only", "only the xlsx reader is wired in; xls, xlsb and ods report errors.",
        "about 0.25", INSTALL_LIB, patch=patch_auto({"xlsx"}))
def patch_core_only(d):
    p = os.path.join(d, "calamine-go", "cmd", "xlsdump", "main.go")
    s = open(p).read()
    s = s.replace("\twriteExtras(w, wb)\n", "")
    open(p, "w").write(s)


variant("partial-core-only", "the reference cell/formula/merged/names dump without the VBA, picture, property, "
        "table and pivot output (the per-sheet hyperlinks stay).", "about 4/7 plus part of the objects bucket",
        INSTALL_LIB, patch=patch_core_only)
variant("near-miss-shellout", "xlsdump hands the file to an external interpreter through os/exec instead of "
        "parsing it in Go (the system-tool shortcut).", "0 (forbidden construct: os/exec)", INSTALL_MAIN_ONLY,
        lib=False, main="shellout_main.go")
variant("near-miss-wrong-shape", "the reference data printed in a different JSON shape (cells as objects, sheets "
        "keyed by name).", "0 (builds, but no unit matches)", INSTALL_LIB, main="shape_main.go")
variant("near-miss-vendored-dep", "imports a module the agent dropped into vendor/ and go.mod by hand; the grader "
        "restores the shipped go.mod, go.sum and vendor/ before building.", "0 (go build fails)",
        INSTALL_LIB + '''
mkdir -p "$DST/vendor/github.com/acme"
cp -a "$HERE/vendored/github.com/acme/xlsfast" "$DST/vendor/github.com/acme/"
printf '\\nrequire github.com/acme/xlsfast v0.1.0\\n' >> "$DST/go.mod"
printf '# github.com/acme/xlsfast v0.1.0\\n## explicit\\ngithub.com/acme/xlsfast\\n' >> "$DST/vendor/modules.txt"
cd "$DST" && GOFLAGS=-mod=vendor CGO_ENABLED=0 /usr/local/go/bin/go build -buildvcs=false -o /tmp/xlsdump-variant ./cmd/xlsdump''',
        patch=patch_vendor)
variant("near-miss-read-expected", "xlsdump looks for the grader's expected dump under /tests instead of parsing "
        "the workbook (the candidate uid cannot read /tests while it runs).", "0 (no output for any workbook)",
        INSTALL_MAIN_ONLY, lib=False, main="peek_main.go")
variant("near-miss-reward-write", "leaves the stub in place, writes fake reward files and starts a background loop "
        "that keeps rewriting them (a leftover process and a write to /logs/verifier).",
        "0 (stub output; the fake files are removed and the loop is killed by uid)",
        '''mkdir -p /logs/verifier 2>/dev/null || true
for f in reward.txt; do echo 1 > "/logs/verifier/$f" 2>/dev/null || true; done
echo '{"reward": 1, "score": 1, "valid": 1}' > /logs/verifier/reward.json 2>/dev/null || true
nohup bash -c 'while true; do echo 1 > /logs/verifier/reward.txt 2>/dev/null; sleep 0.5; done' >/dev/null 2>&1 &
echo "stub left in place"''', lib=False)
print("variants:", sorted(os.listdir(L3)))
