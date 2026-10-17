#!/usr/bin/env bash
# probe.sh: the smoke stage's in-container script (zero tokens). Clones a seed's source, fetches its dependencies,
# then builds it offline and runs its own test suite three times with a structured report per run.
# usage (inside cgpipe-spike:1, work volume at /p, results in /out):
#   probe.sh <git-url> <ref|""> fetch          network on: clone, toolchain, dependencies
#   probe.sh <git-url> <ref|""> build [runs]   --network none: build, list, run the suite (run 3 pinned to one core)
# Prints "CG <key> <value>" lines; harvest.probe() parses them and the reports in /out. Never `set -e`: every step
# must print its exit code. Tested on 32 repos.
set -u
URL="$1"; REF="${2:-}"; PHASE="${3:-build}"; RUNS="${4:-3}"
OUT=/out; mkdir -p "$OUT"; W=/p/src
NPROC=${PROBE_CPUS:-$(nproc)}; J=$(( NPROC < 8 ? NPROC : 8 ))   # nproc sees the host, not the --cpus limit
CAP_CLONE=${CAP_CLONE:-300}; CAP_FETCH=${CAP_FETCH:-900}; CAP_BUILD=${CAP_BUILD:-1500}; CAP_TEST=${CAP_TEST:-900}
# NO_COLOR / FORCE_COLOR are deliberately not set: they changed test outcomes in the prototype (black).
export CI=true CARGO_TERM_COLOR=never GIT_TERMINAL_PROMPT=0 PIP_DISABLE_PIP_VERSION_CHECK=1 RUSTUP_TOOLCHAIN=stable \
       COREPACK_ENABLE_DOWNLOAD_PROMPT=0 CMAKE_BUILD_PARALLEL_LEVEL=$J CTEST_PARALLEL_LEVEL=$J MESON_TESTTHREADS=$J
export GOFLAGS="${GOFLAGS:-} -buildvcs=false"
now() { date +%s; }
say() { echo "CG $*"; }
# step <name> <cap-seconds> <command>: runs under a cap, logs to /out/<name>.log, prints rc and seconds
step() { local n=$1 cap=$2; shift 2; local t; t=$(now)
  timeout -k 10 "$cap" bash -c "$*" >"$OUT/$n.log" 2>&1; local rc=$?
  say "step $n rc=$rc s=$(( $(now) - t ))"; [ $rc -eq 124 ] && say "timeout $n"; return $rc; }

# ---------------------------------------------------------------- system packages named by a recipe hint (HINT_APT)
# The fetch phase installs them and keeps the .deb files in the work volume; the offline build phase installs those.
if [ -n "${HINT_APT:-}" ]; then
  mkdir -p /p/apt/partial
  if [ "$PHASE" = fetch ]; then
    apt-get update -qq > "$OUT/apt.log" 2>&1
    known=$(for p in $HINT_APT; do apt-cache show "$p" >/dev/null 2>&1 && echo "$p"; done)  # Ubuntu names may not exist here
    [ -n "$known" ] && apt-get install -y -q --no-install-recommends -o Dir::Cache::archives=/p/apt $known \
      >> "$OUT/apt.log" 2>&1; say "apt rc=$? installed $(echo $known | wc -w) of $(echo $HINT_APT | wc -w)"
  else
    ls /p/apt/*.deb >/dev/null 2>&1 && dpkg -i /p/apt/*.deb > "$OUT/apt.log" 2>&1; say "apt offline rc=$?"
  fi
fi

# ---------------------------------------------------------------- clone (fetch phase): tag, v<tag>, default branch
if [ "$PHASE" = fetch ]; then
  t=$(now); rm -rf "$W"
  clone() { timeout "$CAP_CLONE" git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=60 clone -q --depth 1 \
              --recurse-submodules --shallow-submodules "$@" "$URL" "$W" 2>>"$OUT/clone.log"; }   # a stalled link fails fast
  if   [ -n "$REF" ] && clone --branch "$REF"; then say "clone ok ref=$REF"
  elif [ -n "$REF" ] && { rm -rf "$W"; clone --branch "v$REF"; }; then say "clone ok ref=v$REF"
  elif rm -rf "$W" && clone; then say "clone ok ref=default"
  elif timeout 60 git ls-remote "$URL" >/dev/null 2>&1; then say "clone error"; exit 0     # reachable: retry later
  else say "clone fail"; exit 0; fi
  say "clone_s $(( $(now) - t ))"
  cd "$W" || exit 0
  say "test_files $(git ls-files | grep -cE '(^|/)(tests?|testdata|test-?suite|fixtures?|spec|conformance|test-?vectors|corpus|testcases?)(/|$)')"
  say "ci_files $(ls .github/workflows 2>/dev/null | wc -l)"
  # no build manifest at the root: use the one subfolder (depth 2) that has one, if exactly one does
  : > /p/subdir
  root=0
  for m in Cargo.toml go.mod meson.build CMakeLists.txt configure.ac configure package.json pyproject.toml setup.py \
           setup.cfg Makefile GNUmakefile makefile; do [ -e "$m" ] && root=1; done
  if [ $root = 0 ]; then
    d=$(find . -mindepth 2 -maxdepth 2 \( -name Cargo.toml -o -name go.mod -o -name meson.build -o -name CMakeLists.txt \
         -o -name configure.ac -o -name package.json -o -name pyproject.toml -o -name setup.py -o -name Makefile \) \
         -not -path './.*' -printf '%h\n' | sort -u)
    [ "$(printf '%s\n' "$d" | grep -c .)" = 1 ] && printf '%s\n' "${d#./}" > /p/subdir
  fi
fi
cd "$W" 2>/dev/null || { say "clone fail"; exit 0; }
say "commit $(git rev-parse HEAD 2>/dev/null)"
SUB=$(cat /p/subdir 2>/dev/null); [ -n "$SUB" ] && { cd "$SUB" || exit 0; say "subdir $SUB"; }

# ---------------------------------------------------------------- detect (root markers, most specific first)
has() { [ -e "$1" ]; }
ECO=unknown
if   has Cargo.toml; then ECO=rust
elif has go.mod; then ECO=go
elif has meson.build; then ECO=meson
elif has CMakeLists.txt; then ECO=cmake
elif has configure.ac || has configure; then ECO=autotools
elif has package.json; then ECO=node
elif has pyproject.toml || has setup.py || has setup.cfg; then ECO=python
elif has Makefile || has GNUmakefile || has makefile; then ECO=make
fi
say "eco $ECO"

# ---------------------------------------------------------------- recipes: FETCH (network), BUILD and TEST (offline)
# TEST writes a structured report to $OUT/run$i.<xml|json|jsonl|automake>; $i and $OUT expand at run time.
case $ECO in
rust)
  FETCH="cargo fetch --locked || cargo fetch"
  BUILD="cargo test --offline --no-run --all-targets --locked || cargo test --offline --no-run --all-targets"
  LIST="cargo test --offline -q -- --list 2>/dev/null | grep -cE ': (test|bench)\$'"
  if command -v cargo-nextest >/dev/null; then TEST='cargo nextest run --offline --no-fail-fast --profile cgprobe'
  else TEST='cargo test --offline --no-fail-fast'; fi ;;          # libtest text, parsed from run$i.log
go)
  FETCH="go mod download all"
  BUILD="GOPROXY=off GOFLAGS=-mod=mod go test -count=1 -run '^\$' ./... >/dev/null"   # compiles every test binary
  LIST="GOPROXY=off go test -list '.*' ./... 2>/dev/null | grep -cE '^(Test|Example|Fuzz)'"
  TEST="GOPROXY=off GOFLAGS=-mod=mod go test -count=1 -json -p $J ./..." ;;
python)
  FETCH='python3 -m venv /p/venv && . /p/venv/bin/activate && pip install -q -U pip &&
         ex=$(python3 - <<"EOF"
import tomllib
x=[]
try:
  d=tomllib.load(open("pyproject.toml","rb")); x=list(((d.get("project") or {}).get("optional-dependencies") or {}).keys())
except Exception: pass
print(",".join(e for e in x if not any(b in e.lower() for b in ("doc","gpu","cuda","win","mac"))))
EOF
);
         grp=$(python3 - <<"EOF2"
import tomllib
try: g=(tomllib.load(open("pyproject.toml","rb")).get("dependency-groups") or {}).keys()
except Exception: g=[]
print(" ".join("--group "+x for x in g if x.lower() in ("test","tests","testing","dev")))
EOF2
);
         pip install -q -e ".${ex:+[$ex]}" $grp || pip install -q ".${ex:+[$ex]}" $grp;
         pip install -q pytest;
         for r in $(find . -maxdepth 3 -iname "*requirements*.txt" | grep -iE "test|dev|ci"); do pip install -q -r $r; done;
         python3 - > /tmp/toxdeps.txt <<"EOF3"
import configparser
c=configparser.ConfigParser(interpolation=None)
try:
  c.read("tox.ini")
  for l in c.get("testenv","deps",fallback="").splitlines():
    l=l.strip()
    if l and not l.startswith("-") and "{" not in l: print(l.split(":")[-1].strip())
except Exception: pass
EOF3
         [ -s /tmp/toxdeps.txt ] && pip install -q -r /tmp/toxdeps.txt;
         for k in 1 2 3 4 5; do
           m=$(pytest -p no:cacheprovider --collect-only -q 2>&1 | grep -oE "No module named .[A-Za-z0-9_]+" | head -1 | grep -oE "[A-Za-z0-9_]+$");
           [ -z "$m" ] && break; echo "REPAIR pip install $m"; pip install -q "$(echo $m | tr _ -)" || break;
         done'
  BUILD='. /p/venv/bin/activate && python -c "import sys; print(sys.version)"'
  LIST='. /p/venv/bin/activate && pytest -p no:cacheprovider --collect-only -q 2>/dev/null | grep -c "::"'
  TEST='. /p/venv/bin/activate && pytest -p no:cacheprovider -q -o junit_family=xunit2 --junitxml=$OUT/run$i.xml' ;;
node)
  if has pnpm-lock.yaml; then PM="corepack pnpm"; INST="corepack pnpm install --frozen-lockfile"
  elif has yarn.lock; then PM="corepack yarn"; INST="corepack yarn install --frozen-lockfile || corepack yarn install --immutable"
  elif has package-lock.json; then PM=npm; INST="npm ci --no-audit --no-fund"
  else PM=npm; INST="npm install --no-audit --no-fund"; fi
  FETCH="$INST"
  BUILD="node -e 'process.exit(require(\"./package.json\").scripts?.build?0:3)' && $PM run build; r=\$?; [ \$r -eq 3 ] && r=0; exit \$r"
  RUNNER=$(node -e 'const p=require("./package.json");const d={...p.dependencies,...p.devDependencies};const t=(p.scripts||{}).test||"";
    console.log(/\bvitest\b/.test(t)||d.vitest&&!/jest/.test(t)?"vitest":/\bjest\b/.test(t)||d.jest?"jest":/\bmocha\b/.test(t)?"mocha":t?"script":"none")' 2>/dev/null)
  say "runner $RUNNER"
  case $RUNNER in
    vitest) LIST="npx vitest list 2>/dev/null | wc -l"; TEST='npx vitest run --reporter=json --outputFile=$OUT/run$i.json' ;;
    jest)   LIST="npx jest --listTests 2>/dev/null | wc -l"; TEST='npx jest --ci --json --outputFile=$OUT/run$i.json' ;;
    mocha)  LIST="echo 0"; TEST='npx mocha --reporter json > $OUT/run$i.json' ;;
    script) LIST="echo 0"; TEST="$PM test" ;;
    *)      LIST="echo 0"; TEST="false" ;;
  esac ;;
cmake)
  OPTS=$(grep -ohE 'option *\( *[A-Za-z0-9_]*(TEST|TESTS|TESTING)[A-Za-z0-9_]*' CMakeLists.txt | sed -E 's/option *\( *//' | sort -u | sed 's/^/-D/; s/$/=ON/' | tr '\n' ' ')
  # configure needs the network (FetchContent, submodule downloads), so it runs in the fetch phase
  FETCH="cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON $OPTS -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
  BUILD="cmake --build build -j $J"
  LIST="ctest --test-dir build -N | sed -nE 's/^Total Tests: ([0-9]+)/\\1/p'"
  TEST='ctest --test-dir build --no-tests=error -j '$J' --timeout 300 --output-junit $OUT/run$i.xml' ;;
meson)
  # Debian's meson is too old for many projects: a current one goes into the work volume, so the offline phase has it
  FETCH="python3 -m venv /p/tools && /p/tools/bin/pip install -q meson && /p/tools/bin/meson setup build -Dbuildtype=release --wrap-mode=default"
  BUILD="/p/tools/bin/meson compile -C build"
  LIST="/p/tools/bin/meson test -C build --list 2>/dev/null | wc -l"
  TEST='/p/tools/bin/meson test -C build --num-processes '$J'; r=$?; cp build/meson-logs/testlog.json $OUT/run$i.jsonl; exit $r' ;;
autotools)
  FETCH="[ -f configure ] || autoreconf -fi"
  BUILD="./configure && make -j$J"
  LIST="echo 0"
  TEST='make -j'$J' check; r=$?; find . -name test-suite.log -newer config.status -exec cat {} + > $OUT/run$i.automake; exit $r' ;;
make)
  FETCH="true"; BUILD="make -j$J"; LIST="echo 0"
  T=$(grep -oE '^(check|test|tests):' Makefile GNUmakefile makefile 2>/dev/null | head -1 | cut -d: -f2)
  TEST="make ${T:-test}" ;;
*) FETCH=true; BUILD=false; LIST="echo 0"; TEST=false ;;
esac
printf '%s\n' "$FETCH" > $OUT/cmd.fetch; printf '%s\n' "$BUILD" > $OUT/cmd.build; printf '%s\n' "$TEST" > $OUT/cmd.test

if [ "$PHASE" = fetch ]; then step fetch "$CAP_FETCH" "$FETCH"; tail -n 8 $OUT/fetch.log | sed 's/^/LOG /'; exit 0; fi

# ---------------------------------------------------------------- build + test (offline)
if [ $ECO = rust ] && command -v cargo-nextest >/dev/null; then
  mkdir -p .config; printf '\n[profile.cgprobe]\nfail-fast = false\n[profile.cgprobe.junit]\npath = "junit.xml"\n' >> .config/nextest.toml
fi
step build "$CAP_BUILD" "$BUILD" && say "build ok" || say "build fail"
tail -n 12 $OUT/build.log | sed 's/^/LOG /'
say "tests_listed $(timeout 300 bash -c "$LIST" 2>/dev/null | tail -1)"
for i in $(seq 1 "$RUNS"); do
  pre=""; [ "$i" = 3 ] && pre="taskset -c 0"          # run 3 on one core: exposes timing flakes
  export i OUT
  step "run$i" "$CAP_TEST" "$pre bash $OUT/cmd.test"; say "run$i rc=$?"
  [ $ECO = rust ] && [ -f target/nextest/cgprobe/junit.xml ] && cp target/nextest/cgprobe/junit.xml $OUT/run$i.xml
  [ $ECO = go ] && cp $OUT/run$i.log $OUT/run$i.jsonl
done
say "done"
