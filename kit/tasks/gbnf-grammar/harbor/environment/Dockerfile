# Debian 12 (bookworm), pinned by digest.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8

# Toolchain: Debian's gcc 12, CMake 3.25, Ninja, Python 3.11 for the self-check, gdb for debugging.
# Nothing is fetched at run time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git less procps file xz-utils python3 \
      build-essential cmake ninja-build pkg-config gdb \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: Node 22 from a pinned nodejs.org tarball (checksum pinned), then a pinned global install.
ARG NODE_VERSION=22.11.0
ARG NODE_SHA256=83bf07dd343002a26211cf1fcd46a9d9534219aad42ee02847816940bf610a72
RUN cd /tmp \
 && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  node-v${NODE_VERSION}-linux-x64.tar.xz" | sha256sum -c - \
 && tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" -C /usr/local --strip-components=1 \
 && rm -f "node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && npm install -g @anthropic-ai/claude-code@2.1.305 \
 && npm cache clean --force

# llama.cpp at commit 39da130 (MIT), trimmed to the library, common utilities, vendored headers, grammars and five
# vocabulary files, with the grammar engine, the JSON schema document builder and the JSON-schema-to-GBNF
# converter replaced by stubs. Fetch, trim and stub happen in one layer, and the result is checked against the
# hash of the expected tree. /usr/src/llama-base is the untouched starting tree; /app is the working copy.
ARG LLAMA_COMMIT=39da130fcd1b6ca47d3c0522a40eccff41ea3dfb
ARG TREE_SHA256=6586c5b58042ccc03fb7b532066ba73ca15a269e553eb751bc899bda0f9e67ca
COPY prune.sh stubs/ /tmp/prep/
RUN set -eu; cd /tmp/prep \
 && curl -fsSL -o llama.tgz "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/${LLAMA_COMMIT}" \
 && mkdir -p /usr/src/llama-base \
 && tar -xzf llama.tgz -C /usr/src/llama-base --strip-components=1 \
 && rm -f llama.tgz \
 && bash /tmp/prep/prune.sh /usr/src/llama-base \
 && cp /tmp/prep/llama-grammar.cpp /usr/src/llama-base/src/llama-grammar.cpp \
 && cp /tmp/prep/json-schema.cpp /tmp/prep/json-schema-to-grammar.cpp /usr/src/llama-base/common/ \
 && rm -rf /tmp/prep \
 && got="$(cd /usr/src/llama-base && find . -type f | LC_ALL=C sort | xargs -d '\n' sha256sum | sha256sum | cut -d' ' -f1)" \
 && [ "$got" = "$TREE_SHA256" ] \
 && chmod -R a+rX,go-w /usr/src/llama-base \
 && mkdir -p /app && cp -a /usr/src/llama-base/. /app/

# Workspace additions: build script and the self-check with its sample cases. Prebuild once.
WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/build.sh /app/check/selfcheck.py \
 && git config --global user.email "dev@localhost" && git config --global user.name "dev" \
 && git config --global init.defaultBranch main \
 && git init -q && git add -A && git commit -q -m "llama.cpp 39da130 (trimmed) with the grammar and JSON schema code stubbed" \
 && ./build.sh >/dev/null

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
