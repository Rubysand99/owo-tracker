"""test_off_no_dm.py — Hub TẮT (,off) thì bot không DM ai (acc chính lẫn acc phụ). Chạy: python test_off_no_dm.py"""
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

async def run(off, target="owner", dm=True):
    b.mdb = AsyncMongoMockClient()["nodm_%s_%s_%s" % (off, target, dm)]
    await b.set_config("alt_user_id", "777"); await b.set_config("tracked_user_id", "5"); await b.set_app_off(off)
    b._notify_recent.clear()
    log = []
    class User:
        def __init__(s, uid): s.uid = uid
        async def send(s, text, **kw): log.append(("dm", s.uid))
    class Chan:
        async def send(s, text, **kw): log.append(("kenh", "tag"))
    async def nci(): return "999"
    b.notify_channel_id = nci
    b.bot = NS(get_channel=lambda i: Chan(), fetch_channel=None, get_user=lambda i: User(str(i)), fetch_user=None)
    b.discord = MagicMock()
    ok = await b.notify_owner("hello " + str(off) + target, dm=dm, target=target, min_gap=0)
    return ok, log

async def main():
    ok, log = await run(off=False)
    r("Hub bật: tag kênh + DM acc chính (như cũ)", log, [("kenh", "tag"), ("dm", "5")])
    ok, log = await run(off=False, target="alt")
    r("Hub bật: tin cho acc phụ DM acc phụ (như cũ)", log, [("dm", "777")])
    ok, log = await run(off=True)
    r("Hub tắt: không DM acc chính (vẫn tag trong kênh)", log, [("kenh", "tag")])
    ok, log = await run(off=True, target="alt")
    r("Hub tắt: tin cho acc phụ bị bỏ, không DM ai, không chuyển sang acc chính", (ok, log), (False, []))
asyncio.run(main())
print("\n" + ("TẤT CẢ ĐẠT" if not FAILS else f"{len(FAILS)} LỖI"))
sys.exit(1 if FAILS else 0)
