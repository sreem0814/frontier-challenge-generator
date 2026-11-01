#!/usr/bin/env bash
# cleanup.sh (installed as /usr/local/bin/runner-cleanup): disk janitor for a trial runner VM (WSL 2), shared by every
# project that runs trials there (each project keeps its runs under ~/<project>-runs/, e.g. ~/cg-runs, ~/tb-runs).
#
# WSL keeps Ubuntu's disk in one ext4.vhdx file on a Windows drive. The file grows with Docker images and runs, and
# when the Windows drive fills up, Ubuntu remounts read-only and the VM is lost until someone repairs it. `df /` inside
# WSL cannot see this (it shows the virtual size), so the janitor watches the real Windows drive through /mnt/<drive>.
#
# Normal pass (hourly, systemd timer): prune stopped containers, unused images older than 72 h (never images labelled
# cg.keep=1 or runner.keep=1), build cache older than 24 h, unused volumes and networks; in each RUN_DIRS folder,
# delete run folders a day after VM 1 pulled them (PULLED marker) and finished-but-unpulled runs after 7 days; vacuum
# logs; fstrim so a sparse vhdx shrinks.
# Emergency pass (Windows drive below MIN_HOST_FREE_GB, or / above MAX_ROOT_USED_PCT): set ~/.runner/DISK_LOW (new
# runs are refused), prune every unused image and all build cache, delete every pulled run. DISK_LOW clears itself
# once the drive is back above WARN_HOST_FREE_GB. Running containers and unfinished runs are never touched.
#
# Settings: /etc/runner-cleanup.conf (written by setup.sh). Usage: sudo runner-cleanup [--dry-run]
set -u
CONF=/etc/runner-cleanup.conf
RUN_USER="${SUDO_USER:-$(id -un)}"; HOST_DRIVE=/mnt/c
MIN_HOST_FREE_GB=40; WARN_HOST_FREE_GB=60; MAX_ROOT_USED_PCT=80
PULLED_KEEP_HOURS=24; UNPULLED_KEEP_DAYS=7; IMAGE_KEEP_HOURS=72; RUN_DIRS="cg-runs tb-runs"
# projects whose run scripts write a PULLED marker after copying results home; in the others, finished runs are
# removed only in an emergency (their results may not be anywhere else)
MARKER_DIRS="cg-runs"
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
HOME_DIR=$(getent passwd "$RUN_USER" | cut -d: -f6); STATE_DIR="$HOME_DIR/.runner"; LOGF="$STATE_DIR/cleanup.log"
mkdir -p "$STATE_DIR"; chown "$RUN_USER" "$STATE_DIR" 2>/dev/null
# CG_RUNS_DIR (tests only) replaces the run-folder list with one folder
if [ -n "${CG_RUNS_DIR:-}" ]; then RUN_PATHS="$CG_RUNS_DIR"; else RUN_PATHS=""; for r in $RUN_DIRS; do RUN_PATHS="$RUN_PATHS $HOME_DIR/$r"; done; fi

do_() { if [ "$DRY" = 1 ]; then echo "would: $*"; else "$@" >/dev/null 2>&1; fi; }
host_free() { df -BG --output=avail "$HOST_DRIVE" 2>/dev/null | tail -1 | tr -dc '0-9'; }
root_used() { df --output=pcent / | tail -1 | tr -dc '0-9'; }
age_h() { echo $(( ( $(date +%s) - $(stat -c %Y "$1") ) / 3600 )); }

before_free=$(host_free); before_used=$(root_used)
mode=normal
if [ -n "$before_free" ] && [ "$before_free" -lt "$MIN_HOST_FREE_GB" ]; then mode=emergency; fi
[ "$before_used" -gt "$MAX_ROOT_USED_PCT" ] && mode=emergency
[ "$mode" = emergency ] && { do_ touch "$STATE_DIR/DISK_LOW"; do_ chown "$RUN_USER" "$STATE_DIR/DISK_LOW"; }

# --- Docker (stopped containers and unused objects only; running containers are never touched)
if command -v docker >/dev/null 2>&1; then
  do_ docker container prune -f --filter "until=6h"
  do_ docker image prune -f
  if [ "$mode" = emergency ]; then
    do_ docker image prune -a -f --filter "label!=cg.keep=1" --filter "label!=runner.keep=1"
    do_ docker builder prune -a -f
  else
    do_ docker image prune -a -f --filter "until=${IMAGE_KEEP_HOURS}h" --filter "label!=cg.keep=1" --filter "label!=runner.keep=1"
    do_ docker builder prune -f --filter "until=24h"
  fi
  do_ docker volume prune -f
  do_ docker network prune -f
fi

# --- run folders: ~/<project>-runs/<task>/<hash>/runs/<runid>/ (DONE = finished, PULLED = results are on VM 1)
removed=0
for RUNS in $RUN_PATHS; do
[ -d "$RUNS" ] || continue
marked=0; for m in $MARKER_DIRS; do [ "$(basename "$RUNS")" = "$m" ] && marked=1; done
[ -n "${CG_RUNS_MARKED:-}" ] && marked="$CG_RUNS_MARKED"      # tests only
for d in "$RUNS"/*/*/runs/*/; do
  [ -d "$d" ] || continue
  [ -f "$d/DONE" ] || continue                                  # unfinished: never touched
  if [ -f "$d/PULLED" ]; then
    if [ "$mode" = emergency ] || [ "$(age_h "$d/PULLED")" -ge "$PULLED_KEEP_HOURS" ]; then do_ rm -rf "$d"; removed=$((removed+1)); fi
  elif { [ "$marked" = 1 ] || [ "$mode" = emergency ]; } && [ "$(age_h "$d/DONE")" -ge $((UNPULLED_KEEP_DAYS * 24)) ]; then
    do_ rm -rf "$d"; removed=$((removed+1))
  fi
done
# empty task/hash folders left behind (keep the harbor/ copy only while a run of that hash still exists)
for h in "$RUNS"/*/*/; do
  [ -d "$h" ] || continue
  if [ -z "$(ls -A "$h/runs" 2>/dev/null)" ] && [ "$(age_h "$h")" -ge 24 ]; then do_ rm -rf "$h"; fi
done
done

# --- system caches and logs
do_ find /tmp -xdev -mindepth 1 -maxdepth 1 -mtime +3 -exec rm -rf {} +
command -v journalctl >/dev/null && do_ journalctl --vacuum-size=200M
command -v apt-get >/dev/null && do_ apt-get clean
[ -x "$HOME_DIR/.local/bin/uv" ] && do_ sudo -u "$RUN_USER" "$HOME_DIR/.local/bin/uv" cache prune
do_ fstrim -av                                                   # lets a sparse vhdx give space back to Windows

after_free=$(host_free); after_used=$(root_used)
if [ -f "$STATE_DIR/DISK_LOW" ] && [ -n "$after_free" ] && [ "$after_free" -ge "$WARN_HOST_FREE_GB" ] && [ "$after_used" -le "$MAX_ROOT_USED_PCT" ]; then
  do_ rm -f "$STATE_DIR/DISK_LOW"
fi
line="$(date -u +%FT%TZ) $mode: windows drive ${HOST_DRIVE} free ${before_free:-?}G -> ${after_free:-?}G, / used ${before_used}% -> ${after_used}%, runs removed $removed$([ -f "$STATE_DIR/DISK_LOW" ] && echo ', DISK_LOW set')"
if [ "$DRY" = 1 ]; then echo "$line (dry run)"; else
  echo "$line" >>"$LOGF"; tail -n 500 "$LOGF" >"$LOGF.tmp" && mv "$LOGF.tmp" "$LOGF"; chown "$RUN_USER" "$LOGF" 2>/dev/null; fi
