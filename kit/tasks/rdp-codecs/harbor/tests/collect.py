"""tests/collect.py: evidence only. Rebuilds the library from the pristine tree plus the codec files from
/app, runs the hidden streams through the decoders, writes evidence.json.

Every path writes evidence.json. The build and the decoders run as an unprivileged uid in their own process
groups with time limits; the expected results stay readable by root only. The runner reports each call's
status and writes the destination buffer after each successful call to a file; the buffer is hashed here
(SHA-256), so nothing the decoder code prints can stand in for a correct image. Case verdicts are computed
here; compute_reward.py turns the evidence into the reward.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app")
ap.add_argument("--base", default="/usr/src/freerdp-3.32.2")
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--tamper", default="", help="file with dpkg --verify findings for the verifier's packages")
ap.add_argument("--sweep", default="{}", help="JSON line from sweep.py: session leftovers that were stopped")
args = ap.parse_args()

DATA = os.path.join(HERE, "data")
CODEC = "libfreerdp/codec"
WEIGHTS = {"interleaved": 0.12, "planar": 0.12, "nsc": 0.08, "clear": 0.13, "rfx": 0.18,
           "progressive": 0.27, "zgfx": 0.10}
# files under libfreerdp/codec/ taken from /app (when present there as regular files)
EDITABLE = ["interleaved.c", "bitmap.c", "planar.c", "nsc.c", "nsc_encode.c", "nsc_encode.h", "nsc_types.h",
            "progressive.c", "progressive.h", "rfx.c", "rfx_*.c", "rfx_*.h", "clear.c", "zgfx.c", "include/*",
            "sse/*", "neon/*"]
NEW_SUFFIXES = (".c", ".h", ".inc")
MAX_FILE, MAX_TOTAL = 4 << 20, 32 << 20
CMAKE_FLAGS = ("-G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DBUILD_TESTING=OFF -DWITH_SIMD=OFF "
               "-DWITH_CCACHE=OFF -DWITH_CLANG_FORMAT=OFF -DWITH_CLIENT=OFF -DWITH_CLIENT_COMMON=OFF "
               "-DWITH_CLIENT_INTERFACE=OFF -DWITH_SERVER=OFF -DWITH_SAMPLE=OFF -DWITH_CHANNELS=OFF -DWITH_KRB5=OFF "
               "-DWITH_PKCS11=OFF -DWITH_SMARTCARD_EMULATE=OFF -DWITH_PCSC=OFF -DWITH_OSS=OFF -DWITH_ALSA=OFF "
               "-DWITH_PULSE=OFF -DWITH_FFMPEG=OFF -DWITH_SWSCALE=OFF -DWITH_JPEG=OFF -DWITH_CAIRO=OFF -DWITH_X11=OFF "
               "-DWITH_WAYLAND=OFF -DWITH_FUSE=OFF -DWITH_AAD=OFF -DWITH_UNICODE_BUILTIN=ON -DWITH_WINPR_TOOLS=OFF "
               "-DWITH_MANPAGES=OFF -DWITH_OPENH264=OFF -DWITH_SYSTEMD=OFF -DWITH_JSON_DISABLED=ON").split()

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
    "base_ok": None, "base_mismatch": [], "overlay": [], "skipped": [], "tamper": [],
    "build_seconds": 0.0, "run_seconds": 0.0, "build_log_tail": "", "sequences_crashed": 0,
    "expected_sealed": None, "leftovers_stopped": [], "wall_s": 0.0,
}
t0 = time.time()


def write():
    ev["wall_s"] = round(time.time() - t0, 1)
    with open(args.out, "w") as f:
        json.dump(ev, f, indent=1)


def gate(reason, cheat=False):
    ev["gate_reason"] = reason
    if cheat:
        ev["cheat_detected"] = True
    write()
    sys.exit(0)


def drop_privileges():
    os.setsid()
    os.setgroups([])
    os.setgid(args.uid)
    os.setuid(args.uid)


def as_candidate(cmd, timeout, env, cwd, out=subprocess.PIPE):
    p = subprocess.Popen(cmd, preexec_fn=drop_privileges, stdout=out, stderr=subprocess.STDOUT, env=env,
                         cwd=cwd)
    try:
        o, _ = p.communicate(timeout=timeout)
        return p.returncode, o or b""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        o, _ = p.communicate()
        return None, (o or b"") + b"\n[timeout]"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def editable(rel, base_has):
    if rel.startswith("test/") or rel == "CMakeLists.txt":
        return False
    if any(fnmatch.fnmatchcase(rel, p) for p in EDITABLE):
        return True
    depth_ok = rel.count("/") == 0 or rel.split("/", 1)[0] in ("include", "sse", "neon")
    return (not base_has) and depth_ok and rel.endswith(NEW_SUFFIXES)


def read_regular(path, limit=MAX_FILE):
    """Read a regular file without following symlinks or blocking on special files."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        chunks = []
        while True:
            b = os.read(fd, 1 << 20)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def parse_cases(path):
    import struct
    data = open(path, "rb").read()
    recs, pos = [], 0
    while pos < len(data):
        start = pos
        n = struct.unpack_from("<I", data, pos + 40)[0]
        pos += 44
        for _ in range(n):
            pos += 36
            pf = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + (1024 if pf else 0)
            ln = struct.unpack_from("<I", data, pos)[0]
            pos += 4 + ln
        recs.append(data[start:pos])
    return recs


try:
    try:
        ev["leftovers_stopped"] = json.loads(args.sweep).get("stopped", [])
    except ValueError:
        ev["leftovers_stopped"] = []

    # 1. the verifier's own tools must be the packaged ones; no preloaded libraries
    if args.tamper and os.path.isfile(args.tamper):
        with open(args.tamper) as f:
            ev["tamper"] = [ln.strip() for ln in f if ln.strip()][:10]
    if os.path.lexists("/etc/ld.so.preload"):
        ev["tamper"].append("/etc/ld.so.preload exists")
    if ev["tamper"]:
        gate("system files used by the verifier were modified: " + "; ".join(ev["tamper"][:3]), cheat=True)

    # 2. the pristine tree in the image must match the shipped manifest
    manifest = {}
    with open(os.path.join(DATA, "base.manifest")) as f:
        for ln in f:
            h, rel = ln.rstrip("\n").split("  ", 1)
            manifest[rel] = h
    seen, bad = set(), []
    for root, dirs, files in os.walk(args.base):
        for n in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, args.base)
            seen.add(rel)
            if rel not in manifest:
                bad.append("added " + rel)
            elif os.path.islink(p) or not os.path.isfile(p) or sha256_file(p) != manifest[rel]:
                bad.append("changed " + rel)
    bad += ["missing " + rel for rel in manifest if rel not in seen]
    ev["base_mismatch"] = bad[:20]
    ev["base_ok"] = not bad
    if bad:
        gate(f"the pristine tree {args.base} was modified ({len(bad)} files, e.g. {bad[0]})", cheat=True)

    # 3. work tree: pristine copy plus the editable codec files from /app
    work = tempfile.mkdtemp(prefix="grade-")
    os.chmod(work, 0o755)
    src = os.path.join(work, "src")
    shutil.copytree(args.base, src, symlinks=True)
    app_codec = os.path.join(args.app, CODEC)
    total = 0
    if os.path.isdir(app_codec) and not os.path.islink(app_codec):
        for root, dirs, files in os.walk(app_codec):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
            for n in sorted(files):
                p = os.path.join(root, n)
                rel = os.path.relpath(p, app_codec)
                base_has = os.path.lexists(os.path.join(args.base, CODEC, rel))
                if not editable(rel, base_has):
                    continue
                try:
                    content = read_regular(p)
                except OSError:
                    content = None
                if content is None or total + len(content) > MAX_TOTAL:
                    ev["skipped"].append(rel)
                    continue
                total += len(content)
                dst = os.path.join(src, CODEC, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if os.path.lexists(dst):
                    os.unlink(dst)
                with open(dst, "wb") as f:
                    f.write(content)
                ev["overlay"].append(rel)
    for root, dirs, files in os.walk(work):
        os.chown(root, args.uid, args.uid)
        for n in files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chown(p, args.uid, args.uid)
    home = os.path.join(work, "home")
    os.mkdir(home)
    os.chown(home, args.uid, args.uid)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8", "WLOG_LEVEL": "OFF"}

    # 4. build gate: configure and build libwinpr3 + libfreerdp3 as the candidate uid
    b0 = time.time()
    bdir = os.path.join(work, "build")
    rc, log = as_candidate(["cmake", "-S", src, "-B", bdir] + CMAKE_FLAGS, 900, env, work)
    if rc == 0:
        rc, log2 = as_candidate(["ninja", "-C", bdir, f"-j{args.jobs}", "freerdp"], 1800, env, work)
        log += log2
    ev["build_seconds"] = round(time.time() - b0, 1)
    ev["build_log_tail"] = log[-3000:].decode("utf-8", "replace")
    if rc != 0:
        errs = [ln for ln in log.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
        gate("library build failed" + (": " + errs[0][:300] if errs else ""))
    runner = os.path.join(work, "codec_runner")
    shutil.copy(os.path.join(HERE, "codec_runner.c"), os.path.join(work, "codec_runner.c"))
    os.chmod(os.path.join(work, "codec_runner.c"), 0o644)
    cc = ["gcc", "-O2", "-o", runner, os.path.join(work, "codec_runner.c"),
          "-I" + os.path.join(src, "include"), "-I" + os.path.join(bdir, "include"),
          "-I" + os.path.join(src, "winpr", "include"), "-I" + os.path.join(bdir, "winpr", "include"),
          "-L" + os.path.join(bdir, "libfreerdp"), "-L" + os.path.join(bdir, "winpr", "libwinpr"),
          "-lfreerdp3", "-lwinpr3", "-Wl,-rpath," + os.path.join(bdir, "libfreerdp"),
          "-Wl,-rpath," + os.path.join(bdir, "winpr", "libwinpr")]
    rc, log = as_candidate(cc, 300, env, work)
    if rc != 0:
        gate("the test runner does not link against the built library: " + log[-300:].decode("utf-8", "replace"))
    ev["build_ok"] = True

    # 5. sealing evidence: the candidate uid must not be able to read the expected results
    probe = subprocess.run(["setpriv", f"--reuid={args.uid}", f"--regid={args.uid}", "--clear-groups",
                            "test", "-r", os.path.join(DATA, "expected.json")])
    ev["expected_sealed"] = probe.returncode != 0

    # 6. run every hidden sequence (fixed denominator: a crash or timeout fails the remaining steps)
    r0 = time.time()
    recs = parse_cases(os.path.join(DATA, "cases.bin"))
    jobs = max(1, args.jobs)
    shards = [[] for _ in range(jobs)]
    sizes = [0] * jobs
    for rec in sorted(recs, key=len, reverse=True):
        k = sizes.index(min(sizes))
        shards[k].append(rec)
        sizes[k] += len(rec)
    cdir = os.path.join(work, "cases")
    os.mkdir(cdir)
    os.chmod(cdir, 0o755)
    paths = []
    for k, sh in enumerate(shards):
        p = os.path.join(cdir, f"shard{k}.bin")
        with open(p, "wb") as f:
            f.write(b"".join(sh))
        os.chmod(p, 0o644)
        paths.append(p)
    logdir = os.path.join(work, "logs")
    dumpdir = os.path.join(work, "dumps")
    for d in (logdir, dumpdir):
        os.mkdir(d)
        os.chown(d, args.uid, args.uid)

    def run_shard(p):
        return as_candidate([runner, p, "--timeout", "20", "--logdir", logdir, "--dump", dumpdir], 2400, env,
                            work)

    results, crashed = {}, set()
    with ThreadPoolExecutor(jobs) as ex:
        for rc, out in ex.map(run_shard, paths):
            for ln in out.decode("ascii", "replace").splitlines():
                p = ln.split()
                if len(p) >= 4 and p[0] == "R" and p[1].isdigit() and p[2].isdigit():
                    results.setdefault((int(p[1]), int(p[2])), (p[3],))
                elif len(p) >= 3 and p[0] == "X" and p[1].isdigit():
                    crashed.add(int(p[1]))
    subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], capture_output=True)
    ev["run_seconds"] = round(time.time() - r0, 1)
    ev["sequences_crashed"] = len(crashed)

    # 7. verdicts against the frozen expected results
    with open(os.path.join(DATA, "expected.json")) as f:
        expected = json.load(f)
    passed = {}
    buckets = {c: {"passed": 0, "total": 0, "weight": w} for c, w in WEIGHTS.items()}
    order = sorted(expected.items(), key=lambda kv: int(kv[0]))
    for kind in ("v", "t"):
        for sid, e in order:
            for i, st in enumerate(e["steps"]):
                if st["k"] != kind:
                    continue
                got = results.get((int(sid), i))
                if kind == "v":
                    # the buffer the runner wrote after this step is hashed here, outside candidate code
                    ok = False
                    if got and got[0] == "1":
                        try:
                            buf = read_regular(os.path.join(dumpdir, f"{int(sid):08d}-{i:04d}.raw"),
                                               limit=st["n"])
                        except OSError:
                            buf = None
                        ok = buf is not None and len(buf) == st["n"] and \
                            hashlib.sha256(buf).hexdigest() == st["s"]
                else:
                    ok = bool(got and got[0] == "0") and passed.get(tuple(st["p"]), False)
                passed[(int(sid), i)] = ok
                buckets[e["codec"]]["total"] += 1
                buckets[e["codec"]]["passed"] += int(ok)
    ev["buckets"] = buckets
    ev["cases_total"] = sum(b["total"] for b in buckets.values())
    ev["cases_passed"] = sum(b["passed"] for b in buckets.values())
    shutil.rmtree(work, ignore_errors=True)
except SystemExit:
    raise
except Exception as e:  # an exception in our own code is a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    write()
sys.exit(0)
