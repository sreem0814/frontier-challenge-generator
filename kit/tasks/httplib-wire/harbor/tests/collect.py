"""tests/collect.py: evidence only. Builds the graded programs against a copy of /app/httplib.h, runs every frozen
case and the upstream test binary, and writes evidence.json on every path. Nothing from /app is imported here.

Graded file: /app/httplib.h only (a regular file, not a symlink, at most 8 MB), copied into a fresh directory.
All compiling and running of candidate code happens as an unprivileged uid with /tests unreadable to it.

Parts:
  build gate   probe.cc and server.cc (tests/harness/) compile and link against the copy
  cases        tests/data/cases.jsonl.gz: library and client cases through probe, raw HTTP exchanges through server
  upstream     tests/gtest/test.cc (cpp-httplib v0.62.0's own suite) compiled against the copy; every listed test
               runs as its own process; a failed compile scores this part 0 (not a gate)
  canaries     tests that must fail, added to test.cc under realistic random names; any pass = cheat detected
"""
import argparse
import gzip
import json
import os
import random
import re
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--uid", type=int, default=65534)
ap.add_argument("--header", default="/app/httplib.h")
ap.add_argument("--jobs", type=int, default=8)
args = ap.parse_args()

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS)
import wire  # noqa: E402  (the grader's own module, from /tests)

HEADER_LIMIT = 8 * 1024 * 1024
DEFS = ["-DCPPHTTPLIB_ZLIB_SUPPORT", "-DCPPHTTPLIB_BROTLI_SUPPORT", "-DCPPHTTPLIB_ZSTD_SUPPORT"]
LIBS = ["-lz", "-lbrotlicommon", "-lbrotlienc", "-lbrotlidec", "-lzstd", "-lpthread"]
GTEST_TIMEOUT = 20
N_CANARY = 12

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "cases_credited": 0,
    "areas": {}, "gtest_build_ok": False, "gtest_total": 0, "gtest_passed": 0,
    "canaries_passed": 0, "errors_sample": [], "gtest_failed_sample": [], "wall_seconds": 0.0,
}
T0 = time.time()


def write():
    ev["wall_seconds"] = round(time.time() - T0, 1)
    with open(args.out, "w") as f:
        json.dump(ev, f)


def demote():
    os.setsid()
    os.setgroups([])
    os.setgid(args.uid)
    os.setuid(args.uid)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (6 << 30, 6 << 30))


def cand_env(home):
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "TMPDIR": home}


def run_cand(cmd, cwd, timeout, extra_env=None):
    env = cand_env(cwd)
    env.update(extra_env or {})
    p = subprocess.Popen(cmd, cwd=cwd, env=env, preexec_fn=demote, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    try:
        out, _ = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc, out = 124, b""
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.wait(timeout=5)
        except Exception:
            pass
    return rc, out.decode("utf-8", "replace")


def owned_dir(path):
    os.makedirs(path, exist_ok=True)
    os.chown(path, args.uid, args.uid)
    os.chmod(path, 0o755)
    return path


def load_cases():
    cases = []
    for l in gzip.open(os.path.join(TESTS, "data", "cases.jsonl.gz")):
        c = json.loads(l)
        if c["kind"] == "probe":
            c["args"] = [bytes.fromhex(a) for a in c["args"]]
        else:
            c["send"] = bytes.fromhex(c["send"])
        cases.append(c)
    return cases


def canary_source(names):
    out = ["\n// ---- grading canaries: each of these must fail ----\n"]
    for suite, name in names:
        out.append(f"TEST({suite}, {name}) {{\n  httplib::Headers h;\n  EXPECT_EQ(h.size() + 1, size_t(0));\n"
                   f"  ASSERT_TRUE(h.size() == 7);\n}}\n")
    return "".join(out)


def run_gtests(binary, gdir, names, work):
    """Each test in its own process, args.jobs at a time; worker k gets its own fixture copy and port block.
    Pass = exit 0 and gtest's own summary line for exactly one passed test."""
    dirs = []
    for k in range(args.jobs):
        d = os.path.join(work, f"gw{k}")
        shutil.copytree(gdir, d, ignore=shutil.ignore_patterns("gtest", "*.cc", "*.o"))
        for root, ds, fs in os.walk(d):
            os.chown(root, args.uid, args.uid)
            for f in fs:
                os.chown(os.path.join(root, f), args.uid, args.uid)
        dirs.append(d)
    res = {}
    q = list(names)
    lock = threading.Lock()

    def worker(k):
        while True:
            with lock:
                if not q:
                    return
                t = q.pop(0)
            rc, out = run_cand([binary, f"--gtest_filter={t}"], dirs[k], GTEST_TIMEOUT,
                               {"HTTPLIB_TEST_WORKER": str(k)})
            ok = rc == 0 and "[  PASSED  ] 1 test." in out and "[  FAILED  ]" not in out
            with lock:
                res[t] = ok

    th = [threading.Thread(target=worker, args=(k,)) for k in range(args.jobs)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    return res


try:
    # 1. runtime
    for tool in ("g++", "pkill"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} missing")
    cases = load_cases()
    ev["cases_total"] = len(cases)
    gt_names = [l.strip() for l in open(os.path.join(TESTS, "gtest", "tests.txt")) if l.strip()]
    ev["gtest_total"] = len(gt_names)

    WORK = tempfile.mkdtemp(prefix="grade-")
    os.chmod(WORK, 0o755)
    inc = owned_dir(os.path.join(WORK, "inc"))
    bld = owned_dir(os.path.join(WORK, "build"))

    # 2. the graded file
    src = args.header
    if not os.path.isfile(src) or os.path.islink(src):
        ev["gate_reason"] = "build: /app/httplib.h is missing or not a regular file"
    elif os.path.getsize(src) > HEADER_LIMIT:
        ev["gate_reason"] = "build: /app/httplib.h is larger than 8 MB"
    else:
        shutil.copyfile(src, os.path.join(inc, "httplib.h"))
        os.chmod(os.path.join(inc, "httplib.h"), 0o444)
        for f in ("probe.cc", "server.cc"):
            shutil.copyfile(os.path.join(TESTS, "harness", f), os.path.join(bld, f))
            os.chmod(os.path.join(bld, f), 0o444)

        # 3. build gate: probe and server
        def cc(name):
            return run_cand(["g++", "-std=c++17", "-O1", "-I" + inc] + DEFS +
                            [name + ".cc", "-o", name] + LIBS, bld, 900)
        with ThreadPoolExecutor(2) as ex:
            (rp, op), (rs, os_) = list(ex.map(cc, ["probe", "server"]))
        if rp == 0 and rs == 0 and os.path.isfile(os.path.join(bld, "probe")) \
                and os.path.isfile(os.path.join(bld, "server")):
            ev["build_ok"] = True
        else:
            ev["gate_reason"] = "build: httplib.h does not compile with the case programs: " + \
                (op if rp else os_)[-600:]

    if ev["build_ok"]:
        # 4. upstream suite, compiled in the background while the cases run
        gsrc = os.path.join(TESTS, "gtest")
        gdir = os.path.join(WORK, "gtest")
        shutil.copytree(gsrc, gdir)
        rng = random.SystemRandom()
        canaries = []
        words = ["Edge", "Basic", "Large", "Empty", "Invalid", "Multi", "Single", "Repeated", "Mixed", "Long"]
        plain = [t for t in gt_names if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", t)]
        for _ in range(N_CANARY):
            suite, name = rng.choice(plain).split(".", 1)
            canaries.append((suite, name + rng.choice(words) + str(rng.randint(2, 99))))
        with open(os.path.join(gdir, "test.cc"), "a") as f:
            f.write(canary_source(canaries))
        for root, ds, fs in os.walk(gdir):
            os.chown(root, args.uid, args.uid)
            for f in fs:
                os.chown(os.path.join(root, f), args.uid, args.uid)
        gt_out = {}

        def build_gtest():
            g = gdir
            flags = ["-std=c++17", "-O0", "-I" + inc, "-I" + g, "-I" + g + "/gtest/include", "-I" + g + "/gtest"] + DEFS
            jobs = [(["g++"] + flags + ["-c", "test.cc", "-o", "test.o"], 1500),
                    (["g++"] + flags + ["-c", "include_httplib.cc", "-o", "inc.o"], 900),
                    (["g++", "-std=c++17", "-O1", "-I" + g + "/gtest/include", "-I" + g + "/gtest", "-c",
                      "gtest/src/gtest-all.cc", "-o", "gtest-all.o"], 900),
                    (["g++", "-std=c++17", "-O1", "-I" + g + "/gtest/include", "-I" + g + "/gtest", "-c",
                      "gtest/src/gtest_main.cc", "-o", "gtest_main.o"], 900)]
            with ThreadPoolExecutor(4) as ex:
                rcs = list(ex.map(lambda j: run_cand(j[0], g, j[1]), jobs))
            if all(r == 0 for r, _ in rcs):
                rc, out = run_cand(["g++", "-o", "httplib_test", "test.o", "inc.o", "gtest-all.o", "gtest_main.o"] +
                                   LIBS, g, 600)
                gt_out["ok"] = rc == 0
                gt_out["log"] = out[-600:]
            else:
                gt_out["ok"] = False
                gt_out["log"] = next(o for r, o in rcs if r)[-600:]

        gt_thread = threading.Thread(target=build_gtest)
        gt_thread.start()

        # 5. cases
        probe = os.path.join(bld, "probe")
        server = os.path.join(bld, "server")
        pc = [c for c in cases if c["kind"] == "probe"]
        wc = [c for c in cases if c["kind"] == "wire"]
        deadline = time.time() + 2700

        def pshard(k):
            d = owned_dir(os.path.join(WORK, f"p{k}"))
            return wire.run_probe_shard(probe, pc[k::args.jobs], preexec=demote, env=cand_env(d), cwd=d,
                                        deadline=deadline)

        def wshard(k):
            d = owned_dir(os.path.join(WORK, f"w{k}"))
            return wire.run_wire_shard(server, 23100 + k, d, wc[k::args.jobs], preexec=demote, env=cand_env(d),
                                       deadline=deadline)

        results = {}
        with ThreadPoolExecutor(args.jobs) as ex:
            for r in ex.map(pshard, range(args.jobs)):
                results.update(r)
        with ThreadPoolExecutor(args.jobs) as ex:
            for r in ex.map(wshard, range(args.jobs)):
                results.update(r)
        # (no uid-wide kill here: the suite is still compiling as the same uid; each shard killed its own group)
        cred = wire.credit(cases, results)
        areas = wire.area_scores(cases, cred)
        ev["areas"] = {a: {"credited": g, "total": t} for a, (g, t) in areas.items()}
        ev["cases_passed"] = sum(1 for c in cases if results.get(c["id"]) == c["expect"])
        ev["cases_credited"] = sum(cred.values())
        for c in cases:
            if not cred[c["id"]] and len(ev["errors_sample"]) < 15:
                ev["errors_sample"].append(f"{c['id']} ({c['area']}/{c.get('op', 'wire')}): "
                                           f"{str(results.get(c['id']))[:120]}")

        # 6. upstream suite
        gt_thread.join()
        ev["gtest_build_ok"] = bool(gt_out.get("ok"))
        if ev["gtest_build_ok"]:
            names = gt_names + [f"{s}.{n}" for s, n in canaries]
            gres = run_gtests(os.path.join(gdir, "httplib_test"), gdir, names, WORK)
            subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], check=False)
            ev["gtest_passed"] = sum(1 for t in gt_names if gres.get(t))
            ev["canaries_passed"] = sum(1 for s, n in canaries if gres.get(f"{s}.{n}"))
            ev["gtest_failed_sample"] = [t for t in gt_names if not gres.get(t)][:15]
            if ev["canaries_passed"]:
                ev["cheat_detected"] = True
                ev["gate_reason"] = (f"anti-cheat: {ev['canaries_passed']} of {N_CANARY} tests written to fail "
                                     "reported success")
        else:
            ev["gtest_failed_sample"] = ["(build) " + gt_out.get("log", "")[-300:]]
except Exception as e:  # our own failure: a harness fault, not the candidate's
    ev["runtime_ok"], ev["runtime_error"] = False, f"{type(e).__name__}: {e}"
finally:
    try:
        subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], check=False)
    except Exception:
        pass
    write()
sys.exit(0)
