"""test_captcha_alt_dm.py — Hub TẮT (,off) thì captcha cũng DM acc phụ; Hub BẬT thì không. Chạy: python test_captcha_alt_dm.py"""
import sys, asyncio
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

CAPTCHA = "⚠️ <@5>, are you a real human? Please use the link below so I can check! Complete this within 10 minutes."
def owo(): return NS(content=CAPTCHA, embeds=[], components=[], reference=None, jump_url="https://discord.com/x", id=1,
                     author=NS(id=b.OWO_BOT_ID), channel=NS(id=1))

async def scenario(off, alt, owner_sends=True):
    b.mdb = AsyncMongoMockClient()["alt_dm_%s_%s_%s" % (off, bool(alt), owner_sends)]
    await b.set_config("alt_user_id", alt); await b.set_app_off(off)
    b._notify_recent.clear()
    owner_calls, dms = [], []
    async def fake_notify(text, **kw): owner_calls.append(text); return owner_sends
    async def fake_dm(uid, text, images=None): dms.append((str(uid), text)); return True
    old = (b.notify_owner, b.dm_user)
    b.notify_owner, b.dm_user = fake_notify, fake_dm
    try:
        await b.check_captcha_message(owo(), "5")
    finally:
        b.notify_owner, b.dm_user = old
    return len(owner_calls), dms

async def main():
    n, dms = await scenario(off=True, alt="777")
    r("Hub tắt: vẫn báo acc chính", n, 1)
    r("Hub tắt: DM acc phụ có link/captcha", [(u, "CAPTCHA" in t) for u, t in dms], [("777", True)])
    n, dms = await scenario(off=False, alt="777")
    r("Hub bật: không DM thêm acc phụ (app tự reo chuông)", dms, [])
    n, dms = await scenario(off=True, alt="")
    r("Hub tắt nhưng chưa đặt acc phụ: không lỗi, không DM", (n, dms), (1, []))
    n, dms = await scenario(off=True, alt="777", owner_sends=False)
    r("Hub tắt, tin trùng (bị chống spam): không DM acc phụ lặp lại", dms, [])
asyncio.run(main())
print("\n" + ("TẤT CẢ ĐẠT" if not FAILS else f"{len(FAILS)} LỖI"))
sys.exit(1 if FAILS else 0)
