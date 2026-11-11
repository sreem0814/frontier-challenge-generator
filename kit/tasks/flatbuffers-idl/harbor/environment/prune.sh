#!/usr/bin/env bash
# prune.sh <extracted flatbuffers dir>: keep only what the task tree needs: the C++ library and flatc sources,
# their CMake build, the reflection schema and the format documentation. Everything else goes: the tests (with
# their golden binaries, binary schemas and expected outputs), the language runtimes and ports, samples,
# examples, benchmarks, generated code and packaging.
set -euo pipefail
cd "$1"
keep="CMakeLists.txt CMake LICENSE README.md include src grpc reflection docs"
for e in * .[!.]*; do
  case " $keep " in *" $e "*) ;; *) rm -rf -- "$e" ;; esac
done
# grpc: only the code generators flatc links
find grpc -mindepth 1 -maxdepth 1 ! -name src -exec rm -rf {} +
find grpc/src -mindepth 1 -maxdepth 1 ! -name compiler -exec rm -rf {} +
# reflection: only the schema of the binary schema format
find reflection -mindepth 1 ! -name reflection.fbs -exec rm -rf {} +
# docs: the top-level pages of the format documentation (schema language, grammar, flatc, evolution,
# binary schema); no site config, assets or per-language guides
find docs -mindepth 1 -maxdepth 1 ! -name source -exec rm -rf {} +
find docs/source -mindepth 1 \( -type d -o ! -name '*.md' \) -prune -exec rm -rf {} +
# bazel and precompiled-header leftovers
find . \( -name BUILD.bazel -o -name '*.bzl' -o -name pch \) -prune -exec rm -rf {} +
