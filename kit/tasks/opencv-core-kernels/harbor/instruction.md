# OpenCV core kernels: win back the vector speed

`/app/opencv` is the core module of OpenCV (upstream commit `e70c9da`, the 5.x line after the 5.0.0 release) with every piece of vector code taken out. The universal-intrinsics headers (`opencv2/core/hal/intrin*.hpp` for every backend), the SIMD branches of the core sources, the per-ISA dispatch lists, IPP and the HAL plugins are gone; what is left is the scalar code, compiled for plain x86-64. It builds, it is correct, and on many kernels it is 3 to 50 times slower than an optimized OpenCV build on the same CPU.

Your job: make the kernels listed below fast again, on one core, without changing what they compute. The score compares your build against the shipped build and against an optimized build of the same upstream sources, measured on the same machine in the same run.

## Workspace

- `/app/opencv/` the source tree (a git repository with one commit). You change files under `/app/opencv/modules/core/src/` only. New `.cpp` files anywhere under that directory are compiled automatically (the module globs `src/` recursively).
- `/app/build/` a configured and built tree (Ninja) of `opencv_core` as a static library, using the fixed configuration.
- `/app/bench/` the measuring tools:
  - `build.sh` rebuilds `/app/build` and links `bin/cvbench` against it.
  - `cmake-args.txt` the fixed CMake configuration (Release, `-O3`, static, `BUILD_LIST=core`, `CV_DISABLE_OPTIMIZATION=ON`, empty `CPU_BASELINE` and `CPU_DISPATCH`, no IPP, TBB, OpenMP, OpenCL, LAPACK or parallel plugins).
  - `cvbench.cpp` the benchmark and check program: the timed cases (`makeCases()`), the randomized check suite (`runChecks()`), the timing server and the comparator. It is the same program the measurement uses.
  - `perf.py` the interleaved timing driver; `selfcheck.py` runs the whole procedure locally (see below).
  - `bin/cvbench-base` the benchmark linked against the untouched sources; it is the baseline and the reference for correctness.
  - `targets.json` the timed cases, their families, and the speedup `S_k` the optimized build reached on our test machine.

There is no network. Everything you need is installed: GCC 12.2, CMake 3.25, Ninja, Python 3.11, gdb.

## What to deliver

Faster implementations, inside `modules/core/src/`, of the functions behind the timed cases, with the public API and ABI unchanged (public headers are not yours to edit; they are taken from the shipped tree). The timed cases, by family (sizes and parameters are in `cvbench.cpp`, most are 640x480 or 1280x720 frames, a few odd sizes such as 637x479):

- arith: `add` 8u, 16s, 8uC3 `subtract`, `add` scalar 32fC3, masked `subtract` 16u
- muldiv: `multiply` 8u, 16s with scale; `divide` 8u, 16s with scale; reciprocal `divide(2.5, x)` 32f
- absminmax: `absdiff` 8u, 16s, 32f, with scalar 8uC3
- weighted: `addWeighted` 8u, 16s, 8uC3
- compare: `compare` 8u GT, 16s EQ, 32f LE; `inRange` 8uC3 and 32f; masked `bitwise_and` 8u
- convert: `convertTo` 32f to 8u, 16s to 8u, 8u to 16s scaled, 32f to 16s scaled, 64f to 32s, 32f to 16f, 16f to 32f, 8u to 8u scaled; `convertScaleAbs` 16s and 32f
- sum: `sum` 8u, 16sC3, 32f; `meanStdDev` 8uC3 and 32f
- norm: L2 8u, L1 32f, INF 16s, L2 32f, difference L2 8u, masked L1 8u, difference INF 32f
- minmax: `countNonZero` 8u and 32f, `minMaxLoc` 8u and 32f, masked `minMaxIdx` 16s
- channels: `split` 8uC3 and 32fC4, `merge` 8uC3 and 16uC4
- mathfn: `magnitude`, `phase`, `cartToPolar` (degrees), `polarToCart`, `exp`, `log`, `sqrt`, `pow(x, 2.5)` on 32f; `exp` on 64f
- matmul: `gemm` 32f 256x256, `gemm` 64f 128x128 with transposed A and C, `dot` 32f and 8u, `transform` 8uC3 3x3 and 32fC3 3x4
- reduce: `reduce` row sums 8u to 32s, column sums 32f
- copy: `transpose` 8u and 32f, `flip` around the y axis 16u

`targets.json` lists the exact case ids. The randomized check suite also covers every depth and channel count of these functions and many neighbours (bitwise ops, `min`/`max`, LUT, `reduce` variants, `extractChannel`, `scaleAdd`, `mulTransposed`, `perspectiveTransform`, norms with masks and relative norms), so a change that breaks an untimed path still fails the gate.

How you get there is up to you: SIMD with compiler intrinsics (`<immintrin.h>`), your own small vector layer, better scalar loops, restructured reductions. You may use instruction-set extensions through `__attribute__((target(...)))` or `#pragma GCC target`; the measuring machine is x86-64, but its exact extensions are not known in advance, so select wider paths at run time (`cv::checkHardwareSupport(CV_CPU_AVX2)`, `__builtin_cpu_supports`). Code that executes an instruction the CPU lacks crashes the run, and a crash scores 0.

## How it is built and measured

1. A clean copy of the shipped tree is unpacked; its `modules/core/src/` is replaced by yours (regular files only). Nothing else in `/app` is used: changes to CMake files, headers, `/app/build`, the bench tools or the system are ignored or, for the toolchain, rejected.
2. It is configured with `cmake-args.txt` (plus explicit paths to the system GCC 12, `ar` and `ranlib`) and built as an unprivileged user with Ninja. `cvbench.cpp` is linked statically against the result.
3. Toolchain check: the compiler, binutils, C and C++ runtime, zlib and CMake packages must match their dpkg checksums, with no extra programs in GCC's search directories and no `/etc/ld.so.preload`.
4. Correctness: `cvbench check <seed>` with a seed drawn at measurement time, on your build and on the shipped build; every record must match within its tolerance (below).
5. Timing: three `cvbench serve` processes (the shipped build, yours, and the optimized upstream build) receive the same commands. For each timed case they prepare the same random inputs; the iteration count is chosen so that one batch takes about 40 ms on the shipped build. Then 15 rounds run; in each round every process runs the same batch (same nonce, so the same input sequence) in a shuffled order, and the wall time of each batch is taken from outside the process. Every iteration reads its inputs from a different row offset and has one element rewritten, so results cannot be reused across calls. Per round the driver forms `t_shipped / t_yours` and `t_shipped / t_optimized`; a case's speedups `s_k` and `S_k` are the medians over the rounds. Your sampled outputs are compared with the shipped build's in every round, and your full outputs once per case.

The timed process calls `cv::setNumThreads(1)`. It must stay single-threaded: if your process has more than one thread or any child process during timing, the run fails the gate. Parallelism does not help here; per-core throughput is the target.

## Correctness tolerances

The shipped build defines the expected output. An element passes if its difference is within the absolute tolerance, or within the relative tolerance times its own magnitude, or (where a normwise tolerance is set) within that tolerance times the largest magnitude in the same output.

- Integer outputs: exact. Operations with a non-integer scale or weights (`multiply` and `divide` with scale, `divide`, `addWeighted`, `convertTo` and `convertScaleAbs` with alpha or beta, `transform`, `cvtSc` checks) may differ by 1.
- 32-bit float elementwise outputs: relative `1e-6`; `addWeighted`, `scaleAdd`, scaled `convertTo` and `transform` also normwise `1e-6`; `pow` relative `4e-6`; `phase` absolute `2e-4` radians (`1e-2` degrees); `polarToCart` absolute `1e-3` or relative `1e-5`.
- 64-bit float outputs: relative `1e-14` (`pow` `1e-13`, `gemm` `1e-10`, `cartToPolar` magnitude `1e-6`).
- Reductions (`sum`, `mean`, `meanStdDev`, `norm`, `dot`): relative `1e-6` for float inputs, `1e-12` (`meanStdDev` `1e-9`) for integer inputs. Counts, extrema and their locations: exact. `reduce` sums: relative or normwise `1e-5`.
- `gemm` and `mulTransposed` 32f: absolute `1e-5`, relative `1e-4` or normwise `1e-5`.

An OpenCV exception must match too: a call the shipped build rejects must be rejected. Every tolerance is written into each record of the check dump and into the case table in `cvbench.cpp`.

## Scoring

Hard gates, each scoring exactly 0: the build fails (configure, compile, link); the toolchain was modified; any check record differs; any timing case fails (a crash, a timeout, wrong outputs, extra threads or processes, or the timed process mapping any file other than its own binary); your sources reference the measurement's files or load code at run time (`dlopen`, `.incbin`, paths under `/tests` or `/logs`).

Otherwise, with families weighted equally and each family's weight split equally among its cases:

- `s = exp(sum_k w_k * ln(min(s_k, max(S_k, 1))))` your weighted geometric-mean speedup, each case capped at what the optimized build reaches,
- `S = exp(sum_k w_k * ln(S_k))` the optimized build's weighted geometric-mean speedup,
- `u = clamp((s - 1 - d) / (S - 1 - d), 0, 1)` with noise margin `d = 0.03`,
- `score = 2^u - 1`.

The untouched tree scores 0. Matching the optimized build on every case scores 1; there is no credit beyond it on any case, and a case you make slower than the shipped build pulls `s` down. On our test machine (an Intel Core Ultra 5 135U, AVX2, no AVX-512) `S` measured 7.25 to 7.47 over four runs; the measuring machine measures its own `S_k`, so the targets move with its CPU. A run in which the optimized build itself shows less than 1.5x is treated as a broken measurement and repeated, not scored.

## Checking your work

```
python3 /app/bench/selfcheck.py                  # build, check, time all cases, estimate the score
python3 /app/bench/selfcheck.py --check-only     # correctness only, seconds
python3 /app/bench/selfcheck.py --no-build --only add_8uC1,sum_32fC1 --reps 5
```

It builds with `build.sh`, runs the check suite against `bin/cvbench-base` with a fresh seed, times every case against the shipped build with the same driver, and estimates the score from `targets.json`. A full run takes a few minutes. Incremental builds of `/app/build` take seconds per file; a full rebuild takes about a minute on 8 cores. Commit often: `git -C /app/opencv` has the shipped state as its first commit.

## Time budget

You have 8 hours. The real remaining time is in `/app/.timer/remaining_secs` (the system clock tells you nothing useful); `alert_30min` and `alert_10min` appear in `/app/.timer` as the budget runs down. Check it before every long build or full timing run.

## Operating rules

Nobody will answer questions, so decide and keep going. Profile first: `selfcheck.py` prints each case's speedup next to the reachable one, and the biggest log-gap is the next job. Most families share a structure (a type switch, a row loop, a kernel per depth), so a good vector helper layer pays off across many of them. Keep the tree building and the check suite passing at every commit: one wrong record or one crash zeroes the whole score, so a fast kernel that is wrong in a corner (an odd width, a non-continuous view, a mask, saturation, NaN) is worth less than the scalar code it replaced. Revert what does not measurably help. Before the budget runs out, leave the last fully checked state in `/app/opencv/modules/core/src/`.
