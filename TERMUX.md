# Tạo & cập nhật repo từ Termux

Hướng dẫn làm mọi thứ ngay trên điện thoại — tạo repo GitHub, push
code, và cập nhật sau này — không cần máy tính.

## 1. Cài đặt lần đầu (chỉ làm 1 lần)

```bash
pkg update && pkg upgrade -y
pkg install git gh -y
```

Cấu hình git (tên/email nên khớp với tài khoản GitHub):

```bash
git config --global user.name "Tên bạn"
git config --global user.email "email@vidu.com"
```

Đăng nhập GitHub ngay trong Termux:

```bash
gh auth login
```

Chọn lần lượt: `GitHub.com` → `HTTPS` → `Login with a web browser` —
Termux sẽ hiện 1 mã, mở trình duyệt (Chrome trên điện thoại là được)
theo link nó đưa, dán mã vào, xác nhận. Xong bước này thì:

```bash
gh auth setup-git
```

Lệnh này để `git push` sau này dùng luôn xác thực của `gh`, không cần
nhập token thủ công mỗi lần.

## 2. Lấy file dự án vào Termux

Nếu bạn đã tải `owo-tracker.zip` về máy (thư mục Downloads):

```bash
termux-setup-storage
```

Android sẽ hỏi xác nhận quyền truy cập bộ nhớ — đồng ý, chỉ hỏi 1 lần
duy nhất. Sau đó:

```bash
cd ~
cp ~/storage/downloads/owo-tracker.zip .
unzip owo-tracker.zip
cd owo-tracker
```

## 3. Tạo repo GitHub mới — ngay từ Termux, không cần mở web

```bash
git init
git add .
git commit -m "Khoi tao owo-tracker bot"
git branch -M main

gh repo create owo-tracker --private --source=. --push
```

Bỏ `--private` nếu muốn repo public. Lệnh `gh repo create` sẽ tự tạo
repo trên GitHub, gắn làm remote `origin`, và `--push` đẩy luôn commit
vừa tạo lên — xong trong 1 lệnh.

Nếu bản `gh` bạn cài có cú pháp khác (CLI này thỉnh thoảng đổi flag
giữa các phiên bản), chạy `gh repo create --help` để xem đúng flag
hiện tại, hoặc làm thủ công:

```bash
gh repo create owo-tracker --private
git remote add origin https://github.com/<username>/owo-tracker.git
git push -u origin main
```

## 4. Cập nhật repo sau này (mỗi khi sửa code)

```bash
cd ~/owo-tracker
# sửa file bằng nano, ví dụ:
nano owo_tracker_bot.py
```

Sửa xong, lưu (`Ctrl+O` rồi Enter, `Ctrl+X` để thoát nano), rồi:

```bash
git add .
git commit -m "Mo ta ngan gon thay doi"
git push
```

Muốn xem lại đã đổi gì trước khi commit: `git status` hoặc `git diff`.

## 5. (Tuỳ chọn) Chạy luôn bot trên điện thoại qua Termux

```bash
pkg install python -y
pip install discord.py motor

export DISCORD_TOKEN="token_bot_cua_ban"
export OWNER_ID="discord_id_cua_ban"
export MONGODB_URI="mongodb+srv://..."
# export AUTOMACRO_API_TOKEN="..."   # tuỳ chọn — chỉ cần nếu muốn AutoMacro đọc lệnh

python owo_tracker_bot.py
```

### Giữ bot chạy khi tắt màn hình

Android sẽ tự kill tiến trình nền để tiết kiệm pin nếu không có wake
lock:

```bash
pkg install termux-api -y   # cần cài thêm app "Termux:API" từ F-Droid/Play Store
termux-wake-lock
```

### Giữ bot chạy kể cả khi đóng hẳn app Termux

Dùng `tmux` — phiên chạy nền độc lập với cửa sổ Termux đang mở:

```bash
pkg install tmux -y
tmux new -s owobot
python owo_tracker_bot.py
```

Bấm `Ctrl+B` rồi thả ra và bấm `D` để thoát ra ngoài mà bot vẫn chạy
ngầm. Quay lại xem log bất cứ lúc nào:

```bash
tmux attach -t owobot
```

Lưu ý: Android vẫn có thể kill Termux nếu hệ thống quá thiếu RAM hoặc
bạn "vuốt tắt" app khỏi danh sách gần đây — `tmux` + `termux-wake-lock`
giảm khả năng này nhiều nhưng không đảm bảo tuyệt đối 100%. Nếu cần độ
ổn định cao, chạy bot trên máy chủ/VPS luôn bật vẫn là lựa chọn chắc
chắn hơn về lâu dài.
