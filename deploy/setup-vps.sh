#!/usr/bin/env bash
# setup-vps.sh — cài owo-tracker lên VPS Ubuntu/Debian. Chạy bằng root; chạy lại nhiều lần vẫn an toàn
# (không ghi đè file cấu hình đã có).
#
#   sudo DOMAIN=bot.example.com bash setup-vps.sh
#
# Biến tùy chọn:
#   DOMAIN      domain đã trỏ về VPS -> cài Caddy để có HTTPS (app Android bắt buộc https://)
#   REPO_URL    mặc định https://github.com/Rubysand99/owo-tracker.git
#   APP_DIR     mặc định /opt/owo-tracker        APP_USER  mặc định owo
#   ENV_FILE    mặc định /etc/owo-tracker.env    API_PORT  mặc định 8080
#   SSH_PORT    cổng SSH để mở trên tường lửa (tự dò, mặc định 22)
#   SKIP_APT=1 SKIP_CADDY=1 SKIP_UFW=1 SKIP_SYSTEMD=1   bỏ qua từng bước tương ứng
set -euo pipefail

REPO_URL=${REPO_URL:-https://github.com/Rubysand99/owo-tracker.git}
APP_DIR=${APP_DIR:-/opt/owo-tracker}
APP_USER=${APP_USER:-owo}
ENV_FILE=${ENV_FILE:-/etc/owo-tracker.env}
SERVICE_FILE=${SERVICE_FILE:-/etc/systemd/system/owo-tracker.service}
CADDYFILE=${CADDYFILE:-/etc/caddy/Caddyfile}
DOMAIN=${DOMAIN:-}
API_PORT=${API_PORT:-8080}
SKIP_APT=${SKIP_APT:-0}
SKIP_CADDY=${SKIP_CADDY:-0}
SKIP_UFW=${SKIP_UFW:-0}
SKIP_SYSTEMD=${SKIP_SYSTEMD:-0}

log()  { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mLưu ý: %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mLỗi: %s\033[0m\n' "$*" >&2; exit 1; }
# Chạy lệnh dưới quyền người dùng của bot, HOME = thư mục ứng dụng (tránh pip/git báo lỗi cache của root)
as_app() { runuser -u "$APP_USER" -- env HOME="$APP_DIR" "$@"; }

[ "$(id -u)" -eq 0 ] || die "Hãy chạy bằng root: sudo bash $0"

USE_CADDY=0
if [ -n "$DOMAIN" ] && [ "$SKIP_CADDY" != 1 ]; then USE_CADDY=1; fi
if [ -z "$DOMAIN" ]; then
  warn "Chưa đặt DOMAIN nên sẽ KHÔNG có HTTPS: app Android không kết nối được qua http://. Chạy lại với DOMAIN=... sau."
fi

# ---------------------------------------------------------------- gói hệ thống
if [ "$SKIP_APT" != 1 ]; then
  log "Cài gói hệ thống"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y git python3 python3-venv python3-pip curl ca-certificates openssl
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || die "Cần Python 3.8 trở lên (khuyên dùng 3.10+)."

# ---------------------------------------------------------------- người dùng + mã nguồn
log "Tạo người dùng '$APP_USER' và lấy mã nguồn về $APP_DIR"
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  as_app git -C "$APP_DIR" pull --ff-only
else
  as_app git clone "$REPO_URL" "$APP_DIR"
fi

log "Cài thư viện Python (venv)"
as_app python3 -m venv "$APP_DIR/.venv"
as_app "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir --upgrade pip
as_app "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements.txt"

# ---------------------------------------------------------------- file cấu hình
NEW_ENV=0
API_TOKEN=""
if [ ! -f "$ENV_FILE" ]; then
  log "Tạo file cấu hình $ENV_FILE"
  API_TOKEN=$(openssl rand -hex 24)
  API_HOST=127.0.0.1
  if [ "$USE_CADDY" != 1 ]; then API_HOST=0.0.0.0; fi
  install -d "$(dirname "$ENV_FILE")"
  sed -e "s|@API_TOKEN@|$API_TOKEN|" -e "s|@API_HOST@|$API_HOST|" -e "s|@API_PORT@|$API_PORT|" \
      "$APP_DIR/deploy/owo-tracker.env.example" > "$ENV_FILE"
  chown root:root "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  NEW_ENV=1
else
  log "Giữ nguyên file cấu hình đã có $ENV_FILE"
fi

# ---------------------------------------------------------------- systemd
log "Cài dịch vụ systemd"
sed -e "s|@APP_DIR@|$APP_DIR|g" -e "s|@APP_USER@|$APP_USER|g" -e "s|@ENV_FILE@|$ENV_FILE|g" \
    "$APP_DIR/deploy/owo-tracker.service" > "$SERVICE_FILE"
STARTED=0
if [ "$SKIP_SYSTEMD" != 1 ]; then
  systemctl daemon-reload
  systemctl enable owo-tracker >/dev/null
  if grep -q 'CHANGE_ME' "$ENV_FILE"; then
    warn "$ENV_FILE còn giá trị CHANGE_ME nên CHƯA khởi động bot."
  else
    systemctl restart owo-tracker
    STARTED=1
  fi
fi

# ---------------------------------------------------------------- Caddy (HTTPS)
if [ "$USE_CADDY" = 1 ]; then
  log "Cài Caddy và cấu hình HTTPS cho $DOMAIN"
  if ! command -v caddy >/dev/null 2>&1; then
    apt-get install -y debian-keyring debian-archive-keyring apt-transport-https gnupg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
  fi
  NEW_CADDY=$(printf '# owo-tracker (do setup-vps.sh tạo)\n%s {\n\tencode gzip\n\treverse_proxy 127.0.0.1:%s\n}\n' "$DOMAIN" "$API_PORT")
  if [ -f "$CADDYFILE" ] && ! grep -q '^# owo-tracker' "$CADDYFILE"; then
    cp "$CADDYFILE" "$CADDYFILE.bak.$(date +%s)"
    warn "Đã sao lưu Caddyfile cũ thành $CADDYFILE.bak.*"
  fi
  printf '%s\n' "$NEW_CADDY" > "$CADDYFILE"
  systemctl enable caddy >/dev/null
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
fi

# ---------------------------------------------------------------- tường lửa
if [ "$SKIP_UFW" != 1 ]; then
  log "Cấu hình tường lửa (ufw)"
  [ "$SKIP_APT" = 1 ] || apt-get install -y ufw
  if [ -z "${SSH_PORT:-}" ]; then
    # Không có sshd / không đọc được cấu hình thì rơi về 22 (|| true: tránh set -e làm script chết)
    SSH_PORT=$(sshd -T 2>/dev/null | awk '/^port /{print $2; exit}' || true)
  fi
  SSH_PORT=${SSH_PORT:-22}
  ufw allow "${SSH_PORT}/tcp" >/dev/null
  if [ "$USE_CADDY" = 1 ]; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
  fi
  ufw --force enable >/dev/null
  echo "Đã mở: SSH ${SSH_PORT}$( [ "$USE_CADDY" = 1 ] && echo ', 80, 443')"
fi

# ---------------------------------------------------------------- tóm tắt
log "Xong"
if [ "$NEW_ENV" = 1 ]; then
  echo "Token API cho app AutoMacro (đã sinh sẵn, cũng nằm trong $ENV_FILE):"
  echo "    $API_TOKEN"
fi
if [ "$STARTED" = 1 ]; then
  echo "Bot đã chạy. Xem log:  journalctl -u owo-tracker -f"
else
  echo "Việc tiếp theo:"
  echo "  1) nano $ENV_FILE      (điền DISCORD_TOKEN, OWNER_ID, MONGODB_URI)"
  echo "  2) systemctl restart owo-tracker"
  echo "  3) journalctl -u owo-tracker -f"
fi
if [ -n "$DOMAIN" ]; then
  echo "Địa chỉ API để nhập vào app:  https://$DOMAIN"
fi
