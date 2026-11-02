# Debian 12 (bookworm), pinned by digest.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8

# Toolchain: Debian's gcc 12, CMake 3.25, Ninja, the two libraries FreeRDP's core needs (zlib, OpenSSL),
# Python 3.11 for the self-check, gdb for debugging. Nothing is fetched at run time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git less procps file xz-utils python3 \
      build-essential cmake ninja-build pkg-config zlib1g-dev libssl-dev gdb \
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

# FreeRDP 3.32.2 (release tarball, checksum pinned). The bitmap codec implementations are replaced by
# the stubs in stubs/ in the same step, so no image layer holds the original codec sources.
# /usr/src/freerdp-3.32.2 is the untouched starting tree; /app is the working copy.
COPY stubs/ /tmp/stubs/
ARG FREERDP_SHA256=e95a505c0057e4d06a3b120477c421028769deba4db9c639ef3465d050f0955c
RUN cd /tmp \
 && curl -fsSLO "https://github.com/FreeRDP/FreeRDP/releases/download/3.32.2/freerdp-3.32.2.tar.gz" \
 && echo "${FREERDP_SHA256}  freerdp-3.32.2.tar.gz" | sha256sum -c - \
 && mkdir -p /usr/src && tar --no-same-owner -xzf freerdp-3.32.2.tar.gz -C /usr/src \
 && cp -r /tmp/stubs/. /usr/src/freerdp-3.32.2/ \
 && rm -rf /tmp/stubs freerdp-3.32.2.tar.gz \
 && chmod -R a+rX,go-w /usr/src/freerdp-3.32.2 \
 && mkdir -p /app && cp -a /usr/src/freerdp-3.32.2/. /app/

# The workspace additions: build script, codec notes, self-check and sample streams. Prebuild once so the
# first incremental build is quick.
WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/build.sh /app/check/selfcheck.py \
 && git config --global user.email "dev@localhost" && git config --global user.name "dev" \
 && git config --global init.defaultBranch main \
 && git init -q && git add -A && git commit -q -m "FreeRDP 3.32.2 with the bitmap codec implementations removed" \
 && ./build.sh >/dev/null

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
