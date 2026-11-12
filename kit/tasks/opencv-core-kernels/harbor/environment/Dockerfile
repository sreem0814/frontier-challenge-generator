# Debian 12 (bookworm), pinned by digest.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat

# Toolchain: GCC 12, CMake 3.25, Ninja, zlib; Python 3.11 for the self-check. Nothing is fetched at run time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake ninja-build zlib1g-dev python3 \
      ca-certificates curl git less procps xz-utils gdb binutils \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: Node 22 from a pinned nodejs.org tarball, then a pinned global install.
ARG NODE_VERSION=22.11.0
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
   | tar -xJ -C /usr/local --strip-components=1 \
 && npm install -g @anthropic-ai/claude-code@2.1.305 \
 && npm cache clean --force

# The workspace: OpenCV core (vector code removed; packed as one archive of the source tree) and the
# benchmark/self-check tools.
WORKDIR /app
COPY opencv-src.tar.xz /tmp/opencv-src.tar.xz
COPY bench/ /app/bench/
RUN tar -xJf /tmp/opencv-src.tar.xz -C /app && rm /tmp/opencv-src.tar.xz \
 && chmod +x /app/bench/*.sh /app/bench/selfcheck.py \
 && bash /app/bench/build.sh \
 && cp /app/bench/bin/cvbench /app/bench/bin/cvbench-base \
 && git config --global user.email dev@example.com && git config --global user.name dev \
 && printf 'build/\nbench/bin/cvbench\nbench/work/\nbench/__pycache__/\n.timer/\n' > /app/.gitignore \
 && git init -q /app && git -C /app add -A && git -C /app commit -qm "OpenCV core without vector code"

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
