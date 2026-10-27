FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8

# Base tools, a C linker for rustc, python3 for the self-check. No image or SVG libraries.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 xz-utils gcc libc6-dev make procps \
 && rm -rf /var/lib/apt/lists/*

# Rust 1.98.0 from the official standalone installer (checksum pinned). No crates are available offline.
ARG RUST_VERSION=1.98.0
ARG RUST_SHA256=ed8ee2df70909c88cbaf87a6cfa3920dac00b537de12a6abe6906641e0f5952f
RUN cd /tmp \
 && curl -fsSLO "https://static.rust-lang.org/dist/rust-${RUST_VERSION}-x86_64-unknown-linux-gnu.tar.xz" \
 && echo "${RUST_SHA256}  rust-${RUST_VERSION}-x86_64-unknown-linux-gnu.tar.xz" | sha256sum -c - \
 && tar -xJf "rust-${RUST_VERSION}-x86_64-unknown-linux-gnu.tar.xz" \
 && "rust-${RUST_VERSION}-x86_64-unknown-linux-gnu/install.sh" --prefix=/usr/local \
      --components=rustc,cargo,rust-std-x86_64-unknown-linux-gnu,rustfmt-preview,clippy-preview \
 && rm -rf /tmp/rust-* \
 && rustc --version && cargo --version

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

# The workspace: an empty renderer crate, the visible sample cases and the self-check.
WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/tools/selfcheck.py \
 && git config --global user.email "dev@localhost" && git config --global user.name "dev" \
 && git config --global init.defaultBranch main \
 && git init -q && git add -A && git commit -q -m "Initial workspace" \
 && cargo build --release --offline --quiet && rm -rf target

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
