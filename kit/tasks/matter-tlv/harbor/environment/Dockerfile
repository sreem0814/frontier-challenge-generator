# Debian 12 (bookworm), pinned by digest.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8

# Toolchain: Debian's gcc 12, CMake 3.25, Ninja, jsoncpp 1.9.5 (the JSON library the JSON<->TLV converter
# uses), GoogleTest for any unit tests you write, Python 3.11 for the self-check, gdb for debugging.
# Nothing is fetched at run time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git less procps file xz-utils python3 \
      build-essential cmake ninja-build pkg-config libjsoncpp-dev libgtest-dev gdb \
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

# The trimmed connectedhomeip v1.6.1.0 tree with the TLV, message-header, onboarding-payload and JSON<->TLV
# implementations replaced by stubs. /usr/src/chip-base is the untouched starting tree; /app is the working copy.
COPY tree/ /usr/src/chip-base/
RUN chmod -R a+rX,go-w /usr/src/chip-base \
 && mkdir -p /app && cp -a /usr/src/chip-base/. /app/

# Workspace additions: build script and the self-check with its sample cases. Prebuild once.
WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/build.sh /app/check/selfcheck.py \
 && git config --global user.email "dev@localhost" && git config --global user.name "dev" \
 && git config --global init.defaultBranch main \
 && git init -q && git add -A && git commit -q -m "connectedhomeip v1.6.1.0 (trimmed) with the codec implementations stubbed" \
 && ./build.sh >/dev/null

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
