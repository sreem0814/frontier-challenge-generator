#!/usr/bin/env python3
"""Score the codec decoders in /app on the sample streams, the same way the hidden set is scored.

  python3 /app/check/selfcheck.py                 build, then run every sample
  python3 /app/check/selfcheck.py --codec rfx     only one codec (interleaved planar nsc clear rfx progressive zgfx)
  python3 /app/check/selfcheck.py --diff          for each failing step, show the first differing pixel
  python3 /app/check/selfcheck.py --seq 412 -v    one sequence, with its parameters and tags
  python3 /app/check/selfcheck.py --dump /tmp/d   write got/expected buffers of failing steps (raw bytes;
                                                  for zgfx the decompressed output)
  options: --no-build (use /app/build as it is), -j N (parallel runners, default 8)

The runner (codec_runner.c, compiled against /app/build) calls the public decoder entry points exactly as
the grader's copy does. Each sample sequence runs in its own process; a crash or a 20 s timeout fails the
rest of that sequence.
"""
import argparse
import json
import lzma
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
SAMPLES = os.path.join(HERE, "samples")
WEIGHTS = {"interleaved": 0.12, "planar": 0.12, "nsc": 0.08, "clear": 0.13, "rfx": 0.18,
           "progressive": 0.27, "zgfx": 0.10}
FORMATS = {0x20048888: "BGRA32", 0x20040888: "BGRX32", 0x20038888: "RGBA32", 0x20030888: "RGBX32",
           0x18020888: "BGR24", 0x10010565: "RGB16"}


def read_records(path):
    data = open(path, "rb").read()
    out, pos = {}, 0
    while pos < len(data):
        start = pos
        sid, codec, w, h, fmt, stride, fill, c0, c1, n = struct.unpack_from("<10I", data, pos + 4)
        pos += 44
        steps = []
        for _ in range(n):
            params = struct.unpack_from("<I8I", data, pos)
            pos += 36
            pf = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + (1024 if pf else 0)
            ln = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + ln
            steps.append({"params": list(params[1:]), "len": ln})
        out[sid] = {"raw": data[start:pos], "codec": codec, "w": w, "h": h, "format": fmt, "stride": stride,
                    "ctx": (c0, c1), "steps": steps}
    return out


def build_runner(no_build):
    if not no_build:
        r = subprocess.run([os.path.join(APP, "build.sh")])
        if r.returncode != 0:
            sys.exit("build failed")
    b = os.path.join(APP, "build")
    exe = os.path.join(b, "codec_runner")
    cmd = ["gcc", "-O2", "-o", exe, os.path.join(HERE, "codec_runner.c"),
           "-I" + os.path.join(APP, "include"), "-I" + os.path.join(b, "include"),
           "-I" + os.path.join(APP, "winpr", "include"), "-I" + os.path.join(b, "winpr", "include"),
           "-L" + os.path.join(b, "libfreerdp"), "-L" + os.path.join(b, "winpr", "libwinpr"),
           "-lfreerdp3", "-lwinpr3",
           "-Wl,-rpath," + os.path.join(b, "libfreerdp"), "-Wl,-rpath," + os.path.join(b, "winpr", "libwinpr")]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit("could not compile the runner against /app/build")
    return exe


def run(exe, recs, jobs, dump=None):
    tmp = tempfile.mkdtemp(prefix="selfcheck-")
    ids = sorted(recs, key=lambda s: -len(recs[s]["raw"]))
    shards = [[] for _ in range(jobs)]
    sizes = [0] * jobs
    for s in ids:
        k = sizes.index(min(sizes))
        shards[k].append(s)
        sizes[k] += len(recs[s]["raw"])
    paths = []
    for k, sh in enumerate(shards):
        if not sh:
            continue
        p = os.path.join(tmp, f"shard{k}.bin")
        with open(p, "wb") as f:
            for s in sorted(sh):
                f.write(recs[s]["raw"])
        paths.append(p)

    def one(p):
        cmd = [exe, p, "--timeout", "20", "--logdir", tmp] + (["--dump", dump] if dump else [])
        env = dict(os.environ, WLOG_LEVEL="OFF")
        return subprocess.run(cmd, capture_output=True, env=env).stdout.decode("ascii", "replace")

    results, crashed = {}, {}
    with ThreadPoolExecutor(jobs) as ex:
        for out in ex.map(one, paths):
            for ln in out.splitlines():
                p = ln.split()
                if len(p) >= 6 and p[0] == "R":
                    key = (int(p[1]), int(p[2]))
                    results.setdefault(key, (int(p[3]), p[4]))
                elif len(p) >= 3 and p[0] == "X":
                    crashed[int(p[1])] = p[2]
    shutil.rmtree(tmp, ignore_errors=True)
    return results, crashed


def grade(expected, results):
    passed, per = {}, {}
    order = sorted(expected.items(), key=lambda kv: int(kv[0]))
    for kind in ("v", "t"):                       # truncated steps refer to their parent's verdict
        for sid, e in order:
            for i, st in enumerate(e["steps"]):
                if st["k"] != kind:
                    continue
                got = results.get((int(sid), i))
                if kind == "v":
                    ok = bool(got and got[0] == 1 and got[1] == st["h"])
                else:
                    ok = bool(got and got[0] == 0) and passed.get(tuple(st["p"]), False)
                passed[(int(sid), i)] = ok
                b = per.setdefault(e["codec"], {"passed": 0, "total": 0})
                b["total"] += 1
                b["passed"] += ok
    return passed, per


def load_pack():
    out = {}
    with lzma.open(os.path.join(SAMPLES, "expected.pack.xz"), "rb") as f:
        while True:
            hdr = f.read(12)
            if len(hdr) < 12:
                break
            sid, step, ln = struct.unpack("<III", hdr)
            out[(sid, step)] = f.read(ln)
    return out


def first_diff(rec, got, exp):
    if rec["codec"] == 7:                          # zgfx: the output bytes themselves
        if len(got) != len(exp):
            return f"output is {len(got)} bytes, expected {len(exp)}"
        i = next(k for k in range(len(got)) if got[k] != exp[k])
        return f"first difference at output byte {i}: got {got[i]:02x} expected {exp[i]:02x}"
    bpp = {0x20: 4, 0x18: 3, 0x10: 2}.get(rec["format"] >> 24, 4)
    for i in range(min(len(got), len(exp))):
        if got[i] != exp[i]:
            y, rem = divmod(i, rec["stride"])
            x, ch = divmod(rem, bpp)
            n = sum(1 for a, b in zip(got, exp) if a != b)
            return (f"first difference at byte {i} (x={x}, y={y}, byte {ch} of the pixel): got "
                    f"{got[i - ch:i - ch + bpp].hex()} expected {exp[i - ch:i - ch + bpp].hex()}; "
                    f"{n} bytes differ")
    return "buffers are identical (the step reported failure)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codec")
    ap.add_argument("--seq", type=int)
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--dump")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("-j", type=int, default=8)
    a = ap.parse_args()

    expected = json.load(open(os.path.join(SAMPLES, "expected.json")))
    recs = read_records(os.path.join(SAMPLES, "cases.bin"))
    sel = {s for s in recs if (a.seq is None or s == a.seq)}
    if a.codec:
        sel = {s for s in sel if expected[str(s)]["codec"] == a.codec}
    if a.seq is not None:                         # a truncated step needs its parent's verdict too
        for st in expected[str(a.seq)]["steps"]:
            if st["k"] == "t":
                sel.add(st["p"][0])
    exe = build_runner(a.no_build)
    dumpdir = tempfile.mkdtemp(prefix="selfcheck-dump-") if (a.diff or a.dump) else None
    results, crashed = run(exe, {s: recs[s] for s in sel}, max(1, a.j), dumpdir)
    exp_sel = {k: v for k, v in expected.items() if int(k) in sel}
    passed, per = grade(exp_sel, results)

    pack = load_pack() if (a.diff or a.dump) else {}
    fails = 0
    for sid in sorted(int(k) for k in exp_sel):
        e = expected[str(sid)]
        rec = recs[sid]
        for i, st in enumerate(e["steps"]):
            ok = passed[(sid, i)]
            show = a.v or (not ok and (a.diff or a.dump or a.seq is not None))
            if not ok:
                fails += 1
            if not show:
                continue
            got = results.get((sid, i))
            dst = ("" if rec["codec"] == 7 else
                   f"dst {rec['w']}x{rec['h']} {FORMATS.get(rec['format'], hex(rec['format']))} stride "
                   f"{rec['stride']} params {rec['steps'][i]['params'][:7]} ")
            desc = (f"seq {sid} step {i} [{e['codec']}] {'truncated' if st['k'] == 't' else 'valid'} "
                    f"{dst}len {rec['steps'][i]['len']} tags {e['tags'] + e['step_tags'][i]}")
            print(("PASS " if ok else "FAIL ") + desc)
            if ok:
                continue
            if sid in crashed and (got is None):
                print(f"    the runner process died ({crashed[sid]}) before this step finished")
            elif st["k"] == "t":
                print("    expected: the call reports failure" + ("" if got and got[0] == 0 else
                                                                   f" (it returned success)"))
                if got and got[0] == 0:
                    print("    (the untruncated parent step fails, so this step cannot count yet)")
            elif got and got[0] == 0:
                print("    expected success, the call reported failure")
            elif got:
                gpath = os.path.join(dumpdir, f"{sid:08d}-{i:04d}.raw") if dumpdir else None
                exp = pack.get((sid, i))
                if gpath and os.path.exists(gpath) and exp is not None:
                    gbuf = open(gpath, "rb").read()
                    print("    " + first_diff(rec, gbuf, exp))
                    if a.dump:
                        os.makedirs(a.dump, exist_ok=True)
                        shutil.copy(gpath, os.path.join(a.dump, f"{sid}-{i}.got.raw"))
                        open(os.path.join(a.dump, f"{sid}-{i}.expected.raw"), "wb").write(exp)
                else:
                    print("    output differs from the expected buffer")
    if dumpdir:
        shutil.rmtree(dumpdir, ignore_errors=True)

    print()
    total_w, score = 0.0, 0.0
    for c in WEIGHTS:
        if c in per:
            b = per[c]
            frac = b["passed"] / b["total"] if b["total"] else 0.0
            print(f"{c:12s} {b['passed']:5d} / {b['total']:5d}  {frac:7.4f}   weight {WEIGHTS[c]:.2f}")
            score += WEIGHTS[c] * frac
            total_w += WEIGHTS[c]
    if total_w:
        label = "estimated score" if total_w > 0.999 else "weighted score over the selected codecs"
        print(f"{label}: {score / total_w:.4f}" + ("" if total_w > 0.999 else
                                                  f" (full-set weight {total_w:.2f})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
