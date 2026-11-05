"""test_v30.py — API cho man "Cong cu" cua app: /settings, /notes, /captcha/clear.
Chạy: python test_v30.py"""
import sys, asyncio, json
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

def req(body=None, token="tok"):
    async def j():
        if body is None: raise ValueError("no json")
        return body
    return NS(headers={"Authorization": f"Bearer {token}"}, json=j)

async def scenarios():
    b.mdb = AsyncMongoMockClient()["v30_test"]; b._app_off_cache.update({"v": None, "at": 0})
    old, b.AUTOMACRO_API_TOKEN = b.AUTOMACRO_API_TOKEN, "tok"
    try:
        # ----- /settings -----
        r = await b.handle_get_settings(req({}, token="sai"))
        check("settings: sai token -> 401", r.status, 401)
        r = await b.handle_get_settings(req({}))
        d = json.loads(r.text)
        check("settings: mặc định giống các lệnh ,autocheck/,hbauto/,hbalert",
              (d["auto_check"], d["hb_auto"], d["hb_alert"], d["event_mode"], d["app_on"], d["captcha_active"]),
              (True, True, False, False, True, False))
        r = await b.handle_post_settings(req({"key": "hb_alert", "enabled": True}))
        d = json.loads(r.text)
        check("settings: bật hb_alert -> 200 và lưu giống ,hbalert on",
              (r.status, d["hb_alert"], await b.get_config("hb_alert")), (200, True, "on"))
        r = await b.handle_post_settings(req({"key": "auto_check", "enabled": False}))
        check("settings: tắt auto_check lưu 'off' (bot đọc đúng khóa cũ)",
              (r.status, await b.get_config("auto_check")), (200, "off"))
        r = await b.handle_post_settings(req({"key": "hb_auto", "enabled": False}))
        check("settings: tắt hb_auto", (r.status, await b.get_config("hb_auto")), (200, "off"))
        for bad in ({"key": "linh_tinh", "enabled": True}, {"key": "hb_auto", "enabled": "on"}, {"key": "hb_auto"}, None):
            r = await b.handle_post_settings(req(bad))
            check(f"settings: body sai {bad!r} -> 400", r.status, 400)
        # ----- /notes -----
        r = await b.handle_get_notes(req({}))
        check("notes: chưa có gì -> danh sách rỗng", json.loads(r.text), {"notes": []})
        r = await b.handle_post_notes(req({"action": "add", "text": "  mua gem  "}))
        d = json.loads(r.text)
        check("notes: thêm -> 200, cắt khoảng trắng, chưa xong",
              (r.status, [(n["text"], n["done"]) for n in d["notes"]]), (200, [("mua gem", False)]))
        nid = d["notes"][0]["id"]
        r = await b.handle_post_notes(req({"action": "add", "text": "   "}))
        check("notes: text rỗng -> 400", r.status, 400)
        r = await b.handle_post_notes(req({"action": "add", "text": "x" * 900}))
        check("notes: text dài bị cắt 500 ký tự", len(json.loads(r.text)["notes"][-1]["text"]), 500)
        r = await b.handle_post_notes(req({"action": "done", "id": nid}))
        d = json.loads(r.text)
        check("notes: đánh dấu xong, việc chưa xong đứng trước",
              [(n["id"] == nid, n["done"]) for n in d["notes"]], [(False, False), (True, True)])
        for bad in ({"action": "done", "id": "1"}, {"action": "done", "id": True}, {"action": "xoa"}, None):
            r = await b.handle_post_notes(req(bad))
            check(f"notes: body sai {bad!r} -> 400", r.status, 400)
        r = await b.handle_get_notes(req({}, token="sai"))
        check("notes: sai token -> 401", r.status, 401)
        # ----- /captcha/clear -----
        await b.mdb[b.COL_ALERTS].update_one({"_id": "captcha"}, {"$set": {"active": True, "at": b._utcnow().isoformat()}}, upsert=True)
        r = await b.handle_post_captcha_clear(req({}, token="sai"))
        check("captcha clear: sai token -> 401", r.status, 401)
        r = await b.handle_post_captcha_clear(req({}))
        check("captcha clear: -> 200 và hết cảnh báo", (r.status, (await b.get_captcha_state())["active"]), (200, False))
    finally:
        b.AUTOMACRO_API_TOKEN = old

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test v30 pass.")
