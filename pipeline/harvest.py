"""harvest.py: zero-token source harvesting and enrichment for cgpipe (plain HTTP and `gh api`, no model calls).

Harvesters turn a channel's `harvest` list in config.json into source rows. The enricher adds GitHub facts to rows
(stars, SPDX licence, archived, last push, language, latest release, open PRs, test-suite size) and a priority score
the writer uses to pick its batch.

Every function here is safe to call from a worker thread; nothing writes project state except through the caller.
"""
import ast
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "cgpipe-harvest (private research)"}
TEST_DIR_RX = re.compile(r"(^|/)(tests?|testdata|test-?suite|fixtures?|spec|conformance|test-?vectors|corpus|testcases?)(/|$)",
                         re.I)
_last_search = [0.0]


class ApiError(Exception):
    """The API could not be reached or refused (network, auth, rate limit): an error, never an empty result."""


def _gh(args, timeout=60):
    """Run `gh api ...` in its own session (Ctrl-C reaches only the runner). Returns parsed JSON. GraphQL answers
    with errors for some aliases still carry data for the others, so stdout is parsed even when gh exits non-zero."""
    try:
        p = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=timeout, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ApiError(f"gh: {type(e).__name__}")
    try:
        d = json.loads(p.stdout)
    except ValueError:
        raise ApiError(f"gh exit {p.returncode}: {(p.stderr or '').strip()[:200]}")
    if p.returncode != 0 and not (isinstance(d, dict) and d.get("data")):
        raise ApiError(f"gh exit {p.returncode}: {str(d.get('message') if isinstance(d, dict) else d)[:200]}")
    return d


def _search_pause():
    """GitHub search allows 30 requests a minute: keep at least 2.1 s between calls."""
    wait = _last_search[0] + 2.1 - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_search[0] = time.time()


def _http_json(url, timeout=60):
    try:
        return json.loads(_http_text(url, timeout))
    except ValueError as e:
        raise ApiError(f"{url[:60]}: not JSON: {str(e)[:80]}")


def _http_text(url, timeout=60):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        raise ApiError(f"{url[:60]}: {type(e).__name__}: {str(e)[:120]}")


def _row(cls, typ, name, url, **kw):
    r = {"class": cls, "type": typ, "name": name, "url": url, "version": "", "licence": "", "surface": "",
         "reference": "", "notes": ""}
    r.update({k: ("" if v is None else v) for k, v in kw.items()})
    return r


# ---------------------------------------------------------------- harvesters (one per `kind` in config.json)
def gh_repo_search(spec, cls):
    _search_pause()
    q = urllib.parse.quote(spec["q"])
    d = _gh([f"search/repositories?q={q}&sort=stars&order=desc&per_page={spec.get('n', 30)}"])
    rows = []
    for it in (d or {}).get("items", []):
        lic = (it.get("license") or {}).get("spdx_id") or ""
        rows.append(_row(cls, spec.get("type", "repo"), it["full_name"], it["html_url"], licence=lic,
                         notes=(it.get("description") or "")[:200]))
    return rows


ISSUE_Q = """query($q:String!){ search(query:$q, type:ISSUE, first:%d){ nodes{ ... on Issue{
  title url number createdAt comments{totalCount} reactions(content:THUMBS_UP){totalCount}
  closedByPullRequestsReferences(includeClosedPrs:true){totalCount}
  repository{ nameWithOwner url stargazerCount isArchived pushedAt licenseInfo{spdxId} primaryLanguage{name} } } } } }"""


def gh_issue_search(spec, cls):
    _search_pause()
    d = _gh(["graphql", "-f", f"query={ISSUE_Q % spec.get('n', 20)}", "-f", f"q={spec['q']}"])
    rows = []
    for n in ((d or {}).get("data") or {}).get("search", {}).get("nodes", []):
        if not n or n["closedByPullRequestsReferences"]["totalCount"]:
            continue                       # someone already has a PR for it
        repo = n["repository"]
        rows.append(_row(cls, spec.get("type", "feature-issue"), f"{repo['nameWithOwner']}#{n['number']}: {n['title'][:90]}",
                         n["url"], licence=(repo.get("licenseInfo") or {}).get("spdxId") or "",
                         surface=f"{n['reactions']['totalCount']} upvotes, {n['comments']['totalCount']} comments",
                         notes=f"repo {repo['url']}; opened {n['createdAt'][:10]}"))
    return rows


def gh_pr_search(spec, cls):
    _search_pause()
    q = urllib.parse.quote(spec["q"])
    d = _gh([f"search/issues?q={q}&sort=reactions&order=desc&per_page={spec.get('n', 30)}"])
    rows = []
    for it in (d or {}).get("items", []):
        repo = it["repository_url"].split("/repos/")[-1]
        rows.append(_row(cls, spec.get("type", "perf-pr"), f"{repo}#{it['number']}: {it['title'][:90]}",
                         it["html_url"], surface=f"{it.get('comments', 0)} comments",
                         notes=f"repo https://github.com/{repo}; merged PR or fixed issue"))
    return rows


def crates_search(spec, cls):
    d = _http_json(f"https://crates.io/api/v1/crates?q={urllib.parse.quote(spec['q'])}&sort=downloads&per_page=100")
    rx = re.compile(spec.get("match", r"pure[- ]rust (implementation|port|rewrite)|port of|rewrite of|re-?implementation of"), re.I)
    rows = []
    for c in d.get("crates", []):
        if rx.search(c.get("description") or "") and c.get("repository"):
            rows.append(_row(cls, "existing-port", f"crate {c['name']}", c["repository"], version=c.get("max_version", ""),
                             reference=f"crates.io/{c['name']} {c.get('max_version', '')}",
                             notes=(c.get("description") or "")[:200]))
    return rows


def npm_search(spec, cls):
    d = _http_json(f"https://registry.npmjs.org/-/v1/search?text={urllib.parse.quote(spec['q'])}&size=250&popularity=1.0")
    rx = re.compile(spec.get("match", r"^(a |an )?(pure |native )?(\w+ )?port of"), re.I)
    rows = []
    for o in (d or {}).get("objects", []):
        p = o.get("package", {})
        repo = ((p.get("links") or {}).get("repository")) or ""
        if rx.search(p.get("description") or "") and "github.com" in repo:
            rows.append(_row(cls, "existing-port", f"npm {p['name']}", repo, version=p.get("version", ""),
                             licence=p.get("license", "") or "", notes=(p.get("description") or "")[:200]))
    return rows


def homebrew(spec, cls):
    d = _http_json("https://formulae.brew.sh/api/formula.json", timeout=180)
    rx = re.compile(spec.get("match", r"assembler|disassembler|formatter|converter|calculator|compiler|parser|"
                                      r"typeset|diff|query|font|image"), re.I)
    rows = []
    for f in d:
        url = ((f.get("urls") or {}).get("stable") or {}).get("url") or f.get("homepage") or ""
        m = re.search(r"github\.com/([^/]+/[^/#?]+)", url)
        if m and rx.search(f.get("desc") or ""):
            repo = m.group(1).removesuffix(".git")
            rows.append(_row(cls, "oracle-cli", f"{f['name']} ({repo})", f"https://github.com/{repo}",
                             version=(f.get("versions") or {}).get("stable", ""), licence=f.get("license") or "",
                             notes=(f.get("desc") or "")[:200]))
    return rows[: spec.get("n", 400)]


def ossfuzz(spec, cls):
    tmp = tempfile.mkdtemp(prefix="cgpipe-ossfuzz-")
    rows = []
    try:
        run = lambda cmd, t: subprocess.run(cmd, capture_output=True, timeout=t, start_new_session=True).returncode == 0
        ok = run(["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--no-checkout",
                  "https://github.com/google/oss-fuzz", tmp], 300)
        ok = ok and run(["git", "-C", tmp, "sparse-checkout", "set", "--no-cone", "/projects/*/project.yaml"], 120)
        ok = ok and run(["git", "-C", tmp, "checkout", "-q"], 300)
        if not ok:
            raise ApiError("oss-fuzz sparse clone failed")
        langs = set(spec.get("languages", ["c", "c++", "rust", "go"]))
        for proj in sorted(os.listdir(os.path.join(tmp, "projects")) if ok else []):
            try:
                y = open(os.path.join(tmp, "projects", proj, "project.yaml")).read()
            except OSError:
                continue
            lang = (re.search(r"^language:\s*\"?([\w+]+)", y, re.M) or [None, ""])[1]
            repo = (re.search(r"^main_repo:\s*['\"]?(https://github\.com/[^\s'\"]+)", y, re.M) or [None, ""])[1]
            if lang in langs and repo:     # contact emails in project.yaml are never read
                rows.append(_row(cls, "oss-fuzz", f"oss-fuzz {proj}", repo.removesuffix(".git"),
                                 notes=f"OSS-Fuzz project, language {lang}"))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ApiError(f"oss-fuzz: {type(e).__name__}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rows[: spec.get("n", 400)]


SMITH_RAW = "https://raw.githubusercontent.com/SWE-bench/SWE-smith/main/swesmith/profiles/{}.py"


def swesmith(spec, cls):
    """SWE-smith's per-repo environment profiles (MIT): repos whose test suites are known to run in a container.
    The profile files are parsed with `ast` and never imported or run. Each row carries the profile's test command
    in its notes, and `_apt`: the apt packages its Dockerfile installs (a hint for the probe)."""
    rows, seen = [], set()
    for lang in spec.get("langs", ["c", "cpp", "golang", "javascript", "python", "rust", "typescript"]):
        for c in ast.parse(_http_text(SMITH_RAW.format(lang))).body:
            if not isinstance(c, ast.ClassDef):
                continue
            f, apt = {}, []
            for s in c.body:
                if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name) and isinstance(s.value, ast.Constant):
                    f[s.target.id] = s.value.value
                elif isinstance(s, ast.FunctionDef) and s.name == "dockerfile":
                    text = " ".join(n.value for n in ast.walk(s) if isinstance(n, ast.Constant) and isinstance(n.value, str))
                    for m in re.finditer(r"apt-get install([^&;|\n]*)", text.replace("\\\n", " ")):
                        apt += [p for p in m.group(1).split() if re.fullmatch(r"[a-z0-9][a-z0-9+.-]{1,60}", p)]
            owner, repo = f.get("owner"), f.get("repo")
            if not (isinstance(owner, str) and isinstance(repo, str)) or (owner.lower(), repo.lower()) in seen:
                continue
            seen.add((owner.lower(), repo.lower()))
            tc = f.get("test_cmd") if isinstance(f.get("test_cmd"), str) else "the language default"
            rows.append(_row(cls, "known-green-repo", f"{owner}/{repo}", f"https://github.com/{owner}/{repo}",
                             notes=f"SWE-smith profile ({lang}): its suite runs in a container; test command: "
                                   f"{' '.join(tc.split())[:120]}. The repo is used by a SWE-bench-family dataset.",
                             _apt=sorted(set(apt))[:40]))
    return rows[: spec.get("n", 600)]


HARVESTERS = {"gh_repo_search": gh_repo_search, "gh_issue_search": gh_issue_search, "gh_pr_search": gh_pr_search,
              "crates_search": crates_search, "npm_search": npm_search, "homebrew": homebrew, "ossfuzz": ossfuzz,
              "swesmith": swesmith}


def harvest_channel(ch):
    """Run every harvester spec of one channel. Returns {"rows", "errors"}; raises when every spec failed, so an
    outage is retried as an error instead of being recorded as an empty channel."""
    rows, errors, specs = [], [], [x for x in ch.get("harvest", []) if x.get("kind") in HARVESTERS]
    for spec in specs:
        try:
            rows += HARVESTERS[spec["kind"]](spec, ch["class"])
        except Exception as e:  # noqa: BLE001 (one broken query must not stop the others)
            errors.append(f"{spec['kind']}: {type(e).__name__}: {str(e)[:120]}")
    if specs and len(errors) == len(specs):
        raise ApiError("every harvester failed: " + "; ".join(errors)[:300])
    hints = {}
    for r in rows:
        apt, g = r.pop("_apt", None), gh_repo_of(r["url"])
        if apt and g:
            hints["/".join(g).lower()] = {"apt": apt}
    return {"rows": rows, "errors": errors, "hints": hints}


# ---------------------------------------------------------------- enricher
ENRICH_FIELDS = """nameWithOwner stargazerCount isArchived isFork pushedAt diskUsage licenseInfo{spdxId}
  primaryLanguage{name} defaultBranchRef{name target{oid}} latestRelease{tagName publishedAt}
  openPRs: pullRequests(states:OPEN){totalCount}"""


def gh_repo_of(url):
    m = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url or "")
    return (m.group(1), m.group(2).removesuffix(".git")) if m else None


def enrich(repos, tree_for=None):
    """repos: list of (owner, name). Returns {"owner/name": facts}: real facts, or {"not_found": True} when GitHub
    answered that the repo doesn't exist (renamed, deleted, private). Repos in a chunk whose call failed are left out
    (unknown, retried later); raises when every chunk failed. One GraphQL point per 10 repos, plus one REST tree call
    per repo in `tree_for` (the test-suite size is the expensive fact, so only rows that need it pay for it)."""
    out, failed = {}, 0
    chunks = [repos[i:i + 10] for i in range(0, len(repos), 10)]
    for chunk in chunks:
        body = " ".join(f'r{j}: repository(owner:"{o}", name:"{n}"){{ {ENRICH_FIELDS} }}' for j, (o, n) in enumerate(chunk))
        try:
            d = _gh(["graphql", "-f", f"query=query{{ {body} }}"])
        except ApiError:
            failed += 1
            continue
        data = d.get("data") or {}
        for j, (o, n) in enumerate(chunk):
            r = data.get(f"r{j}")
            if f"r{j}" in data and r is None:
                out[f"{o}/{n}".lower()] = {"not_found": True}
                continue
            if not r:
                continue
            out[f"{o}/{n}".lower()] = {
                "stars": r["stargazerCount"], "spdx": (r.get("licenseInfo") or {}).get("spdxId") or "",
                "archived": r["isArchived"], "fork": r["isFork"], "pushed": (r.get("pushedAt") or "")[:10],
                "kb": r.get("diskUsage") or 0, "lang": (r.get("primaryLanguage") or {}).get("name") or "",
                "release": (r.get("latestRelease") or {}).get("tagName") or "",
                "head": ((r.get("defaultBranchRef") or {}).get("target") or {}).get("oid") or "",
                "open_prs": r["openPRs"]["totalCount"]}
    for key in (tree_for or []):
        f = out.get(key.lower())
        if not f or not f.get("head"):
            continue
        try:
            t = _gh([f"repos/{key}/git/trees/{f['head']}?recursive=1"], timeout=120)
        except ApiError:
            continue
        blobs = [x for x in t.get("tree", []) if x.get("type") == "blob" and TEST_DIR_RX.search(x.get("path", ""))]
        f["test_files"], f["test_kb"] = len(blobs), round(sum(x.get("size", 0) for x in blobs) / 1024)
        f["tree_truncated"] = bool(t.get("truncated"))
    if chunks and failed == len(chunks):
        raise ApiError("every enrich call failed")
    return out


PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "Unlicense", "Zlib", "0BSD", "BSL-1.0",
              "MPL-2.0", "CC0-1.0", "Python-2.0", "PSF-2.0", "BlueOak-1.0.0", "X11", "Unicode-3.0"}


def priority(f, cls):
    """A rough, explainable 0-100 ordering of rows for the writer. Facts only; no model judgement."""
    if not f:
        return 30.0                                   # unknown: middle of the pack, V1 finds out
    if f.get("not_found") or f.get("archived") or f.get("fork"):
        return 0.0
    p = 20 * min(1.0, math.log10(max(f.get("stars", 0), 1)) / 4)            # 10k stars = full marks
    p += 20 if f.get("spdx") in PERMISSIVE else (8 if f.get("spdx") in ("", "NOASSERTION", "OTHER") else 0)
    pushed = f.get("pushed") or "1970"
    p += 20 if pushed >= "2025" else (10 if pushed >= "2023" else 0)
    if "test_kb" in f:                                  # the grading surface, when measured
        p += 40 * min(1.0, math.log10(max(f["test_kb"], 1)) / 4)             # 10 MB of tests = full marks
    else:
        p += 15
    return round(p, 1)


# ---------------------------------------------------------------- smoke + test probe (no tokens; Docker)
# Two throwaway containers share a named work volume mounted at /p: "fetch" (network on) clones the source and
# downloads dependencies; "build" (--network none) builds offline and runs the project's suite three times with a
# structured report. The script goes in and the reports come out with `docker cp` (no bind mounts), so the same
# calls work against a remote Docker host. A probe right before a spike keeps the volume for it (keep=True).
