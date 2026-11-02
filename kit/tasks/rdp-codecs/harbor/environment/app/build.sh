#!/usr/bin/env bash
# Build libwinpr3 and libfreerdp3 into /app/build with exactly the options the grader uses.
# First run configures (about 20 s); later runs only recompile what changed.
#   ./build.sh            configure if needed, then build the two libraries
#   ./build.sh clean      remove /app/build first
set -euo pipefail
cd "$(dirname "$0")"
[ "${1:-}" = clean ] && rm -rf build
if [ ! -f build/build.ninja ]; then
  cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DBUILD_TESTING=OFF \
    -DWITH_SIMD=OFF -DWITH_CCACHE=OFF -DWITH_CLANG_FORMAT=OFF -DWITH_CLIENT=OFF -DWITH_CLIENT_COMMON=OFF \
    -DWITH_CLIENT_INTERFACE=OFF -DWITH_SERVER=OFF -DWITH_SAMPLE=OFF -DWITH_CHANNELS=OFF -DWITH_KRB5=OFF \
    -DWITH_PKCS11=OFF -DWITH_SMARTCARD_EMULATE=OFF -DWITH_PCSC=OFF -DWITH_OSS=OFF -DWITH_ALSA=OFF \
    -DWITH_PULSE=OFF -DWITH_FFMPEG=OFF -DWITH_SWSCALE=OFF -DWITH_JPEG=OFF -DWITH_CAIRO=OFF -DWITH_X11=OFF \
    -DWITH_WAYLAND=OFF -DWITH_FUSE=OFF -DWITH_AAD=OFF -DWITH_UNICODE_BUILTIN=ON -DWITH_WINPR_TOOLS=OFF \
    -DWITH_MANPAGES=OFF -DWITH_OPENH264=OFF -DWITH_SYSTEMD=OFF -DWITH_JSON_DISABLED=ON >/dev/null
fi
ninja -C build freerdp
