"""test_tools_handlers.py — các đường API mới của màn "Công cụ": /teamcheck /zoodiff /unlocked /alt /alt/test.
Chạy: python test_tools_handlers.py   (cần mongomock-motor như các test khác; logic thuần nằm ở test_tools_api.py)"""
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

def req(body=None, token="tok", query=None):
    async def j():
        if body is None: raise ValueError("no json")
        return body
    return NS(headers={"Authorization": f"Bearer {token}"}, json=j, query=query or {})

def pet(tier, name, count=1, emoji_id=None):
    return {"tier": tier, "name": name, "count": count, "emoji_id": emoji_id, "emoji_animated": False}

async def scenarios():
    b.mdb = AsyncMongoMockClient()["tools_test"]
    old_token, b.AUTOMACRO_API_TOKEN = b.AUTOMACRO_API_TOKEN, "tok"
    old_dm = b.dm_user
    try:
        # ----- sai token: mọi đường mới đều 401 -----
        for name, h, kw in [("teamcheck", b.handle_get_teamcheck, {}), ("zoodiff", b.handle_get_zoodiff, {}),
                            ("unlocked", b.handle_get_unlocked, {}), ("alt GET", b.handle_get_alt, {}),
                            ("alt POST", b.handle_post_alt, {"body": {"user_id": ""}}),
                            ("alt/test", b.handle_post_alt_test, {}),
                            ("manual/pet", b.handle_post_manual_pet, {"body": {}}),
                            ("manual/weapontype", b.handle_post_manual_weapontype, {"body": {}}),
                            ("manual/passive", b.handle_post_manual_passive, {"body": {}})]:
            r = await h(req(token="sai", **kw))
            check(f"{name}: sai token -> 401", r.status, 401)

        # ----- /teamcheck -----
        r = await b.handle_get_teamcheck(req())
        d = json.loads(r.text)
        check("teamcheck: chưa có đội hình -> members 0 + hướng dẫn, đã bỏ ký hiệu Discord",
              (r.status, d["members"], "owo team" in d["text"], "`" in d["text"]), (200, 0, True, False))

        # ----- /zoodiff -----
        r = await b.handle_get_zoodiff(req())
        d = json.loads(r.text)
        check("zoodiff: chưa có lịch sử -> ok false + hướng dẫn", (r.status, d["ok"], d["kind"], "Chưa có lịch sử zoo" in d["text"]),
              (200, False, None, True))
        old_rec = {"kind": "current", "at": "2026-11-07T10:00:00+00:00", "zoo_points": 1000, "breakdown_raw": "C-100",
                   "pets": [pet("common", "bee", 5)]}
        await b.mdb[b.COL_ZOO_HISTORY].insert_one(old_rec)
        d = json.loads((await b.handle_get_zoodiff(req())).text)
        check("zoodiff: mới 1 lần ghi -> ok false, nói rõ số lần", (d["ok"], d["kind"], "Mới có 1 lần ghi" in d["text"]), (False, "current", True))
        await b.mdb[b.COL_ZOO_HISTORY].insert_one({
            "kind": "current", "at": "2026-11-08T10:00:00+00:00", "zoo_points": 1500, "breakdown_raw": "C-130",
            "pets": [pet("common", "bee", 9), pet("common", "cat", 1, emoji_id="111")]})
        r = await b.handle_get_zoodiff(req())
        d = json.loads(r.text)
        check("zoodiff: đủ 2 lần ghi -> ok true, kind current", (r.status, d["ok"], d["kind"]), (200, True, "current"))
        check("zoodiff: có điểm zoo, pet mới, đổi số lượng",
              ("Zoo Points: +500" in d["text"], "Mới mở khóa (1): cat" in d["text"], "bee: 5 → 9 (+4)" in d["text"]), (True, True, True))
        check("zoodiff: chữ đã sạch ký hiệu Discord", ("<:" in d["text"] or "**" in d["text"] or "`" in d["text"]), False)
        d = json.loads((await b.handle_get_zoodiff(req(query={"kind": "now"}))).text)
        check("zoodiff: ?kind=now = đang giữ", (d["ok"], d["kind"]), (True, "current"))
        d = json.loads((await b.handle_get_zoodiff(req(query={"kind": "d"}))).text)
        check("zoodiff: ?kind=d chưa có lần ghi nào -> ok false, kind all", (d["ok"], d["kind"], "owo zoo d" in d["text"]), (False, "all", True))
        r = await b.handle_get_zoodiff(req(query={"kind": "linhtinh"}))
        check("zoodiff: kind sai -> 400", r.status, 400)
        # lệnh Discord dùng chung hàm: kết quả giống
        state, text, kind = await b.zoodiff_report("")
        check("zoodiff_report dùng chung cho lệnh Discord", (state, kind, text.startswith("**So 2 lần ghi")), ("ok", "current", True))

        # ----- /unlocked -----
        d = json.loads((await b.handle_get_unlocked(req())).text)
        check("unlocked: chưa có dữ liệu -> 0 con", d, {"total": 0, "tiers": []})
        await b.mdb[b.COL_ZOO_UNLOCKED].insert_many([
            {"_id": "rare:wolf", "tier": "rare", "name": "wolf", "emoji_id": None, "emoji_animated": False},
            {"_id": "common:bee", "tier": "common", "name": "bee", "emoji_id": None, "emoji_animated": False}])
        await b.mdb[b.COL_ZOO].insert_one({"_id": "latest", "pets": [pet("epic", "dragon"), pet("common", "bee", 3)]})
        r = await b.handle_get_unlocked(req())
        d = json.loads(r.text)
        check("unlocked: gộp danh sách đã nhớ + zoo đang giữ, xếp theo bậc hiếm",
              (r.status, d["total"], [(t["tier"], t["pets"]) for t in d["tiers"]]),
              (200, 3, [("common", ["bee"]), ("rare", ["wolf"]), ("epic", ["dragon"])]))
        d = json.loads((await b.handle_get_unlocked(req(query={"tier": "RARE"}))).text)
        check("unlocked: ?tier=RARE chỉ trả tier đó", (d["total"], [t["tier"] for t in d["tiers"]]), (1, ["rare"]))
        r = await b.handle_get_unlocked(req(query={"tier": "fabled"}))
        d = json.loads(r.text)
        check("unlocked: tier lạ -> 400 kèm các tier có", (r.status, d["tiers"]), (400, ["common", "rare", "epic"]))

        # ----- /alt -----
        d = json.loads((await b.handle_get_alt(req())).text)
        check("alt: chưa đặt -> trả ID mặc định của bot", d, {"alt_user_id": b.ALT_USER_ID_DEFAULT})
        r = await b.handle_post_alt(req({"user_id": " 123456789012345678 "}))
        check("alt: đặt ID hợp lệ -> lưu giống ,setalt (cắt khoảng trắng)",
              (r.status, json.loads(r.text), await b.get_config("alt_user_id")),
              (200, {"alt_user_id": "123456789012345678"}, "123456789012345678"))
        for bad in ({"user_id": "abc"}, {"user_id": "12345"}, {"user_id": 123456789012345678}, {}, None):
            r = await b.handle_post_alt(req(bad))
            check(f"alt: body sai {bad!r} -> 400, không đổi gì", (r.status, await b.get_config("alt_user_id")),
                  (400, "123456789012345678"))
        sent = []
        async def fake_dm(uid, text, images=None):
            sent.append(uid); return True
        b.dm_user = fake_dm
        d = json.loads((await b.handle_post_alt_test(req({}))).text)
        check("alt/test: DM được -> ok true, gửi đúng ID", (d, sent), ({"ok": True, "alt_user_id": "123456789012345678", "reason": ""}, ["123456789012345678"]))
        async def fail_dm(uid, text, images=None):
            return False
        b.dm_user = fail_dm
        d = json.loads((await b.handle_post_alt_test(req({}))).text)
        check("alt/test: DM lỗi -> ok false, reason dm_failed", (d["ok"], d["reason"]), (False, "dm_failed"))
        r = await b.handle_post_alt(req({"user_id": ""}))
        check("alt: rỗng = tắt (bot KHÔNG quay về ID mặc định)",
              (r.status, json.loads(r.text), await b.get_config("alt_user_id")), (200, {"alt_user_id": ""}, ""))
        sent.clear(); b.dm_user = fake_dm
        d = json.loads((await b.handle_post_alt_test(req({}))).text)
        check("alt/test: chưa đặt acc phụ -> no_alt, không DM ai", (d, sent), ({"ok": False, "alt_user_id": "", "reason": "no_alt"}, []))

        # ----- /manual/pet -----
        pet_body = {"name": "Gowl", "rank": "legendary", "hp": 10, "att": 1, "pr": 3, "wp": 1, "mag": 2, "mr": 3}
        r = await b.handle_post_manual_pet(req(pet_body))
        doc = await b.mdb[b.COL_PET_SPECIES].find_one({"_id": "gowl"})
        check("manual/pet: lưu đúng như ,petset", (r.status, json.loads(r.text)), (200, {"ok": True, "name": "Gowl"}))
        check("manual/pet: bản ghi đủ trường, nguồn manual",
              (doc["display_name"], doc["rank"], doc["hp"], doc["mr"], doc["source"], doc["confirmed_by"]),
              ("Gowl", "Legendary", 10, 3, "manual", "app"))
        r = await b.handle_post_manual_pet(req({**pet_body, "hp": 99, "rank": "rare"}))
        doc = await b.mdb[b.COL_PET_SPECIES].find_one({"_id": "gowl"})
        check("manual/pet: nhập lại cùng tên = sửa, không tạo bản ghi thứ 2",
              (doc["hp"], doc["rank"], await b.mdb[b.COL_PET_SPECIES].count_documents({})), (99, "Rare", 1))
        r = await b.handle_post_manual_pet(req({**pet_body, "att": "x"}))
        check("manual/pet: chỉ số sai -> 400 kèm tên trường", (r.status, json.loads(r.text)["field"]), (400, "att"))
        r = await b.handle_post_manual_pet(req(None))
        check("manual/pet: body không phải JSON -> 400", r.status, 400)

        # ----- /manual/weapontype -----
        r = await b.handle_post_manual_weapontype(req({"name": "Poison Dagger", "desc": "Gây Poison"}))
        doc = await b.mdb[b.COL_WEAPON_TYPES].find_one({"_id": "poison dagger"})
        check("manual/weapontype: lưu như ,weapontypeset",
              (r.status, json.loads(r.text), doc["display_name"], doc["main_desc"], doc["confirmed_by"]),
              (200, {"ok": True, "name": "Poison Dagger"}, "Poison Dagger", "Gây Poison", "app"))
        r = await b.handle_post_manual_weapontype(req({"name": "Poison Dagger", "desc": ""}))
        check("manual/weapontype: mô tả rỗng -> 400", (r.status, json.loads(r.text)["field"]), (400, "desc"))

        # ----- /manual/passive -----
        r = await b.handle_post_manual_passive(req({"name": "Enrage", "desc": "Tăng sát thương khi HP thấp"}))
        doc = await b.mdb[b.COL_PASSIVES].find_one({"_id": "enrage"})
        check("manual/passive: lưu như ,passiveset (có bản dịch description_vi)",
              (r.status, doc["display_name"], doc["description"], "description_vi" in doc, doc["confirmed_by"]),
              (200, "Enrage", "Tăng sát thương khi HP thấp", True, "app"))
        r = await b.handle_post_manual_passive(req({"desc": "x"}))
        check("manual/passive: thiếu tên -> 400", (r.status, json.loads(r.text)["field"]), (400, "name"))
    finally:
        b.AUTOMACRO_API_TOKEN = old_token
        b.dm_user = old_dm

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test handler của màn Công cụ pass.")
