#!/usr/bin/env bash
# Run INSIDE a proot-distro Ubuntu session on Termux (Android, ARM64).
# Builds the ARM client and starts the Telegram bot. The phone's residential /
# mobile IP is the same one you join SA-MP with, so game servers accept it.
#
# Usage (inside `proot-distro login ubuntu`):
#   bash termux-setup.sh <BOT_TOKEN> <ADMIN_IDS> [branch]
set -euo pipefail

BOT_TOKEN="${1:-}"
ADMIN_IDS="${2:-}"
BRANCH="${3:-arena/3b12d5df-rakb}"
REPO="https://github.com/WeteroScript/Rakb.git"

if [[ -z "$BOT_TOKEN" || -z "$ADMIN_IDS" ]]; then
  echo "usage: bash termux-setup.sh <BOT_TOKEN> <ADMIN_IDS> [branch]" >&2
  exit 1
fi

echo "==> [1/4] build + runtime deps"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y g++ cmake make python3 python3-pip python3-venv git ca-certificates

echo "==> [2/4] source (branch $BRANCH)"
cd /root
if [[ -d Rakb/.git ]]; then
  git -C Rakb fetch origin "$BRANCH"
  git -C Rakb checkout "$BRANCH"
  git -C Rakb reset --hard "origin/$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO" Rakb
fi
cd Rakb

echo "==> [3/4] build ARM client + python env"
cmake -S rakfk -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j2
python3 -m venv /root/rakb-venv
/root/rakb-venv/bin/pip install --no-cache-dir "aiogram==3.15.0" "aiohttp>=3.9,<4"

echo "==> [4/4] start bot (Ctrl+C to stop; keep Termux open + wakelock)"
exec env BOT_TOKEN="$BOT_TOKEN" ADMIN_IDS="$ADMIN_IDS" AUTOSTART=1 \
  RAKSAMP_BIN=/root/Rakb/build/bin/raksamp DATA_DIR=/root/rakb-data PORT=8080 \
  /root/rakb-venv/bin/python -m tgbot
