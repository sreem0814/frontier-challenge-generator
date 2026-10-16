#!/usr/bin/env bash
# smoke+test prototype: runs INSIDE a throwaway container. Zero tokens.
# usage: smoke_test.sh <git-url> <ref|""> <phase: fetch|build|all> [runs=3]
# Writes /out/<files> and prints "CG <key> <value>" lines. Never uses `set -e` (exit-code markers must always print).
set -u
URL="$1"; REF="${2:-}"; PHASE="${3:-all}"; RUNS="${4:-3}"
OUT=/out; mkdir -p "$OUT"; W=/work/src
NPROC=$(nproc); J=$(( NPROC < 8 ? NPROC : 8 ))
CAP_CLONE=${CAP_CLONE:-300}; CAP_FETCH=${CAP_FETCH:-900}; CAP_BUILD=${CAP_BUILD:-1500}; CAP_TEST=${CAP_TEST:-900}
export CARGO_TERM_COLOR=never NO_COLOR=1 FORCE_COLOR=0 CI=true GIT_TERMINAL_PROMPT=0 PIP_DISABLE_PIP_VERSION_CHECK=1
export GOFLAGS="${GOFLAGS:-} -buildvcs=false" CMAKE_BUILD_PARALLEL_LEVEL=$J CTEST_PARALLEL_LEVEL=$J
now() { date +%s; }
say() { echo "CG $*"; }
# step <name> <cap-seconds> <command>: runs with a cap, logs to /out/<name>.log, prints rc and seconds
step() { local n=$1 cap=$2; shift 2; local t=$(now)
  timeout -k 10 "$cap" bash -c "$*" >"$OUT/$n.log" 2>&1; local rc=$?
  say "step $n rc=$rc s=$(( $(now) - t ))"; [ $rc -eq 124 ] && say "timeout $n"; return $rc; }

# ---------------------------------------------------------------- clone (fetch phase)
if [ "$PHASE" != build ]; then
  t=$(now)
  if [ -n "$REF" ] && timeout "$CAP_CLONE" git clone -q --depth 1 --recurse-submodules --shallow-submodules --branch "$REF" "$URL" $W 2>"$OUT/clone.log"; then say "clone ok ref=$REF"
  elif timeout "$CAP_CLONE" git clone -q --depth 1 --recurse-submodules --shallow-submodules "$URL" $W 2>>"$OUT/clone.log"; then say "clone ok ref=default"
  else say "clone fail"; exit 0; fi
  say "clone_s $(( $(now) - t ))"
fi
cd $W || { say "clone fail"; exit 0; }
say "commit $(git rev-parse HEAD)"

# ---------------------------------------------------------------- detect (convention; CI override via TEST_CMD/BUILD_CMD env)
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

# per-ecosystem recipes: FETCH (network), BUILD (offline), LIST (count), TEST (offline, structured report into $OUT/run$i.*)
case $ECO in
rust)
  FETCH="cargo fetch --locked || cargo fetch"
  BUILD="cargo test --offline --no-run --all-targets --locked 2>&1 || cargo test --offline --no-run --all-targets"
  LIST="cargo test --offline -q -- --list 2>/dev/null | grep -cE ': (test|bench)$'"
  if command -v cargo-nextest >/dev/null; then
    TEST='cargo nextest run --offline --no-fail-fast --profile cgsmoke'      # JUnit via .config/nextest.toml written below
  else
    TEST='cargo test --offline --no-fail-fast 2>&1'                     # parse "test X ... ok|FAILED|ignored"
  fi ;;
go)
  FETCH="go mod download all"
  BUILD="GOPROXY=off GOFLAGS=-mod=mod go test -count=1 -run '^\$' ./... >/dev/null"   # compiles every test binary
  LIST="GOPROXY=off go test -list '.*' ./... 2>/dev/null | grep -cE '^(Test|Example|Fuzz)'"
  TEST="GOPROXY=off GOFLAGS=-mod=mod go test -count=1 -json -p $J ./..." ;;
python)
  FETCH='python3 -m venv /work/venv && . /work/venv/bin/activate && pip install -q -U pip &&
         ex=$(python3 - <<"EOF"
import tomllib,configparser,os
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
         for r in requirements-test.txt requirements-dev.txt requirements_test.txt requirements/test.txt test-requirements.txt tests/requirements.txt; do [ -f $r ] && pip install -q -r $r; done;
         pip install -q pytest;
         for r in $(find . -maxdepth 3 -iname "*requirements*.txt" | grep -iE "test|dev|ci" ); do pip install -q -r $r; done;
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
  BUILD='. /work/venv/bin/activate && python -c "import sys; print(sys.version)"'
  LIST='. /work/venv/bin/activate && pytest -p no:cacheprovider --collect-only -q 2>/dev/null | grep -c "::"'
  TEST='. /work/venv/bin/activate && pytest -p no:cacheprovider -q -o junit_family=xunit2 --junitxml=$OUT/run$i.xml' ;;
node)
  if has pnpm-lock.yaml; then PM="corepack pnpm"; INST="corepack pnpm install --frozen-lockfile"
  elif has yarn.lock; then PM="corepack yarn"; INST="corepack yarn install --frozen-lockfile || corepack yarn install --immutable"
  elif has package-lock.json; then PM=npm; INST="npm ci --no-audit --no-fund"
  else PM=npm; INST="npm install --no-audit --no-fund"; fi
  FETCH="export COREPACK_ENABLE_DOWNLOAD_PROMPT=0; $INST"
  BUILD="node -e 'process.exit(require(\"./package.json\").scripts?.build?0:3)' && $PM run build; r=\$?; [ \$r -eq 3 ] && r=0; exit \$r"
  RUNNER=$(node -e 'const p=require("./package.json");const d={...p.dependencies,...p.devDependencies};const t=(p.scripts||{}).test||"";
    console.log(/\bvitest\b/.test(t)||d.vitest&&!/jest/.test(t)?"vitest":/\bjest\b/.test(t)||d.jest?"jest":/\bmocha\b/.test(t)?"mocha":/node --test/.test(t)?"node":t?"script":"none")')
  say "runner $RUNNER"
  case $RUNNER in
    vitest) LIST="npx vitest list 2>/dev/null | wc -l"; TEST='npx vitest run --reporter=json --outputFile=$OUT/run$i.json' ;;
    jest)   LIST="npx jest --listTests 2>/dev/null | wc -l"; TEST='npx jest --ci --json --outputFile=$OUT/run$i.json' ;;
    mocha)  LIST="echo 0"; TEST='npx mocha --reporter json > $OUT/run$i.json' ;;
    node)   LIST="echo 0"; TEST="$PM test" ;;
    script) LIST="echo 0"; TEST="$PM test" ;;
    *)      LIST="echo 0"; TEST="false" ;;
  esac ;;
cmake)
  OPTS=$(grep -ohE 'option *\( *[A-Za-z0-9_]*(TEST|TESTS|TESTING)[A-Za-z0-9_]*' CMakeLists.txt | sed -E 's/option *\( *//' | sort -u | sed 's/^/-D/; s/$/=ON/' | tr '\n' ' ')
  say "cmake_opts $OPTS"
  FETCH="true"   # FetchContent / submodules: configure needs network, so configure in the fetch phase
  FETCH="cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON $OPTS -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache"
  BUILD="cmake --build build -j $J"
  LIST="ctest --test-dir build -N | sed -nE 's/^Total Tests: ([0-9]+)/\\1/p'"
  TEST='ctest --test-dir build --no-tests=error -j '$J' --timeout 300 --output-junit $OUT/run$i.xml' ;;
meson)
  FETCH="meson setup build -Dbuildtype=release --wrap-mode=default"
  BUILD="meson compile -C build"
  LIST="meson test -C build --list 2>/dev/null | wc -l"
  TEST='meson test -C build --num-processes '$J'; cp build/meson-logs/testlog.json $OUT/run$i.jsonl' ;;
autotools)
  FETCH="[ -f configure ] || autoreconf -fi"
  BUILD="./configure && make -j$J"
  LIST="echo 0"
  TEST="make -j$J check; find . -name test-suite.log -newer config.status -exec cat {} + > \$OUT/run\$i.automake" ;;
make)
  FETCH="true"; BUILD="make -j$J"; LIST="echo 0"
  T=$(grep -oE '^(check|test|tests):' Makefile GNUmakefile makefile 2>/dev/null | head -1 | cut -d: -f2)
  TEST="make ${T:-test}" ;;
*) FETCH=true; BUILD=false; LIST="echo 0"; TEST=false ;;
esac
[ -n "${BUILD_CMD:-}" ] && BUILD="$BUILD_CMD"
[ -n "${TEST_CMD:-}" ] && TEST="$TEST_CMD"
printf '%s\n' "$FETCH" > $OUT/cmd.fetch; printf '%s\n' "$BUILD" > $OUT/cmd.build; printf '%s\n' "$TEST" > $OUT/cmd.test

if [ "$PHASE" != build ]; then step fetch "$CAP_FETCH" "$FETCH"; fi
[ "$PHASE" = fetch ] && exit 0

if [ $ECO = rust ] && command -v cargo-nextest >/dev/null; then
  mkdir -p .config; printf '[profile.cgsmoke]\nfail-fast = false\n[profile.cgsmoke.junit]\npath = "junit.xml"\n' >> .config/nextest.toml
fi
step build "$CAP_BUILD" "$BUILD" && say "build ok" || say "build fail"
tail -n 15 $OUT/build.log | sed 's/^/LOG /'
say "tests_listed $(timeout 300 bash -c "$LIST" 2>/dev/null | tail -1)"
for i in $(seq 1 "$RUNS"); do
  pre=""; [ "$i" = 3 ] && [ "$RUNS" -ge 3 ] && pre="taskset -c 0"     # run 3 on one core: exposes timing flakes
  export i OUT
  step "run$i" "$CAP_TEST" "$pre bash $OUT/cmd.test"; say "run$i rc=$?"
  [ $ECO = rust ] && [ -f target/nextest/cgsmoke/junit.xml ] && cp target/nextest/cgsmoke/junit.xml $OUT/run$i.xml
  [ $ECO = go ] && cp $OUT/run$i.log $OUT/run$i.jsonl
done
say "done"
