# Provenance

## Source

OpenCV, https://github.com/opencv/opencv, commit `e70c9dab7c9ecd9f4e9c82005d882b3cd2567256` (the 5.x development line, 5.1.0-dev, after the 5.0.0 release), Apache-2.0. Only the core module and the top-level build system are used.

## Extraction

The environment ships the top-level CMake files, `cmake/`, `include/` and `modules/core/` of that commit. Everything else is removed: the other modules (including `ts`, so the gtest suites are gone), all of `3rdparty/` (IPP/ICV, TBB, Carotene, KleidiCV, FastCV, MLAS, zlib; the system zlib is used) and all of `hal/`. In the core module the universal-intrinsics headers (`opencv2/core/hal/intrin*.hpp` for every backend, `simd_utils.impl.hpp`, `simd_intrinsics.hpp`) are deleted; `unifdef` evaluates every SIMD and ISA macro (`CV_SIMD*`, `CV_SSE*`, `CV_AVX*`, `CV_NEON*`, `CV_TRY_*`, `CV_ENABLE_UNROLLED`, `HAVE_IPP`, ...) as off in `modules/core/src`, and the vector-only templates, `SIMD_ONLY(...)` bodies and intrinsic macros that remain are removed; a small header (`vec_tags.hpp`) keeps the kernel templates' work-type parameters compiling. The per-ISA dispatch lists in the core CMake file are emptied, and two comments are reworded. The result builds as plain x86-64 code and computes the same results as upstream's scalar paths.

The optimized build used for the target speedups is the same upstream commit, built with OpenCV's default x86-64 configuration (SSE3 baseline, run-time dispatch to SSE4.1, AVX, AVX2 and AVX-512), with IPP off. The verifier ships it only as a statically linked benchmark binary. The benchmark (`cvbench.cpp`) and its check suite were written for this task; inputs are random and generated when the measurement runs.

## Why it is real work

OpenCV's core kernels exist twice upstream: a portable scalar version and a vectorized one, maintained for years across a dozen instruction sets. Porting a library to a platform without its SIMD layer, or rewriting hot kernels after a vector abstraction is dropped, is ordinary performance engineering: profile, vectorize one depth at a time, handle tails, masks, saturation and rounding exactly, and keep a large regression suite green.
