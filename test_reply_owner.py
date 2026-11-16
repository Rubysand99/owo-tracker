"""test_reply_owner.py — nhận diện chủ tin OwO qua reply (kể cả khi tin gốc chưa có trong cache) và lệnh slash.
Chạy: python test_reply_owner.py"""
import sys, types, asyncio
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

ns = types.SimpleNamespace

def msg(ref=None, fetch_author=None, inter_user=None, fetch_raises=False):
    async def fetch_message(mid):
        if fetch_raises:
            raise RuntimeError("not found")
        return ns(author=ns(id=fetch_author))
    m = ns(reference=ref, channel=ns(fetch_message=fetch_message))
    if inter_user is not None:
        m.interaction_metadata = ns(user=ns(id=inter_user))
    return m

def run(coro):
    return asyncio.run(coro)

# tin gốc có trong cache -> không cần tải
check("cache có sẵn: của bạn", run(b.resolve_reply_target(msg(ns(resolved=ns(author=ns(id=5)), message_id=1)), "5")), "ban")
check("cache có sẵn: người khác", run(b.resolve_reply_target(msg(ns(resolved=ns(author=ns(id=9)), message_id=1)), "5")), "nguoi_khac")

# tin gốc KHÔNG có trong cache -> tải theo message_id
b._ref_author_cache.clear()
check("tải tin gốc: của bạn", run(b.resolve_reply_target(msg(ns(resolved=None, message_id=11), fetch_author=5), "5")), "ban")
check("tải tin gốc: người khác", run(b.resolve_reply_target(msg(ns(resolved=None, message_id=12), fetch_author=9), "5")), "nguoi_khac")
check("tải tin gốc lỗi -> khong_co (giữ hành vi cũ)", run(b.resolve_reply_target(msg(ns(resolved=None, message_id=13), fetch_raises=True), "5")), "khong_co")
check("không có reference -> khong_co", run(b.resolve_reply_target(msg(None), "5")), "khong_co")

# lần 2 dùng cache, không tải lại
calls = []
async def fm(mid):
    calls.append(mid); return ns(author=ns(id=9))
m2 = ns(reference=ns(resolved=None, message_id=21), channel=ns(fetch_message=fm))
b._ref_author_cache.clear()
run(b.resolve_reply_target(m2, "5")); run(b.resolve_reply_target(m2, "5"))
check("cùng tin gốc chỉ tải 1 lần", calls, [21])

# lệnh slash: interaction_metadata.user
check("slash của bạn", b.reply_target(msg(None, inter_user=5), "5"), "ban")
check("slash của người khác", b.reply_target(msg(None, inter_user=9), "5"), "nguoi_khac")

print("\n" + ("TẤT CẢ ĐẠT" if not fails else f"{len(fails)} LỖI: {fails}"))
sys.exit(1 if fails else 0)
