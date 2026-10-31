#!/usr/bin/env bash
# update.sh — cập nhật bot trên VPS sau khi bạn push code mới lên GitHub.
#   sudo bash /opt/owo-tracker/deploy/update.sh
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/owo-tracker}
APP_USER=${APP_USER:-owo}

[ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng root: sudo bash $0" >&2; exit 1; }

echo "==> Kéo code mới"
runuser -u "$APP_USER" -- env HOME="$APP_DIR" git -C "$APP_DIR" pull --ff-only
echo "==> Cập nhật thư viện"
runuser -u "$APP_USER" -- env HOME="$APP_DIR" "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements.txt"
echo "==> Khởi động lại bot"
systemctl restart owo-tracker
sleep 4
systemctl --no-pager --lines=15 status owo-tracker || true
