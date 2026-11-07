"""tests/collect.py: evidence only. Rebuilds libllama and llama-common from the pristine tree plus the three
implementation files from /app, runs the hidden cases through case_runner, checks the converted grammars of the
schema_lang cases with the original grammar engine, and writes evidence.json.

Every path writes evidence.json. The build and the cases run as an unprivileged uid in their own process groups
with time limits; the hidden data stays readable by root only while candidate code runs. case_runner forks one
process per case and frames each transcript. For every bucket but schema_lang the transcript is hashed here
(SHA-256) and compared with the frozen hash of the reference transcript. For schema_lang the transcript is the
grammar the candidate's converter produced; after every candidate process is gone, that grammar is matched
against the case's hidden strings by a matcher built here from the original engine, and the case passes when
every verdict (accepted, valid prefix, rejected) equals the frozen one. compute_reward.py turns the evidence
into the reward.
"""
import argparse
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
ap.add_argument("--base", default="/usr/src/llama-base")
ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--tamper", default="", help="file with dpkg --verify findings for the verifier's packages")
ap.add_argument("--sweep", default="{}", help="JSON line from sweep.py: session leftovers that were stopped")
args = ap.parse_args()

DATA = os.path.join(HERE, "data")
WEIGHTS = {"gbnf_parse": 0.09, "gbnf_match": 0.11, "gbnf_stacks": 0.06, "gbnf_tokens": 0.12,
           "schema_doc": 0.12, "schema_text": 0.24, "schema_lang": 0.26}
# The deliverable: these three files from /app replace the stubs in a pristine copy of the tree.
TARGETS = ["src/llama-grammar.cpp", "common/json-schema.cpp", "common/json-schema-to-grammar.cpp"]
MAX_FILE = 4 << 20
CXX = "/usr/bin/x86_64-linux-gnu-g++-12"
LDSO_CONF_D = {"libc.conf", "x86_64-linux-gnu.conf"}

ev = {
    "runtime_ok": True, "runtime_error": "",
    "build_ok": False, "cheat_detected": False, "gate_reason": "",
    "cases_total": 0, "cases_passed": 0, "buckets": {},
    "base_ok": None, "base_mismatch": [], "overlay": [], "skipped": [], "tamper": [],
    "build_seconds": 0.0, "run_seconds": 0.0, "match_seconds": 0.0, "build_log_tail": "", "cases_crashed": 0,
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
    p = subprocess.Popen(cmd, preexec_fn=drop_privileges, stdout=out, stderr=subprocess.STDOUT, env=env, cwd=cwd)
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


def as_root(cmd, timeout, env, cwd):
    p = subprocess.Popen(cmd, preexec_fn=os.setsid, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
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


def parse_frames(data, keep):
    """case_runner output: 'C <id> <bucket> <n>\\n<n bytes>' or 'X <id> <bucket> <reason>'.
    Transcripts of buckets in `keep` are kept as bytes, the others as (sha256, length)."""
    res, pos, n = {}, 0, len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl < 0:
            break
        head = data[pos:nl].split(b" ")
        pos = nl + 1
        if len(head) == 4 and head[0] == b"C" and head[3].isdigit():
            ln = int(head[3])
            cid, bucket = head[1].decode("ascii", "replace"), head[2].decode("ascii", "replace")
            body = data[pos:pos + ln]
            res.setdefault(cid, ("C", body if bucket in keep else hashlib.sha256(body).hexdigest(), len(body)))
            pos += ln
        elif len(head) >= 3 and head[0] == b"X":
            res.setdefault(head[1].decode("ascii", "replace"), ("X", "", 0))
        else:
            break  # unframed output: everything after it counts as missing
    return res


def split_cases(path):
    blocks, cur = [], []
    with open(path) as f:
        for line in f:
            cur.append(line)
            if line == "END\n":
                blocks.append("".join(cur))
                cur = []
    return blocks


def verdicts(frame):
    out = []
    for line in frame.decode("utf-8", "replace").splitlines()[1:]:
        w = line.split()
        out.append(w[1] if len(w) >= 2 else "?")
    return out


try:
    try:
        ev["leftovers_stopped"] = json.loads(args.sweep).get("stopped", [])
    except ValueError:
        ev["leftovers_stopped"] = []

    # 1. the verifier's own tools must be the packaged ones; no preloaded or redirected libraries
    if args.tamper and os.path.isfile(args.tamper):
        with open(args.tamper) as f:
            ev["tamper"] = [ln.strip() for ln in f if ln.strip()][:10]
    if os.path.lexists("/etc/ld.so.preload"):
        ev["tamper"].append("/etc/ld.so.preload exists")
    try:
        extra = sorted(set(os.listdir("/etc/ld.so.conf.d")) - LDSO_CONF_D)
    except OSError:
        extra = []
    if extra:
        ev["tamper"].append("/etc/ld.so.conf.d has extra entries: " + ", ".join(extra[:3]))
    if os.path.islink(CXX) or not os.path.isfile(CXX):
        ev["tamper"].append(CXX + " is not the packaged compiler")
    if ev["tamper"]:
        gate("system files used by the verifier were modified: " + "; ".join(ev["tamper"][:3]), cheat=True)

    # 2. the pristine tree in the image must match the shipped manifest (SHA-256 of the content, then SHA-256 of
    #    the relative path, one file per line)
    manifest = {}
    with open(os.path.join(DATA, "base.manifest")) as f:
        for ln in f:
            h, ph = ln.split()
            manifest[ph] = h
    seen, bad = set(), []
    for root, dirs, files in os.walk(args.base):
        for n in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, args.base)
            ph = hashlib.sha256(rel.encode("utf-8", "surrogateescape")).hexdigest()
            seen.add(ph)
            if ph not in manifest:
                bad.append("added " + rel)
            elif os.path.islink(p) or not os.path.isfile(p) or sha256_file(p) != manifest[ph]:
                bad.append("changed " + rel)
    missing = sum(1 for ph in manifest if ph not in seen)
    if missing:
        bad.append(f"{missing} files missing")
    ev["base_mismatch"] = bad[:20]
    ev["base_ok"] = not bad
    if bad:
        gate(f"the pristine tree {args.base} was modified ({len(bad)} files, e.g. {bad[0]})", cheat=True)

    # 3. work tree: pristine copy plus the three implementation files from /app
    work = tempfile.mkdtemp(prefix="grade-")
    os.chmod(work, 0o755)
    src = os.path.join(work, "src")
    shutil.copytree(args.base, src, symlinks=True)
    for rel in TARGETS:
        try:
            content = read_regular(os.path.join(args.app, rel))
        except OSError:
            content = None
        if content is None:
            ev["skipped"].append(rel)  # missing, a symlink, not a regular file or too large: the stub stays
            continue
        dst = os.path.join(src, rel)
        os.unlink(dst)
        with open(dst, "wb") as f:
            f.write(content)
        ev["overlay"].append(rel)
    hdir = os.path.join(work, "harness")
    os.mkdir(hdir)
    for n in ("case_runner.cpp", "CMakeLists.txt"):
        shutil.copy(os.path.join(HERE, "harness", n), os.path.join(hdir, n))
    for root, dirs, files in os.walk(work):
        os.chown(root, args.uid, args.uid)
        for n in files:
            p = os.path.join(root, n)
            if not os.path.islink(p):
                os.chown(p, args.uid, args.uid)
    home = os.path.join(work, "home")
    os.mkdir(home)
    os.chown(home, args.uid, args.uid)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": home, "LANG": "C.UTF-8"}

    # 4. build gate: configure and build libllama, llama-common and case_runner as the candidate uid
    b0 = time.time()
    bdir = os.path.join(work, "build")
    rc, log = as_candidate(["cmake", "-S", hdir, "-B", bdir, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                            f"-DTREE={src}"], 600, env, work)
    if rc == 0:
        rc, log2 = as_candidate(["ninja", "-C", bdir, f"-j{args.jobs}", "case_runner"], 2400, env, work)
        log += log2
    ev["build_seconds"] = round(time.time() - b0, 1)
    ev["build_log_tail"] = log[-3000:].decode("utf-8", "replace")
    runner = os.path.join(bdir, "case_runner")
    if rc != 0 or not os.path.isfile(runner):
        errs = [ln for ln in log.decode("utf-8", "replace").splitlines() if "error" in ln.lower()]
        gate("library or case_runner build failed" + (": " + errs[0][:300] if errs else ""))
    ev["build_ok"] = True

    # 5. sealing evidence: the candidate uid must not be able to read the expected results
    probe = subprocess.run(["setpriv", f"--reuid={args.uid}", f"--regid={args.uid}", "--clear-groups",
                            "test", "-r", os.path.join(DATA, "expected.json")])
    ev["expected_sealed"] = probe.returncode != 0

    # 6. run every hidden case (fixed denominator: a crash, timeout or missing transcript fails the case)
    r0 = time.time()
    blocks = split_cases(os.path.join(DATA, "cases.txt"))
    jobs = max(1, args.jobs)
    cdir = os.path.join(work, "cases")
    os.mkdir(cdir)
    os.chmod(cdir, 0o755)
    paths = []
    for k in range(jobs):
        p = os.path.join(cdir, f"shard{k}.txt")
        with open(p, "w") as f:
            f.write("".join(blocks[k::jobs]))
        os.chmod(p, 0o644)
        paths.append(p)
    models = os.path.join(src, "models")

    def run_shard(p):
        return as_candidate([runner, p, "--models", models, "--timeout", "10"], 2400, env, work)

    results = {}
    with ThreadPoolExecutor(jobs) as ex:
        for rc, out in ex.map(run_shard, paths):
            for k, v in parse_frames(out, {"schema_lang"}).items():
                results.setdefault(k, v)
    subprocess.run(["pkill", "-KILL", "-U", str(args.uid)], capture_output=True)
    ev["run_seconds"] = round(time.time() - r0, 1)
    ev["cases_crashed"] = sum(1 for v in results.values() if v[0] == "X")

    with open(os.path.join(DATA, "expected.json")) as f:
        expected = json.load(f)

    # 7. schema_lang: build the matcher from the original engine (root only, static) and match the candidate's
    #    grammars against the hidden strings, now that no candidate process is left
    m0 = time.time()
    lverdicts = {}
    lcases = []
    for cid, e in expected.items():
        if e["k"] != "L":
            continue
        got = results.get(cid)
        if got and got[0] == "C" and got[1].startswith(b"OK\n"):
            lcases.append(f"CASE {cid} schema_lang M\nG {got[1][3:].hex()}\n" +
                          "".join(f"S {h}\n" for h in e["strings"]) + "END\n")
    if lcases:
        mdir = tempfile.mkdtemp(prefix="match-")
        os.chmod(mdir, 0o700)
        matcher = os.path.join(mdir, "matcher")
        renv = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
        rc, log = as_root([CXX, "-std=c++17", "-O2", "-static", "-DMATCH_ONLY", f"-I{args.base}/include",
                           f"-I{args.base}/src", f"-I{args.base}/ggml/include",
                           os.path.join(HERE, "harness", "case_runner.cpp"),
                           os.path.join(HERE, "harness", "match_shim.cpp"),
                           os.path.join(HERE, "ref", "llama-grammar.cpp"), "-o", matcher], 900, renv, mdir)
        if rc != 0 or not os.path.isfile(matcher):
            raise RuntimeError("matcher build failed: " + log[-500:].decode("utf-8", "replace"))
        mshards = [os.path.join(mdir, f"m{k}.txt") for k in range(jobs)]
        for k, p in enumerate(mshards):
            with open(p, "w") as f:
                f.write("".join(lcases[k::jobs]))

        def run_match(p):
            return as_root([matcher, p, "--timeout", "20"], 2400, renv, mdir)

        with ThreadPoolExecutor(jobs) as ex:
            for rc, out in ex.map(run_match, mshards):
                for k, v in parse_frames(out, {"schema_lang"}).items():
                    if v[0] == "C":
                        lverdicts.setdefault(k, verdicts(v[1]))
        shutil.rmtree(mdir, ignore_errors=True)
    ev["match_seconds"] = round(time.time() - m0, 1)

    # 8. verdicts against the frozen expectations
    buckets = {b: {"passed": 0, "total": 0, "weight": w} for b, w in WEIGHTS.items()}
    for cid, e in expected.items():
        if e["k"] == "L":
            ok = lverdicts.get(cid) == e["v"]
        else:
            got = results.get(cid)
            ok = bool(got and got[0] == "C" and got[2] == e["n"] and got[1] == e["s"])
        buckets[e["b"]]["total"] += 1
        buckets[e["b"]]["passed"] += int(ok)
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
