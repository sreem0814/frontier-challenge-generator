FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates build-essential cmake ninja-build pkg-config \
      zlib1g-dev libssl-dev python3 python3-numpy git xz-utils procps \
 && rm -rf /var/lib/apt/lists/*
