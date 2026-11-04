#!/usr/bin/env bash
# auto-update.sh — tự cập nhật owo-tracker khi có commit mới trên GitHub. Do systemd timer gọi (xem owo-tracker-update.timer),
# cũng chạy tay được:  sudo bash /opt/owo-tracker/deploy/auto-update.sh
#
# An toàn:
#   - chỉ fast-forward nhánh BRANCH (mặc định main); không bao giờ ép ghi đè / reset về nhánh khác
#   - kiểm tra cú pháp + test không cần mạng TRƯỚC khi khởi động lại; hỏng thì quay về commit cũ, KHÔNG restart
#   - sau khi restart mà bot không sống ổn định thì tự quay về commit cũ rồi restart lại
#   - commit đã bị loại sẽ không bị thử lại mỗi phút (nhớ trong STATE_DIR); có commit mới hơn thì thử lại
#   - có khóa (flock) nên 2 lần chạy chồng nhau không đạp lên nhau
#
# Biến môi trường (đều tùy chọn):
#   APP_DIR=/opt/owo-tracker  APP_USER=owo  SERVICE=owo-tracker  BRANCH=main  REMOTE=origin
#   STATE_DIR=/var/lib/owo-tracker-update   SETTLE_SECONDS=25 (chờ bot ổn định sau restart)   RUN_TESTS=1
set -uo pipefail

APP_DIR=${APP_DIR:-/opt/owo-tracker}
APP_USER=${APP_USER:-owo}
SERVICE=${SERVICE:-owo-tracker}
BRANCH=${BRANCH:-main}
REMOTE=${REMOTE:-origin}
STATE_DIR=${STATE_DIR:-/var/lib/owo-tracker-update}
SETTLE_SECONDS=${SETTLE_SECONDS:-25}
RUN_TESTS=${RUN_TESTS:-1}
# Chỗ chạy lệnh systemctl; để trống = dùng systemctl thật. (Dùng cho kiểm thử.)
SYSTEMCTL=${SYSTEMCTL:-systemctl}

log() { printf '[auto-update] %s\n' "$*"; command -v logger >/dev/null 2>&1 && logger -t owo-tracker-update -- "$*" || true; }

# Toàn bộ logic nằm trong hàm main và file kết thúc bằng `main; exit` — bash đọc hết file trước khi chạy, nên việc
# `git pull` ghi đè chính file này giữa chừng không làm script đang chạy bị hỏng.
as_app() { runuser -u "$APP_USER" -- env HOME="$APP_DIR" "$@"; }
git_app() { as_app git -C "$APP_DIR" "$@"; }

changed_since() { # $1=commit cũ  $2=commit mới  $3=đường dẫn
  ! git_app diff --quiet "$1" "$2" -- "$3" 2>/dev/null
}

pip_sync() {
  as_app "$APP_DIR/.venv/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements.txt"
}

# Kiểm tra bản code hiện đang nằm trên đĩa trước khi cho chạy. In lý do ra stdout nếu hỏng.
verify_tree() {
  local py="$APP_DIR/.venv/bin/python" f err
  for f in "$APP_DIR"/*.py; do
    case "$(basename "$f")" in test_*) continue ;; esac
    if ! err=$(as_app env PYTHONDONTWRITEBYTECODE=1 "$py" -c "import ast,sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" "$f" 2>&1); then
      echo "lỗi cú pháp trong $(basename "$f") ($(printf '%s' "$err" | tail -n 1))"
      return 1
    fi
  done
  if [ "$RUN_TESTS" = 1 ] && [ -f "$APP_DIR/test_security.py" ]; then
    # test_security.py chỉ dùng module có sẵn trong venv (không cần mạng / MongoDB)
    # Log o file tam do mktemp tao (0600) - KHONG dung duong dan co dinh trong /tmp (script chay bang root, de bi tro symlink ghi de file)
    local testlog; testlog="$(mktemp /var/log/owo-update-test.XXXXXX 2>/dev/null || mktemp)"
    ( cd "$APP_DIR" && as_app env PYTHONDONTWRITEBYTECODE=1 "$py" test_security.py ) >"$testlog" 2>&1 \
      || { echo "test_security.py không đạt (xem $testlog)"; return 1; }
    rm -f "$testlog"
  fi
  return 0
}

service_healthy() {
  "$SYSTEMCTL" is-active --quiet "$SERVICE" || return 1
  sleep "$SETTLE_SECONDS"
  "$SYSTEMCTL" is-active --quiet "$SERVICE"
}

mark_bad() { mkdir -p "$STATE_DIR" && printf '%s\n' "$1" > "$STATE_DIR/bad_commit"; }

rollback() { # $1=commit cũ  $2=lý do
  log "❌ $2 — quay về commit cũ ${1:0:8}"
  git_app reset --hard "$1" >/dev/null 2>&1 || log "⚠️ không reset được về ${1:0:8}"
}

main() {
  [ "$(id -u)" -eq 0 ] || { echo "Hãy chạy bằng root: sudo bash $0" >&2; return 1; }
  [ -d "$APP_DIR/.git" ] || { log "Không thấy repo ở $APP_DIR"; return 1; }
  mkdir -p "$STATE_DIR"

  exec 9>"$STATE_DIR/lock"
  flock -n 9 || { log "Đang có lần cập nhật khác chạy — bỏ qua"; return 0; }

  # Không đụng vào repo nếu bạn đã sửa tay file đang được git theo dõi (tránh mất chỉnh sửa)
  if [ -n "$(git_app status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    log "⚠️ Repo có file đã sửa tay chưa commit — không tự cập nhật. Xem: git -C $APP_DIR status"
    return 0
  fi

  git_app fetch --quiet "$REMOTE" "$BRANCH" 2>/dev/null || { log "Không fetch được GitHub (mạng?) — thử lại lần sau"; return 0; }

  local old new
  old=$(git_app rev-parse HEAD)
  new=$(git_app rev-parse "$REMOTE/$BRANCH" 2>/dev/null) || { log "Không có nhánh $REMOTE/$BRANCH"; return 1; }
  [ "$old" = "$new" ] && return 0

  if [ -f "$STATE_DIR/bad_commit" ] && [ "$(cat "$STATE_DIR/bad_commit")" = "$new" ]; then
    return 0   # commit này đã từng bị loại; đợi commit mới hơn
  fi

  # Chỉ tiến lên (fast-forward). Lịch sử bị viết lại / nhánh lệch thì dừng và báo, không tự xử lý.
  if ! git_app merge-base --is-ancestor "$old" "$new"; then
    log "⚠️ $REMOTE/$BRANCH không phải bản tiến lên từ ${old:0:8} (lịch sử bị viết lại?) — không tự cập nhật"
    mark_bad "$new"
    return 0
  fi

  log "Có commit mới: ${old:0:8} → ${new:0:8}"
  git_app merge --ff-only --quiet "$new" || { log "❌ merge --ff-only thất bại"; return 1; }

  local reqs_changed=0
  if changed_since "$old" "$new" requirements.txt; then
    reqs_changed=1
    log "requirements.txt đổi — cài lại thư viện"
    if ! pip_sync; then
      rollback "$old" "cài thư viện thất bại"
      pip_sync || true
      mark_bad "$new"
      return 1
    fi
  fi

  local why
  if ! why=$(verify_tree); then
    rollback "$old" "kiểm tra trước khi chạy không đạt: $why"
    [ "$reqs_changed" = 1 ] && { pip_sync || true; }
    mark_bad "$new"
    return 1
  fi

  log "Khởi động lại $SERVICE"
  "$SYSTEMCTL" restart "$SERVICE"
  if service_healthy; then
    rm -f "$STATE_DIR/bad_commit"
    log "✅ Cập nhật xong, bot đang chạy ở ${new:0:8}"
    return 0
  fi

  rollback "$old" "bot không chạy ổn định sau khi cập nhật"
  [ "$reqs_changed" = 1 ] && { pip_sync || true; }
  "$SYSTEMCTL" restart "$SERVICE" || true
  mark_bad "$new"
  if "$SYSTEMCTL" is-active --quiet "$SERVICE"; then
    log "↩️ Đã quay về ${old:0:8} và bot chạy lại bình thường. Xem lỗi: journalctl -u $SERVICE -n 80"
  else
    log "🚨 Đã quay về ${old:0:8} nhưng bot vẫn không chạy — kiểm tra ngay: journalctl -u $SERVICE -n 80"
  fi
  return 1
}

main "$@"
exit $?
