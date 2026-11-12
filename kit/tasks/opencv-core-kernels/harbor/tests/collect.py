"""tests/collect.py: evidence only. Rebuilds the candidate opencv_core from a clean tree, runs the gates and the timing.

Every path writes evidence.json; compute_reward.py makes the scoring decisions.

1. Toolchain integrity: the compiler, linker, C/C++ runtime, zlib and CMake packages must match their dpkg
   checksums, and no GCC specs file or loader preload may exist (the build flags are fixed by this script).
2. Clean build: the pristine tree (tests/base-src.tar.xz) with only modules/core/src/ taken from /app/opencv,
   configured with the fixed flags, built as an unprivileged user; then cvbench (tests/bench) is linked
   statically against it.
3. Correctness: the randomized check suite (seed drawn now) on the candidate and on the shipped build
   (tests/bin/cvbench-base); every record must match within its tolerance.
4. Timing: three cvbench servers (shipped build, candidate, optimized upstream build) are timed batch by batch
   in shuffled order on one CPU (perf.py). Each batch's outputs are checked against the shipped build. The
   candidate process must stay single-threaded and map no file besides its own binary.
"""
import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import perf  # noqa: E402  (tests/perf.py, the verifier's own module)

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--app", default="/app/opencv")
args = ap.parse_args()

CFG = json.load(open(os.path.join(HERE, "config.json")))
ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "build_log_tail": "", "src_files": 0, "src_bytes": 0, "src_changed_files": 0,
    "check_total": 0, "check_failed": 0, "check_failures": [],
    "timing_ok": False, "cases": [], "tamper": [], "times": {},
}
T0 = time.time()


def write():
    ev["times"]["total"] = round(time.time() - T0, 1)
    tmp = args.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ev, f)
    os.replace(tmp, args.out)


def gate(reason, cheat=False):
    if not ev["gate_reason"]:
        ev["gate_reason"] = reason
    if cheat:
        ev["cheat_detected"] = True


def kill_uid(uid):
    subprocess.run(["pkill", "-KILL", "-U", str(uid)], capture_output=True)


CLEAN_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "HOME": "/nonexistent",
             "CXX": "/usr/bin/x86_64-linux-gnu-g++-12"}


def run_as(cmd, uid, cwd, timeout, env=None):
    def pre():
        os.setsid()
        if uid is not None:
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
    e = dict(CLEAN_ENV)
    if env:
        e.update(env)
    p = subprocess.Popen(cmd, cwd=cwd, env=e, preexec_fn=pre, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.wait()
        return None, "timeout"


def toolchain_tamper():
    """The build must use the image's own compiler, binutils, C/C++ runtime, zlib and CMake, unmodified."""
    found = []
    pk = CFG["toolchain_packages"]
    r = subprocess.run(["dpkg", "--verify"] + pk, capture_output=True, text=True, timeout=600)
    for ln in r.stdout.splitlines():
        # dpkg --verify lists mismatching files; the third flag is 5 when the checksum differs
        parts = ln.split()
        if parts and len(parts[0]) >= 3 and parts[0][2] == "5":
            found.append("modified: " + parts[-1])
    if r.returncode not in (0, 1) or "not installed" in r.stderr:
        found.append("toolchain package missing or dpkg failed")
    owned = set()
    for p in pk:
        q = subprocess.run(["dpkg", "-L", p], capture_output=True, text=True, timeout=120)
        owned.update(x.strip() for x in q.stdout.splitlines())
    for top in CFG["toolchain_dirs"]:
        for root, dirs, files in os.walk(top):
            for f in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
                p = os.path.join(root, f)
                if p not in owned:
                    found.append("unowned file in toolchain: " + p)
    for link, target in CFG["toolchain_links"].items():
        if os.path.realpath(link) != target:
            found.append(f"{link} resolves to {os.path.realpath(link)}")
    for p in CFG["forbidden_files"]:
        if os.path.lexists(p):
            found.append("present: " + p)
    return found


def snapshot_sources(src, dst):
    """Copy modules/core/src from /app into dst; regular files only, bounded size."""
    nfiles = nbytes = 0
    bad = []
    for root, dirs, files in os.walk(src, followlinks=False):
        for d in list(dirs):
            if os.path.islink(os.path.join(root, d)):
                bad.append(os.path.relpath(os.path.join(root, d), src))
                dirs.remove(d)
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in files:
            p = os.path.join(root, f)
            if os.path.islink(p) or not os.path.isfile(p):
                bad.append(os.path.relpath(p, src))
                continue
            nfiles += 1
            nbytes += os.path.getsize(p)
            if nfiles > CFG["max_src_files"] or nbytes > CFG["max_src_bytes"]:
                raise ValueError("source tree too large")
            shutil.copyfile(p, os.path.join(dst, rel, f))
    return nfiles, nbytes, bad


def scan_sources(d, pristine):
    """Signals that the source reaches outside its tree (the verifier's files, prebuilt objects, loaders).

    A token counts only where it occurs more often than in the shipped version of the same file."""
    hits = []
    pats = [s.encode() for s in CFG["forbidden_source_tokens"]]
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, d)
            b = open(p, "rb").read()
            q = os.path.join(pristine, rel)
            o = open(q, "rb").read() if os.path.isfile(q) else b""
            for t in pats:
                if b.count(t) > o.count(t):
                    hits.append(f"{rel}: {t.decode()}")
    return hits


try:
    # ---------------------------------------------------------------- 0. runtime and toolchain
    for tool in ("g++", "cmake", "ninja", "dpkg"):
        if not shutil.which(tool, path=CLEAN_ENV["PATH"]):
            raise RuntimeError(f"{tool} missing from the image")
    up_bin = os.path.join(HERE, "bin", "cvbench-upstream")
    rc = subprocess.run([up_bin, "list"], capture_output=True, timeout=60).returncode
    if rc != 0:
        raise RuntimeError(f"cvbench-upstream does not run (exit {rc})")
    tam = toolchain_tamper()
    ev["tamper"] = tam
    if tam:
        gate("toolchain modified: " + "; ".join(tam[:5]), cheat=True)
        raise StopIteration

    # ---------------------------------------------------------------- 1. two clean trees: shipped (b) and candidate (c)
    # Same layout and path lengths, so an untouched candidate compiles to the same code as the shipped build.
    work = "/tmp/ock-verify"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    os.chmod(work, 0o755)
    t = time.time()
    for sub in ("b", "c"):
        os.makedirs(os.path.join(work, sub))
        with tarfile.open(os.path.join(HERE, "base-src.tar.xz")) as tf:
            try:
                tf.extractall(os.path.join(work, sub), filter="data")
            except TypeError:   # Python without extraction filters; the archive is the verifier's own
                tf.extractall(os.path.join(work, sub))
        shutil.copytree(os.path.join(HERE, "bench"), os.path.join(work, sub, "bench"))
    btree, ctree = os.path.join(work, "b", "opencv"), os.path.join(work, "c", "opencv")
    pristine = os.path.join(btree, "modules", "core", "src")
    core_src = os.path.join(ctree, "modules", "core", "src")
    shutil.rmtree(core_src)
    app_src = os.path.join(args.app, "modules", "core", "src")
    if not os.path.isdir(app_src):
        gate("modules/core/src is missing from /app/opencv")
        raise StopIteration
    nf, nb, bad = snapshot_sources(app_src, core_src)
    ev["src_files"], ev["src_bytes"] = nf, nb
    if bad:
        gate("symlinks or special files in modules/core/src: " + ", ".join(bad[:5]), cheat=True)
        raise StopIteration
    changed = 0
    for root, _, files in os.walk(core_src):
        for f in files:
            p = os.path.join(root, f)
            q = os.path.join(pristine, os.path.relpath(p, core_src))
            if not os.path.isfile(q) or open(p, "rb").read() != open(q, "rb").read():
                changed += 1
    for root, _, files in os.walk(pristine):
        for f in files:
            if not os.path.exists(os.path.join(core_src, os.path.relpath(os.path.join(root, f), pristine))):
                changed += 1
    ev["src_changed_files"] = changed
    hits = scan_sources(core_src, pristine)
    if hits:
        gate("source refers to files outside the tree: " + "; ".join(hits[:5]), cheat=True)
        raise StopIteration
    os.chmod(os.path.join(work, "b"), 0o700)
    subprocess.run(["chown", "-R", f"{args.uid}:{args.uid}", os.path.join(work, "c")], check=True)
    ev["times"]["prepare"] = round(time.time() - t, 1)

    def build(sub, uid):
        root = os.path.join(work, sub)
        tree, bdir = os.path.join(root, "opencv"), os.path.join(root, "build")
        rc, out = run_as(["cmake", "-S", tree, "-B", bdir] + CFG["cmake_args"], uid, root, 1800)
        log = out
        if rc == 0:
            rc, out = run_as(["ninja", "-C", bdir, "-j", str(CFG["build_jobs"]), "opencv_core"], uid, root,
                             CFG["build_timeout"])
            log += out
        if rc == 0:
            rc, out = run_as(["bash", os.path.join(root, "bench", "mkbench.sh"), tree, bdir,
                              os.path.join(root, "cvbench")], uid, root, 1200)
            log += out
        return rc, log

    # ---------------------------------------------------------------- 2. builds (fixed flags; candidate unprivileged)
    t = time.time()
    rc, log = build("b", None)
    if rc != 0:
        raise RuntimeError("the shipped tree did not build: " + log[-500:])
    base_bin = os.path.join(work, "b", "cvbench")
    ev["times"]["build_base"] = round(time.time() - t, 1)
    t = time.time()
    rc, log = build("c", args.uid)
    kill_uid(args.uid)
    ev["build_log_tail"] = log[-3000:]
    ev["times"]["build"] = round(time.time() - t, 1)
    if rc != 0:
        gate("build failed" if rc is not None else "build timed out")
        raise StopIteration
    cand_bin = os.path.join(work, "c", "cvbench")
    subprocess.run(["chown", "root:root", cand_bin], check=True)
    os.chmod(cand_bin, 0o755)
    ev["build_ok"] = True
    write()

    # ---------------------------------------------------------------- 3. correctness (randomized check suite)
    t = time.time()
    rng = random.Random(int.from_bytes(os.urandom(8), "little"))
    seed = rng.getrandbits(63)
    cdir = os.path.join(work, "c", "run")
    os.makedirs(cdir)
    subprocess.run(["chown", f"{args.uid}:{args.uid}", cdir], check=True)
    rdir = os.path.join(work, "b", "run")
    os.makedirs(rdir, mode=0o700)
    rc_b, out_b = run_as([base_bin, "check", str(seed), os.path.join(rdir, "check.bin")], None, rdir, 1200)
    if rc_b != 0:
        raise RuntimeError("shipped build failed its own check run: " + out_b[-300:])
    rc_c, out_c = run_as([cand_bin, "check", str(seed), os.path.join(cdir, "check.bin")], args.uid, cdir, 1800)
    kill_uid(args.uid)
    if rc_c != 0:
        ev["check_failures"] = ["check run " + ("timed out" if rc_c is None else f"exited with {rc_c}") + ": " +
                                out_c[-300:]]
        gate("correctness: the check suite did not complete")
        raise StopIteration
    r = subprocess.run([base_bin, "cmp", os.path.join(rdir, "check.bin"), os.path.join(cdir, "check.bin")],
                       capture_output=True, text=True, timeout=1800)
    lines = r.stdout.splitlines()
    tot = [ln for ln in lines if ln.startswith("TOTAL ")]
    if not tot:
        raise RuntimeError("cmp produced no total")
    ev["check_total"], ev["check_failed"] = int(tot[0].split()[1]), int(tot[0].split()[2])
    ev["check_failures"] = [ln for ln in lines if len(ln.split()) == 5 and ln.split()[1] == "0"][:40]
    ev["times"]["check"] = round(time.time() - t, 1)
    for p in (os.path.join(rdir, "check.bin"), os.path.join(cdir, "check.bin")):
        try:
            os.unlink(p)
        except OSError:
            pass
    if ev["check_failed"]:
        gate(f"correctness: {ev['check_failed']} of {ev['check_total']} check records differ from the shipped build")
        raise StopIteration
    write()

    # ---------------------------------------------------------------- 4. timing
    t = time.time()
    cpus = sorted(os.sched_getaffinity(0))
    cpu = cpus[-1] if CFG.get("pin_cpu", True) else None
    servers = {
        "base": perf.Server("base", base_bin, rdir, uid=None, cpu=cpu),
        "cand": perf.Server("cand", cand_bin, cdir, uid=args.uid, cpu=cpu),
        "up": perf.Server("up", up_bin, rdir, uid=None, cpu=cpu),
    }
    cases = perf.list_cases(base_bin)
    timed = {c["id"]: c for c in CFG["cases"]}
    cases = [c for c in cases if c["id"] in timed]
    if len(cases) != len(timed):
        raise RuntimeError("timed case list does not match the shipped build")
    maps_bad = []
    try:
        res = perf.measure(servers, cases, CFG["reps"], CFG["batch_seconds"], rng, base_bin,
                           {"base": rdir, "cand": cdir, "up": rdir}, ref="base", cand="cand")
        maps_bad = perf.foreign_maps(servers["cand"], cand_bin)
    finally:
        for s in servers.values():
            s.close()
        kill_uid(args.uid)
    ev["times"]["timing"] = round(time.time() - t, 1)
    for rr in res:
        ev["cases"].append({
            "id": rr["id"], "family": rr["family"], "iters": rr["iters"], "ok": rr["ok"], "why": rr["why"],
            "s": round(rr["ratio"].get("cand", 0.0), 5), "S": round(rr["ratio"].get("up", 0.0), 5),
            "t_base_ms": round(1e3 * sorted(rr["t"]["base"])[len(rr["t"]["base"]) // 2] / max(rr["iters"], 1), 5)
            if rr["t"]["base"] else 0,
        })
    if maps_bad:
        gate("the timed process mapped files other than its own binary: " + ", ".join(maps_bad[:4]), cheat=True)
        raise StopIteration
    if len(res) != len(cases):
        gate("timing: the candidate server stopped responding")
        raise StopIteration
    bad = [c for c in ev["cases"] if not c["ok"]]
    if bad:
        gate(f"timing case {bad[0]['id']}: {bad[0]['why']}")
        raise StopIteration
    ev["timing_ok"] = True
except StopIteration:
    pass
except Exception as e:  # our own failure: a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
    ev["traceback"] = traceback.format_exc()[-2000:]
finally:
    kill_uid(args.uid)
    write()
sys.exit(0)
