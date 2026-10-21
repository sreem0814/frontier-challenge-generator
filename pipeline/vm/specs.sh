#!/usr/bin/env bash
# specs.sh: print the WSL side's specs for CG setup. Run inside Ubuntu (WSL):  bash specs.sh
# Paste the whole output back. It prints no secrets.
set -u
echo "== Distro";   . /etc/os-release 2>/dev/null; echo "$PRETTY_NAME, kernel $(uname -r)"
echo "== CPU/RAM";  echo "nproc $(nproc)"; free -h | awk 'NR<=3'
echo "== systemd";  ps -p 1 -o comm=; systemctl is-system-running 2>&1 | head -1
echo "== Disks (inside WSL, / shows the virtual disk; /mnt/<drive> shows the real Windows free space)"
df -h / /mnt/c /mnt/d /mnt/e 2>/dev/null | awk 'NR==1 || /\//'
echo "== WSL config"; cat /etc/wsl.conf 2>/dev/null || echo "(no /etc/wsl.conf)"
echo "== Tools"
for c in docker tailscale tmux rsync git curl python3 uv harbor claude gh; do
  p=$(command -v "$c" 2>/dev/null || ls ~/.local/bin/"$c" 2>/dev/null)
  printf '%-10s %s\n' "$c" "${p:-missing}"
done
command -v docker >/dev/null && { docker version --format 'docker server {{.Server.Version}}' 2>&1 | head -1
  docker info --format 'docker root {{.DockerRootDir}}, images {{.Images}}, containers {{.Containers}}' 2>&1 | head -1
  docker system df 2>/dev/null; }
command -v tailscale >/dev/null && { echo "tailscale: $(tailscale status --self --peers=false 2>&1 | head -1 | awk '{print $1, $2}')"; }
echo "== Network (download test, about 100 MB)"
ok=0
for u in "https://speed.cloudflare.com/__down?bytes=100000000" "https://proof.ovh.net/files/100Mb.dat" "http://speedtest.tele2.net/100MB.zip"; do
  t0=$(date +%s.%N)
  bytes=$(curl -fsS -A "Mozilla/5.0" -o /dev/null -w '%{size_download}' "$u" 2>/dev/null) || { echo "  $u: failed"; continue; }
  awk -v s="$(date +%s.%N)" -v t="$t0" -v b="$bytes" -v u="$u" 'BEGIN{printf "about %.0f Mbit/s (%s)\n", b*8/1e6/(s-t), u}'
  ok=1; break
done
[ "$ok" = 1 ] || echo "download test failed on every test server"
