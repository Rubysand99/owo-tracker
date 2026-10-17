"""test_zoo_off_captcha.py — kiểm tra các tính năng Ruby thêm (lịch sử zoo, owo zoo d, ⭐/➤ trong danh sách vũ khí,
công tắc ,off) + 2 lỗi đã sửa (lịch sử zoo lưu bản thiếu, ,captcha clear không giới hạn chủ bot). Chạy: python test_zoo_off_captcha.py"""
import sys, asyncio, json, re, os
FAILS = []
from unittest.mock import MagicMock
from types import SimpleNamespace as NS
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    try: __import__(m)
    except Exception: sys.modules[m] = MagicMock()
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient
FX = json.load(open("fixtures_zoo_2026-10-10.json", encoding="utf-8"))
def r(label, got, want=None):
    ok = (got == want) if want is not None else bool(got)
    print(("✅ " if ok else "❌ ") + label + ("" if ok else f"\n     thực tế: {got!r}"))
    if not ok: FAILS.append(label)

# --- 1. weapon list có ⭐ và ➤
line = "`FVK6GV` <:rare:1><:rpstaff:2><:udischarge:3> ⭐ **Staff of Purity** 60.7% ➤ <:dboar:4> dboar\n`FVK6GG` <:epic:1><:eprgaxe:2><:ecritical:3> **Decent Glacial Axe** 20.0%"
hdr = "🗡️ <@1>'s Weapons\nWeapon Filters: None\n"
wl = b.parse_weapon_list(hdr + line)
r("list: ⭐ + ➤ đọc đúng", [(e["id"], e["starred"], e["equipped"], e["equipped_by"]) for e in wl], [("FVK6GV", True, True, "dboar"), ("FVK6GG", False, False, None)])
wl2 = b.parse_weapon_list(hdr + "`FVK6GV` <:rare:1><:rpstaff:2><:udischarge:3> **Staff of Purity** 60.7% ➤ <:4m_owo:4>")
r("list: pet chỉ có emoji (tên có số) -> equipped_by", (wl2[0]["equipped"], wl2[0]["equipped_by"]), (True, None))

async def zoo_history():
    b.mdb = AsyncMongoMockClient()["rv"]
    await b.load_emoji_cache()
    b.zoo_session.clear()
    # thứ tự cũ: tiêu đề trước (OwO có thể gửi kiểu này)
    for k in ["header", "middle_part", "points_part"]:
        await b.handle_zoo_text(1, FX[k], "u")
    n = await b.mdb[b.COL_ZOO_HISTORY].count_documents({"kind": "current"})
    r("zoo history: 1 lần gõ zoo (tiêu đề đến TRƯỚC) chỉ nên tạo 1 dòng lịch sử", n, 1)
    hist = await b.mdb[b.COL_ZOO_HISTORY].find({"kind": "current"}).sort("at", 1).to_list(length=10)
    r("zoo history: các dòng đều đủ 89 loài (không lưu bản thiếu)", [len(h["pets"]) for h in hist], [89])
    # thứ tự thật: tiêu đề đến CUỐI
    b.zoo_session.clear(); await b.mdb[b.COL_ZOO_HISTORY].delete_many({}); await b.mdb[b.COL_ZOO].delete_many({})
    for k in ["points_part", "middle_part", "header"]:
        await b.handle_zoo_text(2, FX[k], "u")
    n2 = await b.mdb[b.COL_ZOO_HISTORY].count_documents({"kind": "current"})
    r("zoo history: thứ tự thật (tiêu đề đến cuối) -> 1 dòng", n2, 1)
asyncio.run(zoo_history())

# --- 3. owo zoo d (đệm 0 đủ 6 chữ số)
sup = "⁰¹²³⁴⁵⁶⁷⁸⁹"
def pad(text):
    return re.sub(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: sup[0] * max(0, 6 - len(m.group(1))) + m.group(1), text)
padded = b.parse_zoo(pad(FX["header"]))
r("zoo d: nhận ra bảng 'owo zoo d' (padded)", padded["padded"], True)
r("zoo thường: padded = False", b.parse_zoo(FX["header"])["padded"], False)

async def zoo_d():
    b.mdb = AsyncMongoMockClient()["rv2"]
    await b.load_emoji_cache()
    b.zoo_session.clear()
    for k in ["points_part", "middle_part", "header"]:
        await b.handle_zoo_text(3, FX[k], "u")
    before = await b.mdb[b.COL_ZOO].find_one({"_id": "latest"})
    b.zoo_session.clear()
    for k in ["points_part", "middle_part", "header"]:
        await b.handle_zoo_text(3, pad(FX[k]), "u")
    after = await b.mdb[b.COL_ZOO].find_one({"_id": "latest"})
    r("zoo d: KHÔNG ghi đè zoo đang giữ", len(before["pets"]) == len(after["pets"]) and before["updated_at"] == after["updated_at"], True)
    kinds = sorted({h["kind"] for h in await b.mdb[b.COL_ZOO_HISTORY].find({}).to_list(length=50)})
    r("zoo d: lịch sử có cả 2 loại", kinds, ["all", "current"])
asyncio.run(zoo_d())

# --- 4. công tắc ,off
async def off_mode():
    b.mdb = AsyncMongoMockClient()["rv3"]
    b.AUTOMACRO_API_TOKEN = "tok"
    await b.set_app_off(True)
    got = await b.queue_automacro_command("swap_gem", {"command_text": "owo use 51"})
    r("off: queue_automacro_command trả None và không ghi gì", (got, await b.mdb[b.COL_AUTOMACRO_COMMANDS].count_documents({})), (None, 0))
    class Req:
        headers = {"Authorization": "Bearer tok"}
    resp = await b.handle_get_pending_commands(Req())
    r("off: /commands/pending trả rỗng + off=True", (json.loads(resp.body)["commands"], json.loads(resp.body)["off"]), ([], True))
    async def fake_notify(*a, **k): return True
    b.notify_owner = fake_notify
    r("off: tự chạy lại huntbot bị chặn", await b.maybe_auto_hb_restart("u"), False)
    sent = []
    async def send(t, **k): sent.append(t)
    ctx = NS(command=NS(name="weaponscan"), send=send)
    from discord.ext import commands as _c
    try:
        await b._app_off_guard(ctx); blocked = False
    except _c.CheckFailure as e:
        blocked = str(e) == "app_off"
    r("off: lệnh nhờ app (weaponscan) bị chặn + báo Ruby", (blocked, bool(sent)), (True, True))
    ctx2 = NS(command=NS(name="status"), send=send)
    r("off: lệnh thường (status) vẫn chạy", await b._app_off_guard(ctx2), True)
    await b.set_app_off(False)
    r("off: bật lại -> queue ghi được", bool(await b.queue_automacro_command("swap_gem", {"command_text": "owo use 51"})), True)
asyncio.run(off_mode())

# --- 5. ,captcha clear chỉ chủ bot
async def captcha_owner():
    b.mdb = AsyncMongoMockClient()["rv4"]
    b.OWNER_ID = "1"
    await b.mdb[b.COL_ALERTS].update_one({"_id": "captcha"}, {"$set": {"active": True}}, upsert=True)
    sent = []
    async def send(t, **k): sent.append(t)
    await b.captcha_cmd(NS(author=NS(id=2), send=send), "clear")
    st = await b.mdb[b.COL_ALERTS].find_one({"_id": "captcha"})
    r("captcha clear: người lạ KHÔNG huỷ được cảnh báo", (st["active"], "chủ bot" in sent[-1]), (True, True))
    await b.captcha_cmd(NS(author=NS(id=1), send=send), "clear")
    st = await b.mdb[b.COL_ALERTS].find_one({"_id": "captcha"})
    r("captcha clear: chủ bot huỷ được", st["active"], False)
    await b.mdb[b.COL_ALERTS].update_one({"_id": "captcha"}, {"$set": {"active": True}})
    await b.captcha_cmd(NS(author=NS(id=2), send=send), "")
    r("captcha (xem trạng thái): ai cũng xem được", "captcha" in sent[-1].lower(), True)
asyncio.run(captcha_owner())

if FAILS:
    print("\n❌ %d bài lỗi" % len(FAILS)); sys.exit(1)
print("\n✅ Toàn bộ test zoo/off/captcha pass.")
