# Debian 12 (bookworm), pinned by digest.
FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat

# Toolchain: Debian's Python 3.11 with NumPy 1.24, plus basic tools. Nothing is fetched at run time.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git less procps python3 python3-numpy \
      xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: Node 22 from a pinned nodejs.org tarball, then a pinned global install.
ARG NODE_VERSION=22.11.0
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
   | tar -xJ -C /usr/local --strip-components=1 \
 && npm install -g @anthropic-ai/claude-code@2.1.290 \
 && npm cache clean --force

# The workspace: package skeleton, visible examples with reference outputs, MuJoCo 3.16.0 docs, tools.
WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/tools/selfcheck.py \
 && git config --global user.email dev@example.com && git config --global user.name dev \
 && git init -q /app && git -C /app add -A && git -C /app commit -qm "skeleton"

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
