# Chạy owo-tracker trên VPS

Hướng dẫn chuyển bot từ Railway/Termux sang VPS Ubuntu/Debian. Làm theo thứ tự, khoảng 15–20 phút.

## Bạn cần chuẩn bị

| Thứ | Ghi chú |
|---|---|
| **VPS** Ubuntu 22.04 hoặc 24.04 | 1 vCPU, 1 GB RAM là đủ. Cần đăng nhập được bằng SSH (root hoặc sudo). |
| **Domain** trỏ về IP của VPS | App Android **bắt buộc `https://`**, mà HTTPS cần domain. Chưa có thì dùng subdomain miễn phí của [DuckDNS](https://www.duckdns.org) (xem bước 2). |
| **MongoDB** | Giữ nguyên chuỗi `MONGODB_URI` đang dùng ở Railway (Atlas) → **không phải chuyển dữ liệu**, dữ liệu nằm ở MongoDB chứ không nằm ở Railway. |
| 5 giá trị từ Railway | Mở dịch vụ → tab **Variables** và chép lại: `DISCORD_TOKEN`, `OWNER_ID`, `MONGODB_URI`, `MONGODB_DB_NAME` (nếu có), `AUTOMACRO_API_TOKEN` (nếu có). |

> ⚠️ **Chỉ chạy MỘT bản bot.** Hai bản cùng token sẽ cùng xử lý mỗi tin OwO (ghi đôi dữ liệu, trả lời đôi, giành việc của nhau).
> Hãy tắt bản trên Railway (và Termux nếu đang chạy) **trước khi** bật bản VPS (bước 4).

## 1. Đẩy thư mục `deploy/` lên GitHub

Script cài đặt nằm trong repo nên phải push lên trước (bạn đã làm nếu đọc được file này trên GitHub).

## 2. Trỏ domain về VPS

- Có domain riêng: tạo bản ghi **A** `bot.tenmiencuaban.com` → IP của VPS.
- Dùng DuckDNS: đăng nhập, tạo subdomain (vd `owo-ruby`), điền IP VPS vào ô *current ip*, bấm *update ip*.
  Domain của bạn sẽ là `owo-ruby.duckdns.org`.

Kiểm tra (đợi vài phút nếu chưa ra): `ping owo-ruby.duckdns.org` phải ra đúng IP VPS.

## 3. Cài đặt bằng một lệnh

Đăng nhập VPS rồi chạy (thay domain của bạn):

```bash
curl -fsSL https://raw.githubusercontent.com/Rubysand99/owo-tracker/main/deploy/setup-vps.sh -o setup-vps.sh
sudo DOMAIN=owo-ruby.duckdns.org bash setup-vps.sh
```

Script sẽ: cài Python + git, tạo người dùng riêng `owo`, tải code về `/opt/owo-tracker`, cài thư viện trong venv, tạo
dịch vụ systemd `owo-tracker`, cài **Caddy** (tự xin chứng chỉ HTTPS), và bật tường lửa chỉ mở SSH + 80 + 443.
Cuối cùng nó in ra **token API** đã sinh sẵn — chép lại để nhập vào app. Chạy lại script bao nhiêu lần cũng an toàn
(không ghi đè file cấu hình).

> Đang dùng cổng SSH khác 22? Script tự dò; nếu cần chỉ định: `sudo SSH_PORT=2222 DOMAIN=... bash setup-vps.sh`.

## 4. Chuyển bot sang VPS

1. **Tắt bot trên Railway** (và đóng bot trên Termux nếu đang chạy).
2. Điền cấu hình trên VPS:
   ```bash
   sudo nano /etc/owo-tracker.env
   ```
   Thay các chỗ `CHANGE_ME` bằng `DISCORD_TOKEN`, `OWNER_ID`, `MONGODB_URI` lấy từ Railway. Nếu Railway đang dùng
   `AUTOMACRO_API_TOKEN` riêng và bạn muốn giữ, dán vào dòng `AUTOMACRO_API_TOKEN=` (để app không phải đổi token).
   Quy tắc: `KEY=giá trị`, không dấu cách quanh `=`, không bọc dấu nháy, không viết chú thích cùng dòng.
3. Khởi động và xem log:
   ```bash
   sudo systemctl restart owo-tracker
   journalctl -u owo-tracker -f        # Ctrl+C để thoát; phải thấy dòng "API cho AutoMacro dang chay o 127.0.0.1:8080"
   ```

## 5. Kiểm tra

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://owo-ruby.duckdns.org/alerts
```

- `401` → **đúng** (HTTPS chạy, bot chạy, chỉ là chưa gửi token).
- `502` → Caddy chạy nhưng bot chưa lên: xem `journalctl -u owo-tracker -n 50`.
- Lỗi chứng chỉ / không kết nối → xem mục *Sự cố* bên dưới.

Trong Discord gõ `,status` xem bot đã nhận lệnh chưa.

## 6. Trỏ app sang VPS

Star Hub → **Cài đặt** → *Địa chỉ API* = `https://owo-ruby.duckdns.org` (đủ `https://`, không có dấu `/` ở cuối),
*Token* = giá trị `AUTOMACRO_API_TOKEN` trong `/etc/owo-tracker.env` → **Lưu**.

## Vận hành hằng ngày

| Việc | Lệnh |
|---|---|
| Xem log trực tiếp | `journalctl -u owo-tracker -f` |
| Trạng thái | `systemctl status owo-tracker` |
| Khởi động lại / dừng / bật | `sudo systemctl restart owo-tracker` · `stop` · `start` |
| Cập nhật code ngay (không đợi timer) | `sudo bash /opt/owo-tracker/deploy/auto-update.sh` (hoặc `update.sh`) |
| Xem lịch sử tự cập nhật | `journalctl -t owo-tracker-update -n 30` |
| Tạm tắt / bật tự cập nhật | `sudo systemctl disable --now owo-tracker-update.timer` · `sudo systemctl enable --now owo-tracker-update.timer` |
| Sửa cấu hình rồi áp dụng | `sudo nano /etc/owo-tracker.env` → `sudo systemctl restart owo-tracker` |

Bot tự chạy lại khi VPS khởi động lại và tự khởi động lại nếu bị lỗi (chờ 5 giây). Quy trình làm việc: sửa code → push/merge
vào `main` trên GitHub → trong vòng ~3 phút VPS tự kéo code và khởi động lại bot.

## Tự cập nhật khi có commit mới

`setup-vps.sh` cài sẵn một `systemd timer` (`owo-tracker-update.timer`, mỗi ~3 phút) chạy `deploy/auto-update.sh`.
VPS đã cài từ trước: chạy lại `sudo bash /opt/owo-tracker/deploy/setup-vps.sh` (an toàn, không ghi đè cấu hình) để bật.
Không muốn tự cập nhật: `sudo AUTO_UPDATE=0 bash setup-vps.sh`.

Cách hoạt động, theo thứ tự:

1. `git fetch` nhánh `main`. Không có commit mới thì thoát, không làm gì cả. Repo public nên VPS **không cần khóa hay token GitHub**
   và **không mở thêm cổng nào**.
2. Chỉ **fast-forward**. Nếu bạn đã sửa tay file trong `/opt/owo-tracker`, hoặc lịch sử `main` bị viết lại, script dừng và
   ghi cảnh báo thay vì ghi đè.
3. Cài lại thư viện nếu `requirements.txt` đổi.
4. Kiểm tra cú pháp mọi file `.py` và chạy `test_security.py` (không cần mạng). **Hỏng thì quay về commit cũ và không restart.**
5. Restart bot, đợi ~25 giây. Nếu bot không còn chạy thì **tự quay về commit cũ** và restart lại.
6. Commit đã bị loại không bị thử lại mỗi 3 phút; khi có commit mới hơn thì thử lại.

Lưu ý: commit nào vào `main` là bot chạy bản đó. Nên bật *branch protection* cho `main` (bắt buộc PR + CI xanh), và chỉ merge
sau khi xem diff. Script giảm rủi ro nhưng không thay thế được việc review; test tự động chỉ bắt được lỗi cú pháp và các
kiểm tra bảo mật, không bắt được lỗi logic.

## Bảo mật

- File `/etc/owo-tracker.env` chứa token và chỉ root đọc được. Đừng gửi cho ai, đừng commit.
- API chỉ lắng nghe `127.0.0.1`; chỉ Caddy (HTTPS) ra ngoài. Đừng mở cổng 8080 trên tường lửa của nhà cung cấp VPS.
- Dùng **khóa SSH** thay mật khẩu. Sau khi đã đăng nhập thử bằng khóa thành công, mới tắt mật khẩu:
  `PasswordAuthentication no` trong `/etc/ssh/sshd_config` rồi `sudo systemctl reload ssh`.
- Cập nhật hệ thống thỉnh thoảng: `sudo apt update && sudo apt upgrade -y`.
- MongoDB Atlas gói miễn phí thường **không có sao lưu tự động**; nếu dữ liệu quan trọng, thỉnh thoảng tự xuất bản sao.

## Sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| Caddy không lấy được chứng chỉ | Domain chưa trỏ đúng IP, hoặc cổng 80/443 bị chặn (kiểm tra cả tường lửa của nhà cung cấp VPS, không chỉ `ufw`). Xem `journalctl -u caddy -n 50`. |
| `Thiếu biến môi trường ...` trong log | Còn thiếu `DISCORD_TOKEN` hoặc `MONGODB_URI` trong `/etc/owo-tracker.env`. |
| `Improper token` | Sai `DISCORD_TOKEN` (phải là token của **bot**, không phải của tài khoản). |
| Bot chạy nhưng không đọc được lệnh | Bật *Message Content Intent* trong Discord Developer Portal; kiểm tra `,setserver here`. |
| App báo lỗi `http://` / 401 | Địa chỉ phải là `https://domain`; token trong app phải khớp `AUTOMACRO_API_TOKEN`. |
| Mọi thứ bị ghi đôi / bot trả lời hai lần | Vẫn còn một bản bot chạy ở Railway hoặc Termux. Tắt đi. |
| Dịch vụ dừng sau vài lần lỗi liên tiếp | Sửa cấu hình rồi `sudo systemctl reset-failed owo-tracker && sudo systemctl start owo-tracker`. |

## Không muốn dùng script?

Các file mẫu nằm cạnh file này: `owo-tracker.service` (systemd), `owo-tracker.env.example` (cấu hình), `Caddyfile.example`.
Có thể dùng nginx thay Caddy: chỉ cần proxy HTTPS về `127.0.0.1:8080`. Cài với `SKIP_CADDY=1` nếu bạn tự lo HTTPS,
nhớ đổi `AUTOMACRO_API_HOST` cho phù hợp.
