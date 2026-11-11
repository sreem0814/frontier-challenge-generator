"""Run one flatc case and reduce what it did to a transcript digest.

Shared by collect.py (grading) and the generator that froze the expected results, so both sides compute the
transcript the same way. A case is a set of input files written into an empty directory and one flatc command
line run there (argv[0] is "flatc", outputs go to ./out). The transcript records:
  - whether flatc succeeded (exit status 0) or failed (any other status, a signal or a timeout),
  - for the diagnostics-style buckets, everything flatc printed (stdout, then stderr), with the absolute case
    directory replaced by "@",
  - every file under ./out, by relative path and SHA-256 of its bytes.
The schema_model view decodes the single .bfbs file under ./out with bfbsdec and hashes the canonical text.
"""
import base64
import hashlib
import os
import resource
import signal
import stat
import subprocess

import bfbsdec

PRINTS = {"diag", "conform", "proto"}   # buckets whose printed messages are part of the transcript
MAX_OUT = 64 << 20


def materialize(files, d):
    """files: {relpath: base64 text}. Paths are relative, without '..'."""
    for rel, b64 in files.items():
        if rel.startswith("/") or ".." in rel.split("/"):
            raise ValueError("bad path " + rel)
        p = os.path.join(d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(base64.b64decode(b64))


def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUT, MAX_OUT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(flatc, argv, cwd, timeout=20, preexec=None, env=None):
    """Run flatc in cwd. Returns (status, stdout, stderr); status None means a timeout."""

    def pre():
        if preexec:
            preexec()
        _limits()

    p = subprocess.Popen(["flatc"] + list(argv), executable=flatc, cwd=cwd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=pre,
                         env=env or {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    try:
        out, err = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        p.kill()
        out, err = p.communicate()
        rc = None
    return rc, out[:MAX_OUT], err[:MAX_OUT]


def out_files(cwd):
    """[(relpath, bytes)] for every regular file under cwd/out, sorted; symlinks and other types are noted."""
    base = os.path.join(cwd, "out")
    res = []
    if not os.path.isdir(base) or os.path.islink(base):
        return res
    for root, dirs, files in os.walk(base):
        dirs.sort()
        for n in sorted(files):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, base)
            st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode):
                res.append((rel, b"\0not a regular file"))
                continue
            with open(p, "rb") as f:
                res.append((rel, f.read(MAX_OUT)))
    return res


def transcript(bucket, rc, out, err, cwd):
    ok = rc == 0
    t = ["status %s" % ("ok" if ok else "fail")]
    if bucket in PRINTS:
        a = cwd.encode()
        t.append("stdout " + out.replace(a, b"@").decode("utf-8", "backslashreplace"))
        t.append("stderr " + err.replace(a, b"@").decode("utf-8", "backslashreplace"))
    files = out_files(cwd) if ok or bucket in PRINTS else []
    for rel, data in files:
        t.append("file %s %s" % (rel, hashlib.sha256(data).hexdigest()))
    return "\n".join(t) + "\n", files


def digest(text):
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


def model_digest(rc, files):
    """Canonical decoded view of the single binary schema written under ./out, or None."""
    if rc != 0:
        return None
    bf = [d for rel, d in files if rel.endswith(".bfbs")]
    if len(bf) != 1:
        return None
    try:
        return hashlib.sha256(bfbsdec.decode(bf[0]).encode()).hexdigest()
    except (ValueError, IndexError, UnicodeDecodeError, RecursionError, KeyError):
        return None
