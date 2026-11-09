"""gen/install_sets.py: build/ outputs -> harbor/tests/data/cases.jsonl.gz, harbor/tests/gtest/ (+ tests.txt),
harbor/environment/app/samples/cases.jsonl.gz (samples whose input equals a hidden input are dropped)."""
import gzip, json, os, shutil
B = "build"
s = [json.load(open(f"{B}/gt_stub{x}.json")) for x in ("", "2", "3")]
r = [json.load(open(f"{B}/gt_ref{x}.json")) for x in ("1", "2", "3")]
assert s[0] == s[1] == s[2]
hid = sorted(t for t in r[0] if all(x.get(t) == 0 for x in r) and all(x.get(t) != 0 for x in s))
dst = "harbor/tests/gtest"
if os.path.exists(dst):
    shutil.rmtree(dst)
shutil.copytree(f"{B}/gtest", dst)
open(f"{dst}/tests.txt", "w").write("\n".join(hid) + "\n")
os.makedirs("harbor/tests/data", exist_ok=True)
with gzip.GzipFile("harbor/tests/data/cases.jsonl.gz", "wb", mtime=0) as f:
    f.write(gzip.open(f"{B}/set_hidden.jsonl.gz").read())
key = lambda c: (c.get("op"), tuple(c.get("args", ())), c.get("send"))
hk = {key(json.loads(l)) for l in gzip.open(f"{B}/set_hidden.jsonl.gz")}
os.makedirs("harbor/environment/app/samples", exist_ok=True)
n = d = 0
with gzip.GzipFile("harbor/environment/app/samples/cases.jsonl.gz", "wb", mtime=0) as f:
    for l in gzip.open(f"{B}/set_sample.jsonl.gz"):
        c = json.loads(l)
        if key(c) in hk:
            d += 1
            continue
        out = {k: c[k] for k in ("id", "kind", "area", "fam", "err", "expect")}
        if c["kind"] == "probe":
            out["op"], out["args"] = c["op"], c["args"]
        else:
            out["send"] = c["send"]
        f.write((json.dumps(out, sort_keys=True) + "\n").encode())
        n += 1
print("gtests", len(hid), "samples", n, "dropped overlap", d)
