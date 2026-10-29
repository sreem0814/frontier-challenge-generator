"""assemble.py: build the bundle's data from the generated sets, the upstream fixtures and their dumps.

usage: python3 -I gen/assemble.py <calamine-0.37.0 source dir> <goroot digest> <calamine-0.37.0.crate>
Inputs (git-ignored, under build/): fixtures/, fx_expected/, fixture_split.json, gensets/{hid,hidexp,vis,visexp}.
Outputs: harbor/environment/{reference,samples,tools/units.py}, harbor/tests/{units.py,data/}.
"""
import gzip
import io
import json
import os
import shutil
import sys
import re
import tarfile

T = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = os.path.join(T, "build")
H = os.path.join(T, "harbor")
sys.path.insert(0, os.path.join(T, "gen"))
import units as U  # noqa: E402

src, goroot_digest = sys.argv[1], sys.argv[2]


def gz_bytes(data):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0, compresslevel=9) as g:
        g.write(data)
    return buf.getvalue()


def fresh(d):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)


# reference source: the published crate file (sha256 checked in the Dockerfile), extracted at image build
crate = sys.argv[3]
shutil.rmtree(os.path.join(H, "environment", "reference"), ignore_errors=True)
shutil.copy(crate, os.path.join(H, "environment", "calamine-0.37.0.crate"))

# phrases that must not appear in plain-text bundle files (a sample whose dump contains one ships gzipped)
deny = []
for dl in (os.path.join(T, "..", "..", "scripts", "leak-denylist.txt"),
           os.path.expanduser("~/.config/cgpipe/denylist.txt")):
    if os.path.exists(dl):
        deny += [l for l in open(dl).read().splitlines() if l.strip() and not l.lstrip().startswith("#")]
deny_rx = [re.compile(p, re.I) for p in deny]

split = json.load(open(os.path.join(B, "fixture_split.json")))
sets = {
    "visible": [(os.path.join(B, "fixtures", n), os.path.join(B, "fx_expected", n + ".json")) for n in split["visible"]],
    "hidden": [(os.path.join(B, "fixtures", n), os.path.join(B, "fx_expected", n + ".json")) for n in split["hidden"]],
}
for key, wb, ex in (("visible", "vis", "visexp"), ("hidden", "hid", "hidexp")):
    for n in sorted(os.listdir(os.path.join(B, "gensets", wb))):
        sets[key].append((os.path.join(B, "gensets", wb, n), os.path.join(B, "gensets", ex, n + ".json")))

# samples
sw = os.path.join(H, "environment", "samples", "workbooks")
se = os.path.join(H, "environment", "samples", "expected")
fresh(sw)
fresh(se)
nvis = 0
for wbp, exp in sets["visible"]:
    if not os.path.exists(exp):
        continue
    raw = open(exp, "rb").read()
    if not U.units(json.loads(raw)):
        continue
    n = os.path.basename(wbp)
    shutil.copy(wbp, os.path.join(sw, n))
    text = raw.decode("utf-8")
    if len(raw) > 1 << 20 or any(x.search(text) for x in deny_rx):
        open(os.path.join(se, n + ".json.gz"), "wb").write(gz_bytes(raw))
    else:
        open(os.path.join(se, n + ".json"), "wb").write(raw)
    nvis += 1

# hidden set
td = os.path.join(H, "tests", "data")
fresh(td)
os.makedirs(os.path.join(td, "workbooks"))
os.makedirs(os.path.join(td, "expected"))
os.makedirs(os.path.join(td, "pristine"))
cases = []
for wbp, exp in sets["hidden"]:
    if not os.path.exists(exp):
        continue
    raw = open(exp, "rb").read()
    d = json.loads(raw)
    if not U.units(d):
        continue
    n = os.path.basename(wbp)
    shutil.copy(wbp, os.path.join(td, "workbooks", n))
    open(os.path.join(td, "expected", n + ".json.gz"), "wb").write(gz_bytes(raw))
    cases.append({"file": n, "format": d["format"]})
cases.sort(key=lambda c: c["file"])
json.dump({"goroot_sha256": goroot_digest, "cases": cases}, open(os.path.join(td, "manifest.json"), "w"), indent=0)

# pristine module files
mod = os.path.join(H, "environment", "calamine-go")
for f in ("go.mod", "go.sum"):
    shutil.copy(os.path.join(mod, f), os.path.join(td, "pristine", f))
vsrc = os.path.join(B, "vendor-src")  # holds vendor/ as produced by `go mod vendor` for the skeleton
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as t:
    for dp, dns, fns in os.walk(os.path.join(vsrc, "vendor")):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            ti = t.gettarinfo(p, arcname=os.path.relpath(p, vsrc))
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ""
            ti.mtime = 0
            ti.mode = 0o644
            with open(p, "rb") as f:
                t.addfile(ti, f)
vt = gz_bytes(buf.getvalue())
open(os.path.join(td, "pristine", "vendor.tar.gz"), "wb").write(vt)
open(os.path.join(H, "environment", "calamine-go-vendor.tar.gz"), "wb").write(vt)

for d in (os.path.join(H, "tests"), os.path.join(H, "environment", "tools")):
    shutil.copy(os.path.join(T, "gen", "units.py"), d)

per = {}
for c in cases:
    per[c["format"]] = per.get(c["format"], 0) + 1
print(f"samples: {nvis} workbooks; hidden: {len(cases)} workbooks {per}")
