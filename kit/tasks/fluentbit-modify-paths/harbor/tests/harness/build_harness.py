"""Compile modify_harness.c against a configured and built Fluent Bit tree.

usage: python3 -I build_harness.py <source tree> <build dir> <harness.c> <output binary>

The include and define flags are taken from the build's compile_commands.json entry for
plugins/filter_modify/modify.c, so the harness sees exactly the headers the filter was built with.
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path


def flags_for(build: Path) -> list:
    cc = json.loads((build / "compile_commands.json").read_text())
    for entry in cc:
        if entry["file"].endswith("plugins/filter_modify/modify.c"):
            args = entry.get("arguments") or shlex.split(entry["command"])
            out = []
            for a in args:
                if a.startswith("-I") or a.startswith("-D"):
                    out.append(a)
            return out
    raise SystemExit("modify.c not found in compile_commands.json")


def main() -> int:
    src, build, harness, out = (Path(a) for a in sys.argv[1:5])
    lib = build / "lib"
    cmd = ["cc", "-O1", "-g", "-o", str(out), str(harness)] + flags_for(build) + [
        "-L" + str(lib), "-lfluent-bit", "-Wl,-rpath," + str(lib), "-lpthread", "-lm"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-4000:])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
