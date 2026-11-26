#!/usr/bin/env bash
# Turnkey deploy of the whole RakB stack (Telegram bot + headless SA-MP client)
# onto a fresh Ubuntu/Debian VPS with open outbound UDP — e.g. Oracle Always Free.
# No tunnel needed here: UDP egress is open, so /connect works directly.
#
# Usage:
#   sudo bash deploy-vps.sh <BOT_TOKEN> <ADMIN_IDS> [branch]
# Example:
#   sudo bash deploy-vps.sh "123456:ABC..." "123456789"
#
# Only SSH (22) inbound is required; the bot uses Telegram long polling and the
# SA-MP client dials out over UDP, so no extra inbound ports need opening.
set -euo pipefail

BOT_TOKEN="${1:-}"
ADMIN_IDS="${2:-}"
BRANCH="${3:-arena/3b12d5df-rakb}"
REPO="https://github.com/WeteroScript/Rakb.git"

if [[ -z "$BOT_TOKEN" || -z "$ADMIN_IDS" ]]; then
  echo "usage: sudo bash deploy-vps.sh <BOT_TOKEN> <ADMIN_IDS> [branch]" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "run as root: sudo bash deploy-vps.sh ..." >&2
  exit 1
fi

echo "==> [1/5] swap (2 GB) so the C++ build fits a 1 GB micro instance"
if ! swapon --show | grep -q '/swapfile'; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "==> [2/5] prerequisites + Docker"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl git
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "==> [3/5] source (branch $BRANCH)"
if [[ -d /opt/rakb/.git ]]; then
  git -C /opt/rakb fetch origin "$BRANCH"
  git -C /opt/rakb checkout "$BRANCH"
  git -C /opt/rakb reset --hard "origin/$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO" /opt/rakb
fi

echo "==> [4/5] docker build (a few minutes on a micro instance)"
docker build -t rakb /opt/rakb

echo "==> [5/5] run"
docker rm -f rakb >/dev/null 2>&1 || true
docker run -d --name rakb --restart unless-stopped \
  -e BOT_TOKEN="$BOT_TOKEN" \
  -e ADMIN_IDS="$ADMIN_IDS" \
  -e AUTOSTART=1 \
  -v rakb-data:/app/data \
  rakb

echo
echo "deployed. follow logs:  docker logs -f rakb"
echo "expect:  health on 0.0.0.0:8080 | admins=... | bin=/opt/rakb/bin/raksamp"
echo "then in Telegram:  /nettest  (should be green)  and  /connect <ip> <port> <nick>"
