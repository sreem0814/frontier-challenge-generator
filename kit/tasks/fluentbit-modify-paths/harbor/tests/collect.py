"""Evidence for the modify-filter task. Runs as root; every piece of candidate code runs as an unprivileged uid.

1. Check the pristine Fluent Bit tarball in the image (/opt/fluent-bit-base) against its frozen digest.
2. Unpack it into a fresh work tree and copy over the deliverable paths from /app/fluent-bit (nothing else).
3. Configure and build it as the unprivileged uid with the published cmake options and targets.
4. Run the upstream filter_modify runtime suite and record_accessor internal suite (regression gate).
5. Build the case harness against that build and run the frozen cases through it.
evidence.json is written on every path.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_cases  # noqa: E402
from score_cases import case_passes  # noqa: E402

BASE_TAR = Path("/opt/fluent-bit-base/fluent-bit-f4739648.tar.xz")
BASE_SHA256 = "3a8d39860d80d90ad237b21ef43978234b72c6a57d42816caa8f9869c414c5ab"
APP = Path("/app/fluent-bit")
WORK = None          # set in main(): a fresh root-created directory under /var/tmp

# Deliverable paths: directories are mirrored as a whole, files one by one. Everything else in /app is ignored.
DELIVER_DIRS = ["plugins/filter_modify", "src/record_accessor", "include/fluent-bit/record_accessor"]
DELIVER_FILES = ["src/flb_record_accessor.c", "src/flb_ra_key.c", "src/flb_mp.c",
                 "include/fluent-bit/flb_record_accessor.h", "include/fluent-bit/flb_ra_key.h",
                 "include/fluent-bit/flb_mp.h"]
CMAKE_OPTS = ["-DFLB_TESTS_RUNTIME=On", "-DFLB_TESTS_INTERNAL=On", "-DFLB_USE_SIMDUTF=No", "-DFLB_WASM=No",
              "-DFLB_LUAJIT=No", "-DFLB_KAFKA=No", "-DFLB_EXAMPLES=No", "-DFLB_BACKTRACE=No",
              "-DCMAKE_EXPORT_COMPILE_COMMANDS=On"]
TARGETS = ["fluent-bit-shared", "flb-rt-filter_modify", "flb-it-record_accessor"]
FORBIDDEN = [b"/tests/", b"/logs/verifier", b"hidden.jsonl", b"/opt/fluent-bit-base"]
MAX_FILE = 4 * 1024 * 1024

EV = {"runtime_ok": True, "runtime_error": "", "build_ok": False, "cheat_detected": False, "gate_reason": "",
      "notes": []}


def note(msg):
    EV["notes"].append(msg)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def demote(uid):
    def fn():
        os.setsid()
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return fn


def cand_env():
    return {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "HOME": str(WORK),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TMPDIR": str(WORK / "tmp")}


def run_as(uid, cmd, cwd, timeout, log=None):
    """Run cmd as uid in its own session; kill the whole group on timeout. Returns (rc, tail of output)."""
    out = open(log, "wb") if log else subprocess.DEVNULL
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=out, stderr=subprocess.STDOUT, env=cand_env(),
                             preexec_fn=demote(uid))
        try:
            rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            rc = -999
    finally:
        if log:
            out.close()
    tail = ""
    if log:
        try:
            tail = Path(log).read_bytes()[-3000:].decode("utf-8", "replace")
        except OSError:
            pass
    return rc, tail


def copy_deliverable(dst_root):
    """Mirror the deliverable paths from /app into the work tree. Returns the list of copied files."""
    copied = []
    app = APP
    if not app.is_dir() or app.is_symlink():
        raise RuntimeError("/app/fluent-bit is missing")

    def take(src, dst):
        if src.is_symlink():
            raise PermissionError("symlink in deliverable: %s" % src)
        if not src.is_file():
            return
        if src.stat().st_size > MAX_FILE:
            raise PermissionError("oversized file in deliverable: %s" % src)
        data = src.read_bytes()
        for bad in FORBIDDEN:
            if bad in data:
                raise PermissionError("deliverable %s refers to %s" % (src.relative_to(app), bad.decode()))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        copied.append(str(src.relative_to(app)))

    for d in DELIVER_DIRS:
        s = app / d
        t = dst_root / d
        if s.is_symlink():
            raise PermissionError("symlink in deliverable: %s" % s)
        if t.exists():
            shutil.rmtree(t)
        if not s.is_dir():
            continue
        for root, dirs, files in os.walk(s, followlinks=False):
            rp = Path(root)
            for name in dirs:
                if (rp / name).is_symlink():
                    raise PermissionError("symlink in deliverable: %s" % (rp / name))
            for name in files:
                take(rp / name, t / (rp / name).relative_to(s))
    for f in DELIVER_FILES:
        s = app / f
        t = dst_root / f
        if s.is_symlink():
            raise PermissionError("symlink in deliverable: %s" % s)
        if s.is_file():
            take(s, t)
        elif t.exists():
            t.unlink()
    return copied


def acutest(binary, uid, cwd, timeout, log):
    rc, tail = run_as(uid, [str(binary)], cwd, timeout, log)
    text = Path(log).read_text(errors="replace") if Path(log).exists() else ""
    total = len(re.findall(r"^Test [^\n]*?\.\.\.", text, re.M))
    m = re.search(r"FAILED: (\d+) of (\d+) unit tests? ha(?:ve|s) failed", text)
    if rc == 0 and "SUCCESS: All unit tests have passed." in text:
        return total, total
    if m:
        failed, tot = int(m.group(1)), int(m.group(2))
        return tot - failed, tot
    return 0, max(total, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--uid", type=int, default=65534)
    a = ap.parse_args()
    uid = a.uid
    t0 = time.time()
    try:
        cases = [json.loads(l) for l in gzip.open(HERE / "data" / "hidden.jsonl.gz", "rt")]
        weights = json.loads((HERE / "data" / "weights.json").read_text())
        EV["weights"] = weights
        EV["cases_total"] = len(cases)

        if not BASE_TAR.is_file():
            EV["runtime_ok"] = False
            EV["runtime_error"] = "pristine Fluent Bit tarball missing from the image"
            return
        if sha256(BASE_TAR) != BASE_SHA256:
            EV["cheat_detected"] = True
            EV["gate_reason"] = "the pristine Fluent Bit tarball in /opt was modified"
            return

        global WORK
        WORK = Path(tempfile.mkdtemp(prefix="fbgrade-", dir="/var/tmp"))
        (WORK / "tmp").mkdir()
        rc = subprocess.run(["tar", "-xJf", str(BASE_TAR), "-C", str(WORK)]).returncode
        if rc != 0:
            EV["runtime_ok"] = False
            EV["runtime_error"] = "could not unpack the pristine tree"
            return
        tree = WORK / "fluent-bit"
        try:
            copied = copy_deliverable(tree)
        except PermissionError as e:
            EV["cheat_detected"] = True
            EV["gate_reason"] = str(e)
            return
        except RuntimeError as e:
            EV["gate_reason"] = str(e)
            return
        EV["deliverable_files"] = len(copied)
        hdir = WORK / "harness"
        hdir.mkdir()
        for f in ("modify_harness.c", "build_harness.py"):
            shutil.copy(HERE / "harness" / f, hdir / f)
        subprocess.run(["chown", "-R", "%d:%d" % (uid, uid), str(WORK)], check=True)

        build = tree / "build"
        rc, tail = run_as(uid, ["cmake", "-S", str(tree), "-B", str(build)] + CMAKE_OPTS, tree, 1200,
                          str(WORK / "cmake.log"))
        if rc != 0:
            EV["gate_reason"] = "cmake configure failed"
            EV["build_log_tail"] = tail
            return
        rc, tail = run_as(uid, ["make", "-C", str(build), "-j8"] + TARGETS, tree, 3600, str(WORK / "make.log"))
        if rc != 0:
            EV["gate_reason"] = "build failed"
            EV["build_log_tail"] = tail
            return
        rc, tail = run_as(uid, ["python3", "-I", str(hdir / "build_harness.py"), str(tree), str(build),
                                str(hdir / "modify_harness.c"), str(hdir / "modify_harness")], hdir, 600,
                          str(WORK / "harness.log"))
        if rc != 0:
            EV["gate_reason"] = "the case harness does not compile against the build (filter or headers broken)"
            EV["build_log_tail"] = tail
            return
        EV["build_ok"] = True
        EV["build_secs"] = round(time.time() - t0, 1)
        subprocess.run(["pkill", "-KILL", "-U", str(uid)], check=False)   # nothing from the build keeps running

        p1, t1 = acutest(build / "bin" / "flb-rt-filter_modify", uid, build, 1200, str(WORK / "rt.log"))
        p2, t2 = acutest(build / "bin" / "flb-it-record_accessor", uid, build, 600, str(WORK / "it.log"))
        EV["upstream"] = {"filter_modify": [p1, t1], "record_accessor": [p2, t2]}

        res = run_cases.run(str(hdir / "modify_harness"), cases, batch=200, timeout=180, preexec=demote(uid),
                            env=cand_env())
        buckets = {}
        for c in cases:
            b = buckets.setdefault(c["bucket"], [0, 0])
            b[1] += 1
            if case_passes(c, res.get(c["id"], ("missing", None))):
                b[0] += 1
        EV["buckets"] = buckets
        EV["crashes"] = sum(1 for r in res.values() if r[0] in ("crash", "timeout"))
    except Exception as e:  # an unexpected verifier fault is an infrastructure problem, not a score
        EV["runtime_ok"] = False
        EV["runtime_error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        EV["secs"] = round(time.time() - t0, 1)
        Path(a.out).write_text(json.dumps(EV, indent=1))
        try:
            subprocess.run(["pkill", "-KILL", "-U", str(uid)], check=False)
            if WORK is not None and WORK.is_dir() and not WORK.is_symlink():
                shutil.rmtree(WORK, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
