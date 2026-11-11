# Debian 12 (bookworm), pinned by digest.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8

# Toolchain: Debian's gcc 12, CMake 3.25, Ninja, Python 3.11 for the self-check, gdb for debugging.
# Nothing is fetched at run time. No FlatBuffers package (compiler or library) is installed.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git less procps file xz-utils python3 \
      build-essential cmake ninja-build pkg-config gdb xxd \
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

# FlatBuffers v25.12.19 (commit 7e16302, Apache-2.0), trimmed to the C++ headers, the flatc sources, their CMake
# build, reflection/reflection.fbs and the format documentation, with src/idl_parser.cpp replaced by a stub.
# Fetch, trim and stub happen in one layer, and the result is checked against the hash of the expected tree.
# /usr/src/flatbuffers-base is the untouched starting tree; /app is the working copy.
ARG FB_COMMIT=7e163021e59cca4f8e1e35a7c828b5c6b7915953
ARG FB_TGZ_SHA256=4236c5d22309abeac2384d3800febcc8d60423e8cb2f573abfa8f798352c4536
ARG TREE_SHA256=d3b3e84768a07a298171586cf05c0b8633656e9f244acf8700045a6a2aefe380
COPY prune.sh stubs/ /tmp/prep/
RUN set -eu; cd /tmp/prep \
 && curl -fsSL -o fb.tgz "https://codeload.github.com/google/flatbuffers/tar.gz/${FB_COMMIT}" \
 && echo "${FB_TGZ_SHA256}  fb.tgz" | sha256sum -c - \
 && mkdir -p /usr/src/flatbuffers-base \
 && tar -xzf fb.tgz -C /usr/src/flatbuffers-base --strip-components=1 \
 && rm -f fb.tgz \
 && bash /tmp/prep/prune.sh /usr/src/flatbuffers-base \
 && cp /tmp/prep/idl_parser.cpp /usr/src/flatbuffers-base/src/idl_parser.cpp \
 && rm -rf /tmp/prep \
 && got="$(cd /usr/src/flatbuffers-base && find . -type f | LC_ALL=C sort | xargs -d '\n' sha256sum | sha256sum | cut -d' ' -f1)" \
 && [ "$got" = "$TREE_SHA256" ] \
 && chmod -R a+rX,go-w /usr/src/flatbuffers-base \
 && mkdir -p /app && cp -a /usr/src/flatbuffers-base/. /app/

# Workspace additions: build script and the self-check with its sample cases. Prebuild once.
WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/build.sh /app/check/selfcheck.py \
 && git config --global user.email "dev@localhost" && git config --global user.name "dev" \
 && git config --global init.defaultBranch main \
 && git init -q && git add -A && git commit -q -m "flatbuffers v25.12.19 (trimmed) with the schema parser stubbed" \
 && ./build.sh >/dev/null

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
