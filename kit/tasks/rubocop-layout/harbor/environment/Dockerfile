FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

ENV DEBIAN_FRONTEND=noninteractive PAGER=cat GIT_PAGER=cat LANG=C.UTF-8 LC_ALL=C.UTF-8

# Ruby 3.1 (Debian bookworm) with the headers and compilers the bundle's native gems need; python3 for the self-check.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git python3 xz-utils procps \
      ruby ruby-dev build-essential libyaml-dev libffi-dev zlib1g-dev pkg-config \
 && rm -rf /var/lib/apt/lists/* \
 && ruby -v

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

# The agent works as an unprivileged user; the Ruby toolchain and the installed gems stay root-owned.
RUN useradd -m -u 1000 -s /bin/bash agent

# The rubocop v1.92.0 tree with the Layout department taken out (see /app/README.txt), then every gem of its
# Gemfile.lock installed system-wide (bundler 2.6.9, no network after this layer).
WORKDIR /app
COPY rubocop-base.tar.gz /tmp/build/
RUN tar -xzf /tmp/build/rubocop-base.tar.gz -C /app && rm -rf /tmp/build \
 && gem install bundler -v 2.6.9 --no-document \
 && cd /app/rubocop && bundle _2.6.9_ install --jobs 8 --retry 3 \
 && rm -rf /var/lib/gems/*/cache/*.gem /root/.bundle /root/.local/share/gem \
 && bundle _2.6.9_ exec ruby -e 'require "rubocop"; puts RuboCop::Version::STRING'

COPY app/ /app/
RUN mkdir -p /app/.timer && chown -R agent:agent /app \
 && runuser -u agent -- sh -c 'cd /app/rubocop && git init -q && git add -A \
      && git -c user.name=start -c user.email=start@localhost commit -qm "starting point"'

# --- task timer (append at the end of environment/Dockerfile) ---
# COPY only — never auto-start it from the image (no ENV BASH_ENV, no shell
# profile hooks). The platform arms /app/timer.sh in the task sandbox with the
# real TASK_BUDGET_SECS. An image-side autostart also fires inside the image
# BUILD container and stalls the build until the timer's budget expires.
COPY timer.sh /app/timer.sh
RUN chmod +x /app/timer.sh && mkdir -p /app/.timer
