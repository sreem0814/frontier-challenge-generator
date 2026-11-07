#!/usr/bin/env bash
# prune.sh <extracted llama.cpp dir>: keep only what the task tree needs (same list as the Dockerfile's RUN).
set -euo pipefail
cd "$1"
keep="CMakeLists.txt CMakePresets.json LICENSE licenses cmake ggml src include common vendor grammars models"
for e in * .[!.]*; do
  case " $keep " in *" $e "*) ;; *) rm -rf -- "$e" ;; esac
done
find models -mindepth 1 -maxdepth 1 ! -name 'ggml-vocab-llama-spm.gguf' ! -name 'ggml-vocab-llama-bpe.gguf' \
  ! -name 'ggml-vocab-phi-3.gguf' ! -name 'ggml-vocab-deepseek-coder.gguf' ! -name 'ggml-vocab-falcon.gguf' -exec rm -rf {} +
