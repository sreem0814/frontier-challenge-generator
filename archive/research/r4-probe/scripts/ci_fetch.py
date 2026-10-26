"""Fetch root listing, CI workflows and build manifests for repos (text only; nothing is executed).
usage: python3 -I ci_fetch.py repos.txt outdir"""
import json, os, subprocess, sys, base64
from concurrent.futures import ThreadPoolExecutor

ROOT_FILES = {"Cargo.toml", "go.mod", "CMakeLists.txt", "meson.build", "configure", "configure.ac", "Makefile",
              "GNUmakefile", "makefile", "package.json", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
              "noxfile.py", "pytest.ini", "justfile", "Justfile", ".gitlab-ci.yml", ".travis.yml", "build.zig",
              "pnpm-lock.yaml", "yarn.lock", "package-lock.json", "Makefile.am", "BUILD.bazel", "WORKSPACE",
              "MODULE.bazel", "build.gradle", "pom.xml", "Taskfile.yml", ".cirrus.yml", "appveyor.yml"}
GET_CONTENT = {"Cargo.toml", "go.mod", "CMakeLists.txt", "meson.build", "Makefile", "GNUmakefile", "makefile",
               "package.json", "pyproject.toml", "setup.cfg", "tox.ini", "noxfile.py", "justfile", "Justfile",
               ".gitlab-ci.yml", ".travis.yml", "Makefile.am"}


def gh(path, raw=False):
    args = ["gh", "api", path]
    if raw:
        args += ["-H", "Accept: application/vnd.github.raw"]
    p = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        return None
    return p.stdout if raw else json.loads(p.stdout)


def one(repo, outdir):
    d = os.path.join(outdir, repo.replace("/", "__"))
    if os.path.exists(os.path.join(d, "meta.json")):
        return
    os.makedirs(d, exist_ok=True)
    meta = {"repo": repo}
    info = gh(f"repos/{repo}")
    if not info:
        meta["error"] = "repo"
        json.dump(meta, open(os.path.join(d, "meta.json"), "w"))
        return
    meta["lang"] = info.get("language")
    meta["branch"] = info.get("default_branch")
    tree = gh(f"repos/{repo}/git/trees/{meta['branch']}") or {}
    names = [t["path"] for t in tree.get("tree", [])]
    meta["root"] = names
    for n in names:
        if n in GET_CONTENT:
            c = gh(f"repos/{repo}/contents/{n}", raw=True)
            if c is not None:
                open(os.path.join(d, "f__" + n), "w").write(c[:400000])
    wf = gh(f"repos/{repo}/contents/.github/workflows") if ".github" in names else None
    meta["workflows"] = []
    for w in (wf or []):
        if isinstance(w, dict) and w.get("name", "").endswith((".yml", ".yaml")):
            c = gh(f"repos/{repo}/contents/.github/workflows/{w['name']}", raw=True)
            if c is not None:
                open(os.path.join(d, "wf__" + w["name"]), "w").write(c)
                meta["workflows"].append(w["name"])
    json.dump(meta, open(os.path.join(d, "meta.json"), "w"))


if __name__ == "__main__":
    repos = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda r: one(r, sys.argv[2]), repos))
