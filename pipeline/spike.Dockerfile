# cgpipe image for smoke probes (pipeline/probe.sh) and spikes: a throwaway Debian box with build tools and Claude Code.
# Build: docker build -t cgpipe-spike:1 -f pipeline/spike.Dockerfile pipeline
# Network is on (the spike downloads upstream code). Nothing here is part of a task bundle.
FROM debian:bookworm-slim
LABEL cg.keep="1"

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat IS_SANDBOX=1 \
    PATH=/root/.cargo/bin:/usr/local/go/bin:$PATH

RUN printf 'Acquire::Retries "8";\nAcquire::http::Timeout "60";\n' > /etc/apt/apt.conf.d/80retries \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build pkg-config autoconf automake libtool git curl wget ca-certificates \
      python3 python3-pip python3-venv xz-utils unzip zip jq bc time file \
 && rm -rf /var/lib/apt/lists/*

# Node 22 + Claude Code (pinned)
ARG NODE_VERSION=22.11.0
ARG CLAUDE_CODE_VERSION=2.1.304
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
   | tar -xJ -C /usr/local --strip-components=1 \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && (claude --version || node /usr/local/lib/node_modules/@anthropic-ai/claude-code/install.cjs) \
 && claude --version \
 && npm cache clean --force

# Rust and Go are common in our subjects; preinstalling saves spike time and tokens.
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ARG GO_VERSION=1.23.4
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" | tar -xz -C /usr/local

WORKDIR /work

# The smoke stage's probe (pipeline/probe.sh) uses ccache for C/C++ builds and cargo-nextest for JUnit reports.
RUN apt-get update && apt-get install -y --no-install-recommends ccache && rm -rf /var/lib/apt/lists/* \
 && curl -LsSf https://get.nexte.st/latest/linux | tar zxf - -C /root/.cargo/bin && cargo nextest --version
