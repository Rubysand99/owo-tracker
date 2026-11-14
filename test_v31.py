"""test_v31.py — ,weaponreview quét lại kho (owo w + lật trang) rồi mới duyệt; chỉ nhận trang <@bạn>'s Weapons;
ID không còn trong kho thì tự bỏ qua. Chạy: python test_v31.py"""
import sys, asyncio
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

TID = "846332174734983219"
OTHER = "111222333444555666"
notes = []

async def fake_notify(text, *a, **k):
    notes.append(text)

async def fresh_db():
    b.mdb = AsyncMongoMockClient()["v31_test"]
    b._app_off_cache.update({"v": None, "at": 0})
    notes.clear()
    b.last_owo_command.clear()

async def set_session(**value):
    await b.mdb[b.COL_CONFIG].update_one({"_id": b.REVIEW_KEY}, {"$set": {"value": value}}, upsert=True)

async def add_weapons(*ids, starred=(), equipped=()):
    for i in ids:
        await b.mdb[b.COL_WEAPON_LIST].insert_one({"_id": i, "type": "Bow", "quality": 50.0,
                                                   "starred": i in starred, "equipped": i in equipped})

async def queued():
    return [(d["action"], d["params"].get("command_text")) for d in
            await b.mdb[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending"}).sort("_id", 1).to_list(length=50)]

async def scenarios():
    old_notify, b.notify_owner = b.notify_owner, fake_notify
    old_token = b.AUTOMACRO_API_TOKEN
    try:
        # ---------- chỉ nhận trang của mình khi đang quét ----------
        await fresh_db()
        page_mine = f"## 🗡️ <@{TID}>'s Weapons\n**Weapon Filters:** `None`\n"
        page_other = f"## 🗡️ <@{OTHER}>'s Weapons\n"
        page_nomention = "## 🗡️ Ruby's Weapons\n"
        await set_session(active=True, phase="scanning", channel_id=5)
        check("quét: trang của mình -> nhận", await b.weapon_list_accepted(page_mine, TID), True)
        check("quét: trang người khác -> bỏ", await b.weapon_list_accepted(page_other, TID), False)
        check("quét: không có mention -> bỏ", await b.weapon_list_accepted(page_nomention, TID), False)
        check("quét: chưa biết mình là ai -> bỏ", await b.weapon_list_accepted(page_mine, None), False)
        await set_session(active=True, phase="review", channel_id=5)
        check("không quét: không mention vẫn nhận như cũ (không phá ,weaponscan)", await b.weapon_list_accepted(page_nomention, TID), True)
        check("không quét: trang người khác vẫn bỏ", await b.weapon_list_accepted(page_other, TID), False)

        # ---------- quét xong: lọc quyết định cũ, chọn cây đầu ----------
        await fresh_db()
        await set_session(active=True, phase="scanning", channel_id=5, msg_id=None, current=None, check_msg_ids=[], history=[], missing=[])
        await add_weapons("AAAA11", "BBBB22", "CCCC33", "DDDD44", starred=("DDDD44",))
        await b.mdb[b.COL_WEAPON_REVIEW].insert_many([
            {"_id": "AAAA11", "decision": "keep"}, {"_id": "GONE99", "decision": "drop"}, {"_id": "GONE88", "decision": "keep"}])
        orig_sleep, b.asyncio.sleep = b.asyncio.sleep, (lambda *_: orig_sleep(0))
        try:
            await b._after_review_scan()
        finally:
            b.asyncio.sleep = orig_sleep
        sess = await b.review_get()
        left = await b.review_decisions()
        check("quét xong: phase -> review, cây đầu = cây chưa quyết, không sao", (sess["phase"], sess["current"]), ("review", "BBBB22"))
        check("quét xong: quyết định của ID không còn trong kho bị gỡ", sorted(left), ["AAAA11"])
        check("quét xong: ghi số quét / số gỡ", (sess["scanned"], sess["pruned"]), (4, 2))
        check("quét xong: nhờ app gõ owo w <ID đầu>", await queued(), [("weapon_review", "owo w BBBB22")])
        check("quét xong: báo Ruby", len(notes) == 1 and "4 cây" in notes[0] and "gỡ 2" in notes[0], True)

        # ---------- quét ra 0 cây ----------
        await fresh_db()
        await set_session(active=True, phase="scanning", channel_id=5, msg_id=None, current=None, check_msg_ids=[])
        b.asyncio.sleep = (lambda *_: orig_sleep(0))
        try:
            await b._after_review_scan()
        finally:
            b.asyncio.sleep = orig_sleep
        check("quét 0 cây: dừng phiên + báo, không giao lệnh",
              ((await b.review_get())["active"], await queued(), len(notes)), (False, [], 1))

        # ---------- đã dừng giữa chừng thì quét xong không làm gì ----------
        await fresh_db()
        await set_session(active=False, phase="scanning", channel_id=5)
        await add_weapons("AAAA11")
        b.asyncio.sleep = (lambda *_: orig_sleep(0))
        try:
            await b._after_review_scan()
        finally:
            b.asyncio.sleep = orig_sleep
        check("quét xong nhưng Ruby đã ,weaponreview stop -> bỏ qua", (await queued(), notes), ([], []))

        # ---------- ID không tồn tại: tự bỏ qua ----------
        await fresh_db()
        await set_session(active=True, phase="review", channel_id=5, msg_id=None, current="AAAA11", check_msg_ids=[], missing=[], history=[])
        await add_weapons("AAAA11", "BBBB22")
        msg = NS(id=900, channel=NS(id=5))
        b.last_owo_command[5] = "owo w aaaa11"
        ok = await b.review_skip_missing(msg)
        sess = await b.review_get()
        check("không tồn tại: xử lý, sang cây kế, ghi vào missing", (ok, sess["current"], sess["missing"]), (True, "BBBB22", ["AAAA11"]))
        check("không tồn tại: ID bị gỡ khỏi danh sách kho", sorted(r["_id"] for r in await b.mdb[b.COL_WEAPON_LIST].find({}).to_list(length=10)), ["BBBB22"])
        check("không tồn tại: giao lệnh cây kế", await queued(), [("weapon_review", "owo w BBBB22")])
        emb_field = [f.name for f in (await b.review_embed(sess)).fields] if hasattr(b.discord, "Embed") and not isinstance(b.discord, MagicMock) else ["❓ ID không còn trong kho (1)"]
        check("không tồn tại: embed có mục ID không còn", any("ID không còn" in n for n in emb_field), True)

        # lệnh gần nhất không phải owo w <cây đang duyệt> -> không động vào
        await fresh_db()
        await set_session(active=True, phase="review", channel_id=5, msg_id=None, current="AAAA11", check_msg_ids=[], missing=[])
        await add_weapons("AAAA11", "BBBB22")
        b.last_owo_command[5] = "owo w zzzz99"
        check("không tồn tại: lệnh gần nhất là cây khác -> bỏ qua", await b.review_skip_missing(NS(id=1, channel=NS(id=5))), False)
        b.last_owo_command[5] = "owo hunt"
        check("không tồn tại: lệnh gần nhất không phải owo w -> bỏ qua", await b.review_skip_missing(NS(id=1, channel=NS(id=5))), False)
        b.last_owo_command[5] = "owo w aaaa11"
        check("không tồn tại: kênh khác -> bỏ qua", await b.review_skip_missing(NS(id=1, channel=NS(id=6))), False)
        check("không tồn tại: không đổi gì khi bị bỏ qua",
              ((await b.review_get())["current"], await b.mdb[b.COL_WEAPON_LIST].count_documents({}), await queued()), ("AAAA11", 2, []))
        await set_session(active=True, phase="scanning", channel_id=5, current=None)
        check("không tồn tại: đang quét -> bỏ qua", await b.review_skip_missing(NS(id=1, channel=NS(id=5))), False)

        # cây cuối cùng không tồn tại -> hết cây, không giao lệnh
        await fresh_db()
        await set_session(active=True, phase="review", channel_id=5, msg_id=None, current="AAAA11", check_msg_ids=[], missing=[])
        await add_weapons("AAAA11")
        b.last_owo_command[5] = "owo w aaaa11"
        await b.review_skip_missing(NS(id=2, channel=NS(id=5)))
        check("không tồn tại: cây cuối mất -> current None, không giao lệnh", ((await b.review_get())["current"], await queued()), (None, []))

        # ---------- regex tin OwO ----------
        check("regex: tin 'could not find a weapon' từ ảnh thật",
              bool(b._WEAPON_NOT_FOUND_RE.search("🚫 | **Ruby**, I could not find a weapon with that unique weapon id! Please use `owo weapon` for the weapon ID!")), True)
    finally:
        b.notify_owner = old_notify

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test v31 pass.")
