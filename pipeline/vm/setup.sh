#!/usr/bin/env bash
# setup.sh: set up the WSL side of a trial runner (vm2, vm3), shared by every project that runs trials there.
# Idempotent: safe to run again, also on a runner that was set up before (it keeps what is there).
#
#   bash setup.sh --hostname vm2 --host-drive /mnt/c [--no-tailscale]
#
# Run it inside Ubuntu (WSL 2) as your normal user; it asks for your sudo password. It installs: base tools, Docker
# Engine (with log limits and build-cache GC), Tailscale (joins your tailnet, or renames this node, as --hostname),
# key-only SSH for VM 1, uv + Harbor 0.24.0, ~/.runner/, CG's keys file ~/cg.env (Claude keys only),
# and the disk janitor (runner-cleanup, hourly).
# --host-drive is the Windows drive that holds this distro's ext4.vhdx, as seen from WSL (/mnt/c, /mnt/d ...).
# VM 1's public key is read from vm1.pub next to this script (VM 1 copies both to ~/runner-setup/).
set -euo pipefail
HN="" DRIVE="" TS=1
while [ $# -gt 0 ]; do case "$1" in
  --hostname) HN="$2"; shift 2 ;; --host-drive) DRIVE="$2"; shift 2 ;; --no-tailscale) TS=0; shift ;;
  *) echo "unknown option $1"; exit 2 ;; esac; done
[ -n "$HN" ] && [ -n "$DRIVE" ] || { sed -n '2,12p' "$0"; exit 2; }
HERE="$(cd "$(dirname "$0")" && pwd)"
say() { printf '\n== %s\n' "$*"; }

say "checks"
grep -qi microsoft /proc/version || { echo "not WSL: this script is for the WSL side of a Windows VM"; exit 1; }
[ "$(id -u)" != 0 ] || { echo "run as your normal user, not root"; exit 1; }
[ -d "$DRIVE" ] || { echo "$DRIVE not found: pass the Windows drive that holds the distro, e.g. /mnt/c"; exit 1; }
if [ "$(ps -p 1 -o comm=)" != systemd ]; then
  if ! grep -q '^\[boot\]' /etc/wsl.conf 2>/dev/null; then printf '\n[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null; fi
  grep -q '^systemd=true' /etc/wsl.conf || sudo sed -i '/^\[boot\]/a systemd=true' /etc/wsl.conf
  echo "systemd was off: enabled it in /etc/wsl.conf. In PowerShell run 'wsl --shutdown', reopen Ubuntu, run this again."
  exit 0
fi

say "base packages"
sudo apt-get update -q
sudo apt-get install -y -q tmux rsync curl ca-certificates git jq python3 python3-venv openssh-server bc

say "Docker Engine"
if ! command -v docker >/dev/null; then
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  . /etc/os-release
  printf 'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
    "${UBUNTU_CODENAME:-$VERSION_CODENAME}" "$(dpkg --print-architecture)" | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
  sudo apt-get update -q
  sudo apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# container logs capped at 3 x 10 MB; build cache garbage-collected at 20 GB
sudo mkdir -p /etc/docker
echo '{"log-driver":"json-file","log-opts":{"max-size":"10m","max-file":"3"},"builder":{"gc":{"enabled":true,"defaultKeepStorage":"20GB"}}}' \
  | sudo tee /etc/docker/daemon.json >/dev/null
sudo systemctl enable --now docker containerd
sudo systemctl restart docker
id -nG | grep -qw docker || { sudo usermod -aG docker "$USER"; echo "added $USER to the docker group (takes effect at next login)"; }

if [ "$TS" = 1 ]; then
  say "Tailscale (inside WSL; Windows' own Tailscale can't carry WSL 2 traffic)"
  command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
  sudo systemctl enable --now tailscaled
  if ! tailscale status >/dev/null 2>&1; then
    echo "Open the URL below and log in to the same tailnet as VM 1:"
    sudo tailscale up --hostname="$HN" --ssh=false
  else sudo tailscale set --hostname="$HN" || true; fi
fi

say "SSH for VM 1 (key only)"
mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
if [ -s "$HERE/vm1.pub" ]; then
  key="$(awk '{print $1, $2}' "$HERE/vm1.pub")"      # type and key only; the comment is dropped
  grep -qF "$key" ~/.ssh/authorized_keys || echo "$key vm1" >> ~/.ssh/authorized_keys
else echo "WARNING: $HERE/vm1.pub missing: VM 1 can't log in until its key is in ~/.ssh/authorized_keys"; fi
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/90-runner.conf >/dev/null
sudo systemctl enable --now ssh
sudo systemctl restart ssh

say "uv and Harbor 0.24.0"
[ -x ~/.local/bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv tool install --python 3.12 harbor==0.24.0 >/dev/null 2>&1 || ~/.local/bin/uv tool upgrade harbor
grep -q 'local/bin' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

say "runner folder and keys file"
mkdir -p ~/.runner
# Each project has its own keys file with only the keys it needs; this creates CG's (other projects' files are left alone).
if [ ! -e ~/cg.env ]; then
  install -m 600 /dev/null ~/cg.env
  printf '# CG trial keys (Claude Code agent). Stays on this runner. Fill in with: nano ~/cg.env\nCLAUDE_CODE_OAUTH_TOKEN=\nCLAUDE_FORCE_OAUTH=1\n' > ~/cg.env
fi
chmod 600 ~/cg.env

say "disk janitor (hourly)"
if [ -f /etc/systemd/system/cg-cleanup.timer ]; then         # older name for the same janitor
  sudo systemctl disable --now cg-cleanup.timer 2>/dev/null || true
  sudo rm -f /etc/systemd/system/cg-cleanup.{timer,service} /usr/local/bin/cg-cleanup /etc/cg-cleanup.conf
fi
sudo install -m 755 "$HERE/cleanup.sh" /usr/local/bin/runner-cleanup
printf 'RUN_USER=%s\nHOST_DRIVE=%s\nRUN_DIRS="cg-runs tb-runs"\nMARKER_DIRS="cg-runs"\nMIN_HOST_FREE_GB=40\nWARN_HOST_FREE_GB=60\nMAX_ROOT_USED_PCT=80\nPULLED_KEEP_HOURS=24\nUNPULLED_KEEP_DAYS=7\nIMAGE_KEEP_HOURS=72\n' \
  "$USER" "$DRIVE" | sudo tee /etc/runner-cleanup.conf >/dev/null
printf '[Unit]\nDescription=Trial runner disk janitor\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/runner-cleanup\nNice=10\nIOSchedulingClass=idle\n' \
  | sudo tee /etc/systemd/system/runner-cleanup.service >/dev/null
printf '[Unit]\nDescription=Run the trial runner disk janitor hourly\n[Timer]\nOnBootSec=5min\nOnUnitActiveSec=1h\nPersistent=true\n[Install]\nWantedBy=timers.target\n' \
  | sudo tee /etc/systemd/system/runner-cleanup.timer >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now runner-cleanup.timer
sudo /usr/local/bin/runner-cleanup

say "summary"
echo "hostname (tailnet): $HN   tailscale ip: $(tailscale ip -4 2>/dev/null | head -1)"
echo "docker: $(sudo docker version --format '{{.Server.Version}}' 2>&1 | head -1)   harbor: $(~/.local/bin/harbor --version 2>&1)"
echo "cpus: $(nproc)   memory: $(free -h | awk 'NR==2{print $2}')   windows drive $DRIVE free: $(df -h --output=avail "$DRIVE" | tail -1)"
echo "janitor: $(tail -1 ~/.runner/cleanup.log)"
echo "CG keys file: ~/cg.env (fill in CLAUDE_CODE_OAUTH_TOKEN before CG trials)"
echo "next: tell VM 1 this runner is ready."
