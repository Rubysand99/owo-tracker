"""test_version.py — số phiên bản của bot (file VERSION do GitHub Actions tự tăng sau mỗi lần cập nhật lên main).
Chạy: python test_version.py"""
import os, re, sys, tempfile
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

here = os.path.dirname(os.path.abspath(b.__file__))
raw = open(os.path.join(here, "VERSION"), encoding="utf-8").read().strip()
check("file VERSION có dạng số.số (vd 1.12)", bool(re.fullmatch(r"\d+\.\d+", raw)), True)
check("bot đọc đúng file VERSION", b.BOT_VERSION, raw)
check("bot_version_text bắt đầu bằng v + số", b.bot_version_text().startswith(f"v{raw}"), True)

with tempfile.TemporaryDirectory() as d:
    check("thiếu file VERSION -> '?' (không làm bot hỏng)", b._read_version(d), "?")
    open(os.path.join(d, "VERSION"), "w").write("  2.7\n")
    check("đọc VERSION, bỏ khoảng trắng/xuống dòng", b._read_version(d), "2.7")
    open(os.path.join(d, "VERSION"), "w").write("\n")
    check("VERSION rỗng -> '?'", b._read_version(d), "?")
    check("thư mục không phải repo git -> không có mã commit", b._read_git_sha(d), "")

b.BOT_COMMIT = "abc1234"
check("hiện kèm mã commit khi có", b.bot_version_text(), f"v{b.BOT_VERSION} (abc1234)")
b.BOT_COMMIT = ""
check("không có mã commit thì chỉ hiện số", b.bot_version_text(), f"v{b.BOT_VERSION}")

# Workflow tăng version: công thức tăng giống hệt bash trong .github/workflows/version.yml
def bump(cur):
    if not re.fullmatch(r"\d+\.\d+", cur or ""):
        cur = "1.0"
    major, minor = cur.split(".")
    return f"{major}.{int(minor) + 1}"
check("tăng: 1.0 -> 1.1", bump("1.0"), "1.1")
check("tăng: 1.9 -> 1.10 (không phải số thập phân)", bump("1.9"), "1.10")
check("tăng: đổi số lớn 2.0 -> 2.1", bump("2.0"), "2.1")
check("tăng: file hỏng -> bắt đầu lại từ 1.1", bump("abc"), "1.1")
wf = open(os.path.join(here, ".github", "workflows", "version.yml"), encoding="utf-8").read()
check("workflow tăng version có chặn lặp vô hạn (bỏ qua commit chore(version))", "chore(version)" in wf, True)
check("workflow chỉ chạy khi test xanh", "conclusion == 'success'" in wf, True)

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test phiên bản pass.")
