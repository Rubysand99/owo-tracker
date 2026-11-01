"""test_help.py — `,help` luôn khớp với các lệnh thật của bot.
QUY ƯỚC: thêm / đổi / xóa lệnh nào thì sửa HELP_GROUPS (trong owo_tracker_bot.py) cho khớp; test này báo lỗi nếu quên.
Chạy: python test_help.py"""
import re, sys
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

# Đọc tên lệnh thẳng từ mã nguồn nên chạy được cả khi không có discord.py thật.
src = open("owo_tracker_bot.py", encoding="utf-8").read()
commands_in_code = set(re.findall(r'@bot\.command\(name="([^"]+)"', src))
check("mọi lệnh đều khai báo bằng @bot.command(name=\"...\") (để test này thấy hết)",
      re.findall(r"@bot\.command\(\s*\)", src), [])

in_help = [name for _, items in b.HELP_GROUPS for name, _ in items]
check("help: không có lệnh nào ghi 2 lần", sorted({n for n in in_help if in_help.count(n) > 1}), [])
check("help: mọi lệnh của bot đều có mô tả trong ,help", sorted(commands_in_code - set(in_help)), [])
check("help: không nhắc lệnh đã bị xóa", sorted(set(in_help) - commands_in_code), [])
check("help: chữ hiện ra của mỗi lệnh bắt đầu bằng `,tênlệnh",
      sorted(n for _, items in b.HELP_GROUPS for n, txt in items if not txt.startswith(f"`,{n}")), [])
check("help: mỗi nhóm vừa 1 field embed (<= 1024 ký tự)",
      [t for t, items in b.HELP_GROUPS if len(" · ".join(txt for _, txt in items)) > 1024], [])
check("help: có lệnh mới của bản này (gemtier, setserver, autocheck, hbalert)",
      sorted({"gemtier", "setserver", "autocheck", "hbalert"} - set(in_help)), [])

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test ,help pass.")
