# Prototype smoke+test image: spike image tools minus Claude, plus test reporters and caches.
FROM cgpipe-spike:1
RUN apt-get update && apt-get install -y --no-install-recommends ccache meson python3-yaml util-linux \
 && rm -rf /var/lib/apt/lists/*
RUN curl -LsSf https://get.nexte.st/latest/linux | tar zxf - -C /root/.cargo/bin && cargo nextest --version
ENV PATH=/root/.cargo/bin:/usr/local/go/bin:/root/go/bin:$PATH GOPATH=/root/go
