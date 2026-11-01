"""test_security.py — khoá lệnh theo chủ bot, escape regex, chống dò token API.
Chạy: python test_security.py"""
import re, sys, time
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

src = open("owo_tracker_bot.py", encoding="utf-8").read().split("\n")

# 1) Mọi lệnh phải có @is_owner()/@is_owner_or_alt(), trừ vài lệnh vô hại (ping/help) và captcha (tự kiểm tra bên trong)
OPEN_OK = {"ping", "help", "captcha"}
unguarded = []
for i, line in enumerate(src):
    m = re.match(r'@bot\.command\(name="([^"]+)"', line)
    if not m or m.group(1) in OPEN_OK:
        continue
    near = src[max(0, i - 3):i + 4]
    if not any(re.match(r"\s*@(is_owner|is_owner_or_alt)\(\)", x) for x in near):
        unguarded.append(m.group(1))
check("mọi lệnh (trừ ping/help/captcha) chỉ chủ bot dùng được", unguarded, [])

# 2) Không còn $regex nhét thẳng chuỗi người gõ
raw = [i + 1 for i, line in enumerate(src) if '"$regex": search' in line]
check("không còn $regex dùng chuỗi tìm kiếm chưa escape", raw, [])

# 3) Chống dò token
b.AUTOMACRO_API_TOKEN = "t" * 32
b._auth_failures.clear()
def req(token, ip="1.2.3.4", fwd=None):
    h = {"Authorization": f"Bearer {token}"}
    if fwd: h["X-Forwarded-For"] = fwd
    return NS(headers=h, remote=ip)

check("token đúng -> qua", b._check_api_token(req("t" * 32)), True)
for _ in range(b.AUTH_FAIL_LIMIT):
    b._check_api_token(req("sai"))
check("sai quá nhiều lần -> bị khoá", b._auth_locked("1.2.3.4"), True)
check("bị khoá thì token đúng cũng bị từ chối", b._check_api_token(req("t" * 32)), False)
check("IP khác không bị ảnh hưởng", b._check_api_token(req("t" * 32, ip="9.9.9.9")), True)
check("hết cửa sổ thời gian thì mở khoá",
      b._auth_locked("1.2.3.4", now=time.time() + b.AUTH_FAIL_WINDOW + 1), False)
check("sau Caddy (127.0.0.1) lấy IP thật từ X-Forwarded-For",
      b._client_ip(req("x", ip="127.0.0.1", fwd="5.6.7.8, 127.0.0.1")), "5.6.7.8")
check("gọi trực tiếp thì bỏ qua X-Forwarded-For giả",
      b._client_ip(req("x", ip="8.8.8.8", fwd="5.6.7.8")), "8.8.8.8")
b._auth_failures.clear()

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test security pass.")
