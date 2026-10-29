FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat

# Toolchain the agent works with. Every version is pinned; nothing is fetched at run time (no network).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 xz-utils procps less file unzip xxd \
 && rm -rf /var/lib/apt/lists/*

# Go 1.26.10 from the official tarball (checksum from go.dev/dl).
ARG GO_VERSION=1.26.10
ARG GO_SHA256=ccfe7ae822d2c2f41f4fe7c956199967a4dac22d0ee0d2b2bfdb440aab3b20c5
RUN curl -fsSLO "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" \
 && echo "${GO_SHA256}  go${GO_VERSION}.linux-amd64.tar.gz" | sha256sum -c - \
 && tar -xzf "go${GO_VERSION}.linux-amd64.tar.gz" -C /usr/local \
 && rm -f "go${GO_VERSION}.linux-amd64.tar.gz"
ENV PATH=/usr/local/go/bin:/home/agent/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GOFLAGS=-mod=vendor GOTOOLCHAIN=local GOPROXY=off CGO_ENABLED=0

# Claude Code CLI: Node 22 from a pinned nodejs.org tarball, then a pinned global install.
ARG NODE_VERSION=22.11.0
ARG NODE_SHA256=83bf07dd343002a26211cf1fcd46a9d9534219aad42ee02847816940bf610a72
RUN curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  node-v${NODE_VERSION}-linux-x64.tar.xz" | sha256sum -c - \
 && tar -xJf "node-v${NODE_VERSION}-linux-x64.tar.xz" -C /usr/local --strip-components=1 \
 && rm -f "node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && npm install -g @anthropic-ai/claude-code@2.1.290 \
 && npm cache clean --force

# The agent works as the unprivileged user "agent" ([agent] user in task.toml); the toolchain stays root-owned.
RUN useradd -m -u 1000 -s /bin/bash agent
ENV GOPATH=/home/agent/go GOCACHE=/home/agent/.cache/go-build

WORKDIR /app
# The Go module to complete (its vendor/ ships as a tarball), the published calamine 0.37.0 crate as a read-only
# reference, sample workbooks with their expected dumps, and the self-check. Nothing from tests/ or solution/.
COPY calamine-go /app/calamine-go
COPY samples /app/samples
COPY tools /app/tools
COPY calamine-go-vendor.tar.gz calamine-0.37.0.crate /tmp/build/
ARG CRATE_SHA256=c9ca341b94bc4b29e08970b1a03914fad2dfe177e2ecb67fcd6de9046004aafb
RUN echo "${CRATE_SHA256}  /tmp/build/calamine-0.37.0.crate" | sha256sum -c - \
 && mkdir -p /app/reference /app/.timer \
 && tar -xzf /tmp/build/calamine-0.37.0.crate -C /app/reference \
 && tar -xzf /tmp/build/calamine-go-vendor.tar.gz -C /app/calamine-go \
 && rm -rf /tmp/build \
 && chmod -R a-w /app/reference \
 && chown -R agent:agent /app/calamine-go /app/samples /app/tools /app/.timer \
 && chown agent:agent /app \
 && runuser -u agent -- env HOME=/home/agent PATH="$PATH" sh -c 'cd /app/calamine-go && go build ./... \
      && git init -q && git add -A && git -c user.name=start -c user.email=start@localhost commit -qm "starting point"'

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
