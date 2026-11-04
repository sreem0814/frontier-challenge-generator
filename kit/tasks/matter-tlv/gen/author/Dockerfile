FROM debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git python3 \
    build-essential cmake ninja-build pkg-config libjsoncpp-dev libgtest-dev file \
 && rm -rf /var/lib/apt/lists/*
