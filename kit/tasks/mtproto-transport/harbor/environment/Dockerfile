# Go toolchain on Debian bookworm, pinned by digest.
FROM golang:1.25.14-bookworm@sha256:3b4a11519ad929d1e1d261a12cff056f0c85b735253d7d861346b9c6f8b36437

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 procps xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: Node >= 22 from a pinned nodejs.org tarball, then a pinned global install.
# Keep optional dependencies (the native binary ships as one).
ARG NODE_VERSION=22.11.0
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
   | tar -xJ -C /usr/local --strip-components=1 \
 && npm install -g @anthropic-ai/claude-code@2.1.292 \
 && npm cache clean --force

# The system: github.com/gotd/td at v0.162.0 (commit be24580), fetched as the checksummed module zip
# from the Go module proxy. The copy in the module cache is deleted in the same step, so the image
# holds only the working tree below.
WORKDIR /app
RUN set -eux; \
    mkdir -p /tmp/fetch; cd /tmp/fetch; go mod init fetch >/dev/null 2>&1; \
    GOFLAGS=-mod=mod go mod download -json github.com/gotd/td@v0.162.0 > dl.json; \
    grep -q '"Sum": "h1:3pUzBsEbb0I5QquvfSkXihkVBXI+QTtdd/upijjUbkw="' dl.json; \
    cp -r "$(go env GOMODCACHE)/github.com/gotd/td@v0.162.0/." /app/; \
    rm -rf "$(go env GOMODCACHE)/github.com/gotd/td@v0.162.0" "$(go env GOMODCACHE)/cache/download/github.com/gotd/td" /tmp/fetch; \
    chmod -R u+w /app; \
    rm -rf /app/_fuzz; \
    for d in proto/codec mtproxy/obfuscated2 crypto exchange mtproto mtproto/salts rpc; do find "/app/$d" -maxdepth 1 -name '*.go' -delete; done

# The four packages to rebuild, reduced to their exported API, plus the self-check tool.
COPY overlay/ /app/

# Dependencies for an offline build (root-owned, read-only to the agent).
RUN set -eux; cd /app; \
    go mod download; \
    test ! -e "$(go env GOMODCACHE)/github.com/gotd/td@v0.162.0"; \
    chmod -R go-w /go/pkg

# The agent works as an unprivileged user that owns /app; its build cache is warmed here.
RUN set -eux; \
    useradd -m -u 1000 -s /bin/bash agent; \
    chmod +x /app/selfcheck/run.sh; \
    mkdir -p /app/.timer; \
    chown -R agent:agent /app; \
    chmod 777 /app/.timer; \
    runuser -u agent -- env HOME=/home/agent PATH="$PATH" GOPATH=/go bash -euc ' \
      cd /app; \
      go build ./...; \
      go test -count=1 -run "^$" ./... > /dev/null; \
      git init -q; \
      printf ".timer/\ntimer.sh\n" >> .git/info/exclude; \
      git add -A; \
      git -c user.name=base -c user.email=base@localhost commit -qm "base: v0.162.0 with the transport and crypto packages reduced to their API"'

ENV GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local GOFLAGS=-buildvcs=false

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
