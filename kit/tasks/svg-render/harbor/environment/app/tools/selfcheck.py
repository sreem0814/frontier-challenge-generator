#!/usr/bin/env python3
"""selfcheck.py: build the renderer the way the grader does and score it on the visible samples.

  python3 tools/selfcheck.py                 clean offline build + every sample under samples/
  python3 tools/selfcheck.py --fast          reuse /app/target (incremental cargo build, no clean copy)
  python3 tools/selfcheck.py -k marker       only samples whose path contains "marker"
  python3 tools/selfcheck.py --diff out/diff write expected | yours | off-pixel images for failing cases
  python3 tools/selfcheck.py --list          print every case with its result

The comparison rule is the grader's (tools/imgcmp.py). The printed score is the fraction of samples that
pass; the real score uses the same rule on a larger set of cases you do not have.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgcmp  # noqa: E402

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(APP, "samples")
SKIP_TOP = {"target", ".git", ".timer"}
WIDTH = 300
CASE_TIMEOUT = 30
NOBODY = 65534


def sh(cmd, cwd, env, timeout, as_nobody):
    kw = dict(user=NOBODY, group=NOBODY, extra_groups=[]) if as_nobody else {}
    p = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    try:
        out, _ = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        out, _ = p.communicate()
        rc = None
    # anything still alive in the session is a leftover process (the grader treats it as a failed gate)
    leftover = 0
    try:
        os.killpg(p.pid, 0)
        leftover = 1
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    return rc, out.decode("utf-8", "replace"), leftover


def chown_tree(path):
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            os.lchown(os.path.join(root, n), NOBODY, NOBODY)
    os.lchown(path, NOBODY, NOBODY)


def build(fast, as_nobody, tmp):
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "CARGO_NET_OFFLINE": "true"}
    if fast:
        env.update(HOME=os.environ.get("HOME", "/root"), CARGO_HOME=os.path.join(tmp, "cargo-home"))
        src = APP
        as_nobody = False
    else:
        src = os.path.join(tmp, "src")
        shutil.copytree(APP, src, symlinks=True,
                        ignore=lambda d, names: SKIP_TOP if os.path.samefile(d, APP) else [])
        home = os.path.join(tmp, "home")
        os.makedirs(os.path.join(home, ".cargo"))
        env.update(HOME=home, CARGO_HOME=os.path.join(home, ".cargo"), TMPDIR=home,
                   CARGO_TARGET_DIR=os.path.join(src, "target"))
        if as_nobody:
            os.chmod(tmp, 0o755)
            chown_tree(src)
            chown_tree(home)
    os.makedirs(env["CARGO_HOME"], exist_ok=True)
    t0 = time.monotonic()
    rc, out, _ = sh(["cargo", "build", "--release", "--offline"], src, env, 1800, as_nobody)
    print(f"build: {'ok' if rc == 0 else 'FAILED'} in {time.monotonic() - t0:.1f}s ({'incremental in /app' if fast else 'clean copy'})")
    if rc != 0:
        print(out[-4000:])
        return None
    exe = os.path.join(src, "target", "release", "svgrender")
    if not os.path.isfile(exe):
        print("build: target/release/svgrender was not produced")
        return None
    return exe


def diff_image(exp, cand, w, h, path):
    """expected | yours | marks (red: off pixel, grey: different but accepted)."""
    mask = imgcmp.off_mask(imgcmp.premultiply(exp), imgcmp.premultiply(cand), w, h)
    colours = {0: b"\x00\x00\x00\x00", 1: b"\x90\x90\x90\xff", 2: b"\xff\x00\x00\xff"}
    stride, row = w * 4, 3 * w * 4
    out = bytearray(row * h)
    for y in range(h):
        out[y * row:y * row + stride] = exp[y * stride:(y + 1) * stride]
        out[y * row + stride:y * row + 2 * stride] = cand[y * stride:(y + 1) * stride]
        out[y * row + 2 * stride:(y + 1) * row] = b"".join(colours[m] for m in mask[y * w:(y + 1) * w])
    imgcmp.write_png(path, 3 * w, h, bytes(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fast", action="store_true", help="incremental build in /app instead of a clean copy")
    ap.add_argument("-k", dest="filter", default="", help="only samples whose path contains this text")
    ap.add_argument("--diff", default="", help="directory for diff images of failing cases")
    ap.add_argument("--list", action="store_true", help="print every case, not only failures")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()

    as_nobody = os.geteuid() == 0
    tmp = tempfile.mkdtemp(prefix="selfcheck-")
    try:
        exe = build(a.fast, as_nobody, tmp)
        if exe is None:
            print("score estimate: 0 (the build gate failed)")
            return 1
        cases = sorted(os.path.relpath(os.path.join(r, f), SAMPLES)
                       for r, _, fs in os.walk(SAMPLES) for f in fs if f.endswith(".svg"))
        cases = [c for c in cases if a.filter in c]
        runs = os.path.join(tmp, "runs")
        os.makedirs(runs)
        os.chmod(runs, 0o777)

        def one(rel):
            d = tempfile.mkdtemp(dir=runs)
            shutil.copyfile(os.path.join(SAMPLES, rel), os.path.join(d, "in.svg"))
            if as_nobody:
                chown_tree(d)
            env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": d, "TMPDIR": d, "LANG": "C.UTF-8"}
            t0 = time.monotonic()
            rc, out, leftover = sh([exe, "--width", str(WIDTH), "in.svg", "out.png"], d, env, CASE_TIMEOUT, as_nobody)
            dt = time.monotonic() - t0
            res = {"case": rel, "ok": False, "leftover": leftover, "secs": dt}
            outp = os.path.join(d, "out.png")
            if rc is None:
                res["why"] = f"timeout after {CASE_TIMEOUT}s"
            elif rc != 0:
                res["why"] = f"exit status {rc}: {out.strip()[-200:]}"
            elif not os.path.isfile(outp) or os.path.islink(outp):
                res["why"] = "no out.png"
            else:
                exp = open(os.path.join(SAMPLES, rel[:-4] + ".png"), "rb").read()
                cand = open(outp, "rb").read()
                ok, off, msg = imgcmp.compare_png_bytes(exp, cand)
                res["ok"], res["why"] = ok, msg
                if a.diff and not ok and off is not None:
                    os.makedirs(a.diff, exist_ok=True)
                    w, h, e = imgcmp.read_png(exp)
                    _, _, c = imgcmp.read_png(cand)
                    diff_image(e, c, w, h, os.path.join(a.diff, rel.replace("/", "__")[:-4] + ".png"))
            shutil.rmtree(d, ignore_errors=True)
            return res

        t0 = time.monotonic()
        with ThreadPoolExecutor(max(1, a.jobs)) as pool:
            results = list(pool.map(one, cases))
        buckets = {}
        for r in results:
            b = buckets.setdefault(r["case"].split("/")[0], [0, 0])
            b[1] += 1
            b[0] += r["ok"]
            if a.list or not r["ok"]:
                print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['case']}: {r['why']}")
        print(f"\n{len(results)} samples in {time.monotonic() - t0:.1f}s, slowest render "
              f"{max((r['secs'] for r in results), default=0):.2f}s")
        for name, (p, t) in sorted(buckets.items()):
            print(f"  {name:15s} {p:4d}/{t:<4d} {p / t:6.1%}")
        passed = sum(r["ok"] for r in results)
        leftovers = sum(r["leftover"] for r in results)
        if leftovers:
            print(f"GATE: {leftovers} render(s) left a process running; the grader scores such a renderer 0")
            print("score estimate: 0")
            return 1
        if results:
            print(f"score estimate: {passed}/{len(results)} = {passed / len(results):.4f}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
