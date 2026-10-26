"""Parse smoke+test outputs into per-test status maps and a determinism verdict. Host side; data only.
usage: python3 -I parse_results.py <outdir>   -> prints one JSON object"""
import glob, json, os, re, sys
import xml.etree.ElementTree as ET

LIBTEST = re.compile(r"^test (.+?) \.\.\. (ok|FAILED|ignored)(?:, .*)?$", re.M)
RUNNING = re.compile(r"^\s+Running (?:unittests )?(\S+)", re.M)
CTEST_SUM = re.compile(r"(\d+)% tests passed, (\d+) tests failed out of (\d+)")
PYTEST_SUM = re.compile(r"=+ (.*?) in [\d.]+s")
AUTOMAKE = re.compile(r"^# (TOTAL|PASS|SKIP|XFAIL|FAIL|XPASS|ERROR):\s+(\d+)", re.M)


def junit(path):
    res = {}
    try:
        root = ET.parse(path).getroot()
    except Exception:  # noqa: BLE001
        return None
    for tc in root.iter("testcase"):
        name = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        tags = {c.tag for c in tc}
        st = "fail" if tags & {"failure", "error"} else "skip" if "skipped" in tags else "pass"
        res[name] = st
    return res


def gojson(path):
    res = {}
    for line in open(path, errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("Test") and e.get("Action") in ("pass", "fail", "skip"):
            res[f"{e['Package']}::{e['Test']}"] = e["Action"]
        elif not e.get("Test") and e.get("Action") == "fail":       # package-level failure (build error, panic in init)
            res[f"{e.get('Package')}::<package>"] = "fail"
    return res


def jestjson(path):
    try:
        d = json.load(open(path))
    except Exception:  # noqa: BLE001
        return None
    res = {}
    if "stats" in d and "tests" in d:                                  # mocha --reporter json
        st = {id(t): "pass" for t in d.get("passes", [])}
        st.update({id(t): "fail" for t in d.get("failures", [])})
        names = {}
        for k, v in (("passes", "pass"), ("failures", "fail"), ("pending", "skip")):
            for t in d.get(k, []):
                names[f"{os.path.basename(t.get('file') or '')}::{t.get('fullTitle')}"] = v
        return names
    for f in d.get("testResults", []):
        fn = os.path.basename(f.get("name", ""))
        for a in f.get("assertionResults", []):
            st = {"passed": "pass", "failed": "fail"}.get(a.get("status"), "skip")
            res[f"{fn}::{a.get('fullName') or a.get('title')}"] = st
        if f.get("status") == "failed" and not f.get("assertionResults"):
            res[f"{fn}::<file>"] = "fail"                             # suite failed to load
    return res


def mesonjsonl(path):
    res = {}
    for line in open(path, errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        r = e.get("result", "")
        res[e.get("name", "?")] = "pass" if r in ("OK", "EXPECTEDFAIL") else "skip" if r == "SKIP" else "fail"
    return res


def libtest(path):
    txt = open(path, errors="replace").read()
    res, binary = {}, ""
    pos = 0
    for m in re.finditer(r"^\s+(?:Running|Doc-tests) .*$|^test .+? \.\.\. (?:ok|FAILED|ignored).*$", txt, re.M):
        line = m.group(0)
        if not line.startswith("test "):
            binary = line.strip().split(" (")[0]
            continue
        mm = LIBTEST.match(line)
        if mm:
            res[f"{binary}::{mm.group(1)}"] = {"ok": "pass", "FAILED": "fail", "ignored": "skip"}[mm.group(2)]
    return res


def one_run(d, i):
    for ext, fn in ((".xml", junit), (".jsonl", None), (".json", jestjson), (".automake", None)):
        p = os.path.join(d, f"run{i}{ext}")
        if not os.path.exists(p):
            continue
        if ext == ".jsonl":
            head = open(p, errors="replace").readline()
            return (gojson(p) if '"Action"' in head else mesonjsonl(p)), "go-json" if '"Action"' in head else "meson-json"
        if ext == ".automake":
            c = dict((k, int(v)) for k, v in AUTOMAKE.findall(open(p, errors="replace").read()))
            return ({f"#{k}": v for k, v in c.items()} if c else None), "automake-summary"
        r = fn(p)
        if r is not None:
            return r, ext[1:]
    p = os.path.join(d, f"run{i}.log")
    if os.path.exists(p):
        r = libtest(p)
        if r:
            return r, "libtest-text"
    return None, "exit-code-only"


def main(d):
    log = open(os.path.join(d, "stdout.txt"), errors="replace").read() if os.path.exists(os.path.join(d, "stdout.txt")) else ""
    rcs = {int(a): int(b) for a, b in re.findall(r"^CG run(\d+) rc=(\d+)", log, re.M)}
    runs, fmt = [], None
    for i in sorted(rcs):
        r, f = one_run(d, i)
        fmt = f if r is not None else (fmt or f)
        runs.append(r)
    out = {"eco": (re.search(r"^CG eco (\S+)", log, re.M) or [0, ""])[1], "format": fmt, "rcs": [rcs[k] for k in sorted(rcs)],
           "build_ok": "CG build ok" in log,
           "tests_listed": (re.search(r"^CG tests_listed (\d+)", log, re.M) or [0, None])[1],
           "steps": {a: int(b) for a, b in re.findall(r"^CG step (\w+) rc=\d+ s=(\d+)", log, re.M)}}
    good = [r for r in runs if r is not None]
    out["runs_without_report"] = sum(r is None for r in runs)
    if good and len(good) < len(runs):
        runs = good                               # a run that crashed before writing its report is itself nondeterminism
    if runs and all(r is not None for r in runs) and fmt != "automake-summary":
        names = set().union(*[set(r) for r in runs])
        flaky = sorted(n for n in names if len({r.get(n, "missing") for r in runs}) > 1)
        first = runs[0]
        out.update(tests=len(first), passed=sum(v == "pass" for v in first.values()),
                   failed=sum(v == "fail" for v in first.values()), skipped=sum(v == "skip" for v in first.values()),
                   flaky=len(flaky), flaky_names=flaky[:20])
    elif runs and runs[0] is not None:
        out.update(summary=runs, flaky=int(len({json.dumps(r, sort_keys=True) for r in runs}) > 1))
    out["deterministic_rc"] = len(set(out["rcs"])) <= 1
    out["deterministic"] = out["deterministic_rc"] and not out.get("flaky") and not out["runs_without_report"]
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1])
