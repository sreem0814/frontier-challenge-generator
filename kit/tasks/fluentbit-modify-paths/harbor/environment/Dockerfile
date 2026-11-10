FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8 LC_ALL=C.UTF-8

# C toolchain and the libraries Fluent Bit's build needs (all its other dependencies are vendored in lib/).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 xz-utils procps \
      build-essential cmake flex bison pkg-config libssl-dev libyaml-dev zlib1g-dev gdb \
 && rm -rf /var/lib/apt/lists/* \
 && cmake --version | head -1

# Claude Code CLI: Node 22 from a pinned nodejs.org tarball, then a pinned global install.
ARG NODE_VERSION=22.11.0
ARG NODE_SHA256=83bf07dd343002a26211cf1fcd46a9d9534219aad42ee02847816940bf610a72
RUN cd /tmp \
 && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  node-v${NODE_VERSION}-linux-x64.tar.xz" | sha256sum -c - \
 && tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" -C /usr/local --strip-components=1 \
 && rm -f "node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && npm install -g @anthropic-ai/claude-code@2.1.305 \
 && npm cache clean --force

# The agent works as an unprivileged user.
RUN useradd -m -u 1000 -s /bin/bash agent

# Fluent Bit at commit f4739648 (git archive of the upstream tree). A root-owned copy stays in /opt as the
# pristine base; the working copy in /app/fluent-bit belongs to the agent and is built once here.
COPY fluent-bit-f4739648.tar.xz /opt/fluent-bit-base/
RUN chmod 755 /opt/fluent-bit-base && chmod 644 /opt/fluent-bit-base/fluent-bit-f4739648.tar.xz \
 && mkdir -p /app && tar -xJf /opt/fluent-bit-base/fluent-bit-f4739648.tar.xz -C /app

COPY app/ /app/
RUN chmod +x /app/tools/build.sh && mkdir -p /app/.timer && chown -R agent:agent /app \
 && runuser -u agent -- env JOBS=8 bash /app/tools/build.sh >/tmp/prebuild.log 2>&1 \
 || (tail -50 /tmp/prebuild.log; exit 1)
RUN rm -f /tmp/prebuild.log \
 && runuser -u agent -- sh -c 'cd /app/fluent-bit && git init -q && echo "build/" >> .git/info/exclude \
      && git add -A && git -c user.name=start -c user.email=start@localhost commit -qm "starting point"'

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
