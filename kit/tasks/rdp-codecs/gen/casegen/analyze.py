"""Join meta.json with oracle.txt: per codec, how many valid steps decode cleanly, how many truncated
variants are rejected. usage: analyze.py DIR [--show N]"""
import collections
import json
import sys

d = sys.argv[1]
show = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[2] == "--show" else 0
meta = {m["seq"]: m for m in json.load(open(f"{d}/meta.json"))}
res, crash = {}, {}
for ln in open(f"{d}/oracle.txt"):
    p = ln.split()
    if p[0] == "R":
        res[(int(p[1]), int(p[2]))] = (int(p[3]), p[4], int(p[5]))
    elif p[0] == "X":
        crash[int(p[1])] = p[2]
stat = collections.defaultdict(collections.Counter)
examples = collections.defaultdict(list)
for sid, m in meta.items():
    c = m["codec"]
    for i, st in enumerate(m["steps"]):
        r = res.get((sid, i))
        if r is None:
            key = "crash" if sid in crash else "missing"
        else:
            ok, h, logged = r
            key = f"{st['kind']}:{'ok' if ok else 'fail'}{'+log' if logged else ''}"
        stat[c][key] += 1
        if len(examples[(c, key)]) < 3:
            examples[(c, key)].append((sid, i, st["tags"], m["tags"]))
for c in sorted(stat):
    print(c, dict(stat[c]))
if show:
    for k, v in sorted(examples.items()):
        if "fail" in k[1] and "valid" in k[1] or "log" in k[1] or "crash" in k[1]:
            print(k, v[:show])
