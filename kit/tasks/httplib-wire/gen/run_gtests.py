"""gen/run_gtests.py: run every test of a gtest binary as its own process, N at a time.

usage: python3 -I run_gtests.py <binary> <gtest dir> <out.json> [--jobs 8] [--timeout 20] [--filter list.txt]
Each worker k gets its own copy of the fixture dir and HTTPLIB_TEST_WORKER=k (own port block, own socket names).
Writes {"test name": rc, ...}; rc 0 = pass, 124 = timeout.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

binary, gdir, out = sys.argv[1], sys.argv[2], sys.argv[3]
jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 8
tmo = float(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 20
names = None
if "--filter" in sys.argv:
    names = [l.strip() for l in open(sys.argv[sys.argv.index("--filter") + 1]) if l.strip()]
if names is None:
    p = subprocess.run([binary, "--gtest_list_tests"], capture_output=True, text=True, timeout=60)
    names, suite = [], ""
    for l in p.stdout.splitlines():
        if not l.startswith(" "):
            suite = l.split()[0]
        else:
            names.append(suite + l.split()[0])

work = tempfile.mkdtemp(prefix="gt-")
dirs = []
for k in range(jobs):
    d = os.path.join(work, f"w{k}")
    shutil.copytree(gdir, d, ignore=shutil.ignore_patterns("gtest", "*.cc"))
    dirs.append(d)
res = {}
lock = threading.Lock()
queue = list(names)


def worker(k):
    env = {"PATH": "/usr/bin:/bin", "HOME": dirs[k], "HTTPLIB_TEST_WORKER": str(k), "LANG": "C.UTF-8"}
    while True:
        with lock:
            if not queue:
                return
            t = queue.pop(0)
        p = subprocess.Popen([binary, f"--gtest_filter={t}"], cwd=dirs[k], env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            rc = p.wait(timeout=tmo)
        except subprocess.TimeoutExpired:
            rc = 124
        try:
            os.killpg(p.pid, 9)
        except ProcessLookupError:
            pass
        p.wait()
        with lock:
            res[t] = rc


t0 = time.time()
th = [threading.Thread(target=worker, args=(k,)) for k in range(jobs)]
for x in th:
    x.start()
for x in th:
    x.join()
shutil.rmtree(work, ignore_errors=True)
json.dump(res, open(out, "w"), indent=0, sort_keys=True)
print(f"{len(res)} tests, {sum(1 for v in res.values() if v == 0)} pass, {time.time() - t0:.0f} s")
