"""test_hb_password_owner.py — mật khẩu/captcha huntbot của NGƯỜI KHÁC (OwO reply tin họ) không được DM; Hub tắt thì không chuyển mật khẩu.
Chạy: python test_hb_password_owner.py"""
import sys, asyncio, time
from unittest.mock import MagicMock
from types import SimpleNamespace as NS
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    try: __import__(m)
    except Exception: sys.modules[m] = MagicMock()
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient

FAILS = []
def r(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label + ("" if ok else f"\n     thực tế: {got!r}  mong đợi: {want!r}"))
    if not ok: FAILS.append(label)

HB = "🔐 Here is your password! Please use the password to start your huntbot. (password image)"
CAP = "⚠️ are you a real human? Please use the link below so I can check! Complete this within 10 minutes."

def owo(text, ref_author=None, fetch_author=None, resolved=True):
    async def fetch_message(mid): return NS(author=NS(id=fetch_author))
    ref = None
    if ref_author is not None or fetch_author is not None:
        ref = NS(resolved=NS(author=NS(id=ref_author)) if resolved else None, message_id=42)
    return NS(content=text, embeds=[], components=[], reference=ref, jump_url="https://discord.com/x", id=1,
              author=NS(id=b.OWO_BOT_ID), channel=NS(id=1, fetch_message=fetch_message), guild=None)

async def run(text, *, off=False, hb_window=False, **mk):
    b.mdb = AsyncMongoMockClient()["hbo_%d" % int(time.time() * 1e6)]
    await b.set_config("alt_user_id", "777"); await b.set_app_off(off)
    b._notify_recent.clear(); b._ref_author_cache.clear()
    b.hb_pending["at"] = time.time() if hb_window else 0.0
    sent = []
    async def fake_notify(t, **kw): sent.append(("notify", kw.get("target", "owner"))); return True
    async def fake_dm(uid, t, images=None): sent.append(("dm", str(uid))); return True
    old = (b.notify_owner, b.dm_user); b.notify_owner, b.dm_user = fake_notify, fake_dm
    try:
        m = owo(text, **mk)
        rt = await b.resolve_reply_target(m, "5")
        await b.check_captcha_message(m, "5", rt); await b.check_hb_password_message(m, "5", rt)
    finally:
        b.notify_owner, b.dm_user = old
    return sent

async def main():
    r("mật khẩu huntbot OwO reply NGƯỜI KHÁC (tin gốc có trong cache): không DM", await run(HB, ref_author=9), [])
    r("... tin gốc KHÔNG có trong cache (phải tải): không DM", await run(HB, fetch_author=9, resolved=False), [])
    r("captcha OwO reply NGƯỜI KHÁC: không báo ai", await run(CAP, ref_author=9), [])
    r("Hub tắt: mật khẩu huntbot không chuyển sang acc phụ", await run(HB, off=True, ref_author=5), [])
    r("Hub bật + reply tin của BẠN: chuyển sang acc phụ", await run(HB, ref_author=5), [("notify", "alt")])
    r("Hub bật + không rõ chủ + không có yêu cầu đang chờ: bỏ qua", await run(HB), [])
    r("Hub bật + không rõ chủ nhưng bạn vừa xin mật khẩu: chuyển", await run(HB, hb_window=True), [("notify", "alt")])
    r("captcha của BẠN (reply tin bạn), Hub bật: báo acc chính", await run(CAP, ref_author=5), [("notify", "owner")])
asyncio.run(main())
print("\n" + ("TẤT CẢ ĐẠT" if not FAILS else f"{len(FAILS)} LỖI"))
sys.exit(1 if FAILS else 0)
