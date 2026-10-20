# Pin the base by digest: docker pull debian:bookworm-slim && docker inspect --format '{{index .RepoDigests 0}}'
FROM debian:bookworm-slim@sha256:REPLACE_WITH_DIGEST

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat

# Toolchain the agent works with. Pin every version; nothing is fetched at run time (no network).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: Node >= 22 from a pinned nodejs.org tarball, then a pinned global install.
# Keep optional dependencies (the native binary ships as one).
ARG NODE_VERSION=22.11.0
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
   | tar -xJ -C /usr/local --strip-components=1 \
 && npm install -g @anthropic-ai/claude-code@REPLACE_WITH_VERSION \
 && npm cache clean --force

WORKDIR /app
# COPY the system the agent works on here. Nothing from tests/ or solution/ goes in the image.


# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
