"""Stop processes left over from the agent's session that could interfere with grading.

Run by test.sh as root (python3 -I -S) before the reward files are cleared and again before they are
written. Stopped, by PID: shell and interpreter processes (bash, sh, python, node, perl, sleep, ...) whose
working directory or command line points into the workspace or a scratch location, and any process whose
executable lives there (/app, /tmp, /var/tmp, /dev/shm, /root, /home, /logs). PID 1, this process and its
ancestors (the harness that runs the verifier) and container keepalives (sleep infinity, tail -f /dev/null)
are never touched. Prints one JSON line with what it found.
"""
import json
import os
import re
import signal
import sys
import time

KEEPALIVE = (["sleep", "infinity"], ["/bin/sleep", "infinity"], ["/usr/bin/sleep", "infinity"],
             ["tail", "-f", "/dev/null"], ["sh", "-c", "sleep infinity"], ["/bin/sh", "-c", "sleep infinity"])
WATCH = ("/app", "/tmp", "/var/tmp", "/dev/shm", "/root", "/home", "/logs", "/run/user")
INTERP = re.compile(r"^((ba|da|z|k|c|tc|fi)?sh|python[0-9.]*|node|nodejs|perl[0-9.]*|ruby[0-9.]*|sleep|timeout|"
                    r"nohup|setsid|socat|nc|ncat|netcat|busybox|env|awk|gawk|mawk|watch|yes|xargs|"
                    r"find|inotifywait|stdbuf|nice|ionice|script|expect|tclsh[0-9.]*|lua[0-9.]*|php[0-9.]*|"
                    r"gdb|make|ninja|cmake)$")


def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def info(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
    except OSError:
        return None
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = ""
    try:
        with open(f"/proc/{pid}/comm") as f:
            comm = f.read().strip()
    except OSError:
        comm = ""
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        cwd = ""
    return argv, exe, comm, cwd


def sweep():
    keep = ancestors() | {1}
    killed = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid in keep:
            continue
        got = info(pid)
        if not got:
            continue
        argv, exe, comm, cwd = got
        if not argv or argv in KEEPALIVE:
            continue
        prog = os.path.basename(exe) or comm
        interp = INTERP.match(prog) or INTERP.match(comm) or INTERP.match(os.path.basename(argv[0]))
        touches = cwd.startswith(WATCH) or any(w in a for a in argv for w in WATCH)
        local_exe = exe.startswith(WATCH)
        if not ((interp and touches) or local_exe):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append({"pid": pid, "cmd": " ".join(argv)[:160], "cwd": cwd[:80]})
        except OSError:
            pass
    return killed


found = []
for _ in range(3):           # repeat: a watchdog may respawn a child between passes
    k = sweep()
    found += k
    if not k:
        break
    time.sleep(0.2)
print(json.dumps({"stopped": found[:40], "count": len(found)}))
sys.exit(0)
