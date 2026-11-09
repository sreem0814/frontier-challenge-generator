FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8 LC_ALL=C.UTF-8

# C++ toolchain (GCC 12) and the compression libraries httplib.h is built with; python3 for the self-check.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 xz-utils procps \
      g++ make gdb zlib1g-dev libbrotli-dev libzstd-dev \
 && rm -rf /var/lib/apt/lists/* \
 && g++ --version | head -1

# Claude Code CLI: Node 22 from a pinned nodejs.org tarball, then a pinned global install.
ARG NODE_VERSION=22.11.0
ARG NODE_SHA256=83bf07dd343002a26211cf1fcd46a9d9534219aad42ee02847816940bf610a72
RUN cd /tmp \
 && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  node-v${NODE_VERSION}-linux-x64.tar.xz" | sha256sum -c - \
 && tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" -C /usr/local --strip-components=1 \
 && rm -f "node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && npm install -g @anthropic-ai/claude-code@2.1.305 \
 && npm cache clean --force \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
 && rm -rf /root/.npm /tmp/*

# The agent works as an unprivileged user; the toolchain stays root-owned.
RUN useradd -m -u 1000 -s /bin/bash agent

# cpp-httplib v0.62.0 with the message layer stubbed out (see /app/README.txt), as a one-commit repository.
WORKDIR /app
COPY app/ /app/
RUN mkdir -p /app/.timer && chown -R agent:agent /app \
 && runuser -u agent -- sh -c 'cd /app && git init -q && git add -A \
      && git -c user.name=start -c user.email=start@localhost commit -qm "starting point"'

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
