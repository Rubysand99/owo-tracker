"""test_v29.py — tin sự kiện [x/10], gem special (star), kho định dạng mới, chặn báo nhầm pet mới.
Chạy: python test_v29.py"""
import sys, asyncio
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient
from datetime import datetime

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

UID = "846332174734983219"
BEAR = (f"🐻 **|** `[8/10]` <@{UID}>, A bear-ista freshly brewed you an espresso cup with "
        "**435 <:weaponshard:655902978712272917> Weapon Shards** on the side!")
CANDY = (f"🍬 **|** `[1/10]` <@{UID}>, Trick or treat! The neighbour is handing out "
         "**2 <:crate:523771259302182922> Weapon Crates**!")

ev = b.parse_event_hunt(BEAR, UID)
check("sự kiện 🐻: đếm 8/10", (ev[0]["kind"], ev[0]["current"], ev[0]["max"]), ("🐻", 8, 10))
check("sự kiện 🐻: thưởng 435 Weapon Shards", [(r["amount"], r["item"], r.get("emoji_name")) for r in ev[0]["rewards"]],
      [(435, "Weapon Shards", "weaponshard")])
ev = b.parse_event_hunt(CANDY, UID)
check("sự kiện 🍬: đếm 1/10", (ev[0]["kind"], ev[0]["current"], ev[0]["max"]), ("🍬", 1, 10))
check("sự kiện 🍬: thưởng 2 Weapon Crates", [(r["amount"], r["item"]) for r in ev[0]["rewards"]], [(2, "Weapon Crates")])
check("sự kiện: hiện đúng chữ, không còn emoji tag/**", ev[0]["text"],
      "Trick or treat! The neighbour is handing out 2 Weapon Crates!")
both = b.parse_event_hunt("**🌱 | Ruby**, hunt is empowered by gems\n" + BEAR + "\n" + CANDY, UID)
check("2 dòng sự kiện trong cùng 1 tin", [(e["kind"], e["current"]) for e in both], [("🐻", 8), ("🍬", 1)])
check("sự kiện của NGƯỜI KHÁC bị bỏ qua", b.parse_event_hunt(BEAR.replace(UID, "111"), UID), None)
check("tin hunt thường không có sự kiện", b.parse_event_hunt("**🌱 | Ruby**, hunt is empowered by gems\nYou found: :bee:", UID), None)
check("không biết ai đang theo dõi -> vẫn đọc", len(b.parse_event_hunt(BEAR, None)), 1)

# --- gem
check("gem thường cgem1", b.parse_gem_name("cgem1"), {"tier": "Common", "slot": "1"})
check("gem đặc biệt cstar -> slot star", b.parse_gem_name("cstar"), {"tier": "Common", "slot": "star"})
check("gem đặc biệt mstar", b.parse_gem_name("mstar"), {"tier": "Mythical", "slot": "star"})
check("không phải gem", b.parse_gem_name("greatsword"), None)

INV = """**====== Ruby's Inventory ======**
`001`<:cring:590393333331918859>⁰⁰¹    `051`<:cgem1:492572122120585240>¹¹⁷    `052`<:ugem1:492572122514980864>¹¹⁷    `053`<:rgem1:492572122888011776>¹²⁸
`054`<:egem1:492572122477101056>⁰⁵³    `055`<:mgem1:492572122590478356>⁰⁰¹    `065`<:cgem3:510366792024195072>¹³²    `066`<:ugem3:510366792095367189>¹¹⁵
`067`<:rgem3:510366792653340674>¹¹²    `068`<:egem3:510366792800272394>⁰⁶³    `069`<:mgem3:510366792447819777>⁰⁰²    `072`<:cgem4:510366763255463936>¹¹²
`073`<:ugem4:510366764249382922>¹²⁶    `074`<:rgem4:510366763884478464>¹³⁰    `075`<:egem4:510366763972558848>⁰³⁰    `079`<:cstar:1101731000721096744>⁰⁰²
`101`<:greatsword:538196865129250817>⁰²⁷    `102`<:healstaff:538196865410138125>⁰⁴²"""
inv = b.parse_inventory(INV)
items = {i["code"]: i for i in inv["items"]}
check("kho: đọc đủ 18 món", len(items), 18)
check("kho: cgem1 = 117 viên, slot 1", (items["051"]["count"], items["051"]["gem_slot"], items["051"]["gem_tier"]), (117, "1", "Common"))
check("kho: mgem3 = 2 viên", (items["069"]["count"], items["069"]["gem_slot"]), (2, "3"))
check("kho: cstar (gem đặc biệt) là gem, slot star, 2 viên",
      (items["079"]["is_gem"], items["079"]["gem_slot"], items["079"]["count"]), (True, "star", 2))
check("kho: vũ khí không bị tính là gem", items["101"]["is_gem"], False)
check("kho: nhẫn không bị tính là gem", items["001"]["is_gem"], False)

HUNT_STAR = ("**🌱 | Ruby**, hunt is empowered by <:cgem1:492572122120585240>`[57/100]` "
             "<:rgem3:510366792653340674>`[20/50]` <:cstar:1101731000721096744>`[9/10]`  !\n"
             "**<:blank:427371936482328596> |** You found:  :bee:")
gs = b.parse_hunt_gem_status(HUNT_STAR)
check("hunt có gem special: đọc 3 gem, có slot star", sorted(g["slot"] for g in gs["gems"]), ["1", "3", "star"])

async def run():
    b.mdb = AsyncMongoMockClient()["v29_test"]
    await b.load_emoji_cache()
    now = datetime.utcnow()
    check("hub event: chưa có -> None", await b._hub_event(now), None)
    await b.save_event_hunt(b.parse_event_hunt(BEAR, UID), "m1", UID)
    await b.save_event_hunt(b.parse_event_hunt(CANDY, UID), "m2", UID)
    await b.save_event_hunt(b.parse_event_hunt(BEAR.replace("[8/10]", "[9/10]"), UID), "m3", UID)
    h = await b._hub_event(datetime.utcnow())
    cnt = {c["kind"]: (c["current"], c["max"]) for c in h["counters"]}
    check("hub event: mỗi loại giữ số mới nhất", cnt, {"🐻": (9, 10), "🍬": (1, 10)})
    check("hub event: nhật ký 3 dòng", len(h["recent"]), 3)
    check("hub event: dòng mới nhất là 🐻 9/10", (h["recent"][0]["kind"], h["recent"][0]["current"]), ("🐻", 9))
    # nhat ky khong phinh to
    for i in range(60):
        await b.save_event_hunt(b.parse_event_hunt(CANDY, UID), f"x{i}", UID)
    n = await b.mdb[b.COL_EVENT].count_documents({"type": "log"})
    check("nhật ký giữ tối đa %d dòng" % b.EVENT_LOG_KEEP, n, b.EVENT_LOG_KEEP)

    # --- pet mới: zoo chưa đủ (thiếu tin 2) -> không kết luận
    found = {"animals": [{"name": "dragon"}]}
    await b.mdb[b.COL_ZOO].insert_one({"_id": "latest", "pets": [{"name": "bee", "tier": "common", "count": 3}],
                                       "zoo_points": None, "breakdown_raw": None})
    check("zoo thiếu Zoo Points (mới đọc 1 tin) -> KHÔNG báo pet mới", await b.record_new_pets(found, UID), None)
    await b.mdb[b.COL_ZOO].update_one({"_id": "latest"}, {"$set": {"zoo_points": 1000}})
    check("zoo đủ + pet thật sự chưa có -> báo pet mới", await b.record_new_pets(found, UID), ["dragon"])
    check("zoo đủ + pet đã có -> không báo", await b.record_new_pets({"animals": [{"name": "bee"}]}, UID), [])
asyncio.run(run())

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test v29 pass.")

# --- ten loai gem
print()
check("tên loại gem", [b.gem_type_name(x) for x in ("1", "3", "4", "star")], ["Hunting", "Empowering", "Lucky", "Special"])
async def run_gem_names():
    b.mdb = AsyncMongoMockClient()["v29_gem"]
    await b.load_emoji_cache()
    await b.save_gem_status(b.parse_hunt_gem_status(HUNT_STAR), "u1")
    await b.mdb[b.COL_INVENTORY].insert_one({"_id": "079", "is_gem": True, "gem_slot": "star", "gem_tier": "Common",
                                             "gem_tier_rank": 1, "count": 2, "name": "cstar"})
    g = await b._hub_gems(datetime.utcnow())
    check("hub gem: gem đang dùng có tên loại", sorted(e["type_name"] for e in g["equipped"]), ["Empowering", "Hunting", "Special"])
    check("hub gem: gem dự phòng có tên loại", [e["type_name"] for e in g["spare"]], ["Special"])
asyncio.run(run_gem_names())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test tên loại gem pass.")

# --- cong chan: chi doc MOI tin OwO khi da biet ten nguoi theo doi
async def run_gate():
    from types import SimpleNamespace as NS
    seen = []
    async def fake_handle(message, tid):
        seen.append(message.content)
    async def noop(*a, **k):
        return None
    old_h, old_p = b.handle_owo_response, b.bot.process_commands
    b.handle_owo_response, b.bot.process_commands = fake_handle, noop
    try:
        b.mdb = AsyncMongoMockClient()["v29_gate"]
        await b.set_config("tracked_channel_id", "77"); await b.set_config("tracked_user_id", "1")
        b.tracked_names.clear(); b.pending_commands.clear()
        owo = NS(content="tin OwO", embeds=[], components=[], author=NS(id=b.OWO_BOT_ID, bot=True),
                 channel=NS(id=77), guild=object(), reference=None, id=5)
        await b.on_message(owo)
        check("vừa khởi động (chưa biết tên) + không có lệnh -> KHÔNG đọc tin OwO", seen, [])
        b.tracked_names["1"] = {"ruby"}
        await b.on_message(owo)
        check("đã biết tên + kênh farm -> đọc mọi tin OwO", seen, ["tin OwO"])
        other = NS(**{**owo.__dict__, "channel": NS(id=99)})
        await b.on_message(other)
        check("kênh khác kênh farm -> bỏ qua", len(seen), 1)
    finally:
        b.handle_owo_response, b.bot.process_commands = old_h, old_p
asyncio.run(run_gate())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test cổng đọc tin OwO pass.")

# --- huntbot: OwO GỘP thông tin + trạng thái vào 1 tin (đúng như màn hình thật của Ruby)
def _hb_text(status_block):
    f = [("<:eff:1> Efficiency - `218/H`", "`Lvl 193 [17866/99787]` `[■■■□□□□□□□□□□□□□]`"),
         ("<:dur:2> Duration - `21.9H`", "`Lvl 214 [0/92288]` `[□□□□□□□□□□□□□□□□]`"),
         ("<:cost:3> Cost - `5 cowoncy`", "`Lvl 5 [MAX]` `[■■■■■■■■■■■■■■■■]`"),
         ("<:gain:4> Gain - `4350 essence/H`", "`Lvl 174 [38399/109010]` `[■■■■■■□□□□□□□□□□]`"),
         ("<:xp:5> Experience - `2380 xp/H`", "`Lvl 68 [0/20414]` `[□□□□□□□□□□□□□□□□]`"),
         ("<:radar:6> Radar - `0.00013 %`", "`Lvl 32 [21692/312791]` `[■■□□□□□□□□□□□□□□]`"),
         ("<:essence:7> Animal Essence - `0`", "`Current Max Autohunt: 4,774 animals, 95,265 essence, and 52,122 xp for 23,870 cowoncy`")]
    t = "**BEEP. BOOP. I AM HUNTBOT. I WILL HUNT FOR YOU MASTER.**\nUse the command `owo autohunt {cowoncy}` to get started."
    for n, v in f:
        t += f"\n**{n}:** {v}"
    return t + status_block
HB_RUNNING = "\n**HUNTBOT is currently hunting!:** `BEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 9H 51M`\n`55.02% DONE | 2626 ANIMALS CAPTURED`"
HB_IDLE_INFO_ONLY = ""

async def run_hb():
    b.mdb = AsyncMongoMockClient()["v29_hb"]
    await b.load_emoji_cache()
    now = datetime.utcnow()
    # 1) trước đó Hub tưởng huntbot KHÔNG chạy (tin thông tin cũ, không có trạng thái)
    await b.save_huntbot(b.parse_huntbot_status(_hb_text(HB_IDLE_INFO_ONLY)))
    h = await b._hub_huntbot(now)
    check("hb: tin chỉ có thông tin -> chưa kết luận đang săn", h["hunting"], False)
    # 2) tin GỘP đang săn: PHẢI cập nhật trạng thái, không chỉ chỉ số
    await b.save_huntbot(b.parse_huntbot_status(_hb_text(HB_RUNNING)))
    h = await b._hub_huntbot(datetime.utcnow())
    check("hb gộp: đang săn = True", h["hunting"], True)
    check("hb gộp: tiến độ 55.02% và 2626 con", (h["progress_pct"], h["animals_captured"]), (55.02, 2626))
    check("hb gộp: còn 9H 51M -> seconds_left ~ 9h51m", 35400 <= h["seconds_left"] <= 35460, True)
    check("hb gộp: vẫn có đủ 6 chỉ số", sorted(h["traits"]), ["cost", "duration", "efficiency", "experience", "gain", "radar"])
    # 3) tin thông tin cũ (không có trạng thái) đến sau KHÔNG được xóa trạng thái đang săn
    await b.save_huntbot(b.parse_huntbot_status(_hb_text(HB_IDLE_INFO_ONLY)))
    h = await b._hub_huntbot(datetime.utcnow())
    check("hb: tin chỉ-thông-tin đến sau không làm mất 'đang săn'", h["hunting"], True)
    # 4) tin trạng thái riêng (kiểu 2 tin cũ) vẫn chạy
    await b.save_huntbot(b.parse_huntbot_status("**BEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 1H 12M**\n94.52% DONE | 4512 ANIMALS CAPTURED"))
    h = await b._hub_huntbot(datetime.utcnow())
    check("hb: tin trạng thái riêng vẫn cập nhật", (h["hunting"], h["animals_captured"]), (True, 4512))
    # 5) huntbot về: tin gộp có 'I AM BACK WITH' -> hunting False
    await b.save_huntbot(b.parse_huntbot_status(_hb_text("\n**BEEP BOOP. I AM BACK WITH 4512 ANIMALS, 95265 ESSENCE**")))
    h = await b._hub_huntbot(datetime.utcnow())
    check("hb gộp: tin 'I AM BACK WITH' -> không còn săn", h["hunting"], False)
asyncio.run(run_hb())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test huntbot gộp pass.")

# --- chế độ Event: slot thứ 4 = gem Special
async def run_event_mode():
    from types import SimpleNamespace as NS
    from unittest.mock import AsyncMock
    b.mdb = AsyncMongoMockClient()["v29_evmode"]
    await b.load_emoji_cache()
    b.gem_missing_streak.clear()
    check("event mode: mặc định TẮT", await b.get_event_mode(), False)
    # kho có gem Special (cstar) + đang dùng 3 gem thường
    await b.mdb[b.COL_INVENTORY].insert_many([
        {"_id": "079", "is_gem": True, "gem_slot": "star", "gem_tier": "Common", "gem_tier_rank": 1, "count": 2, "name": "cstar"}])
    three = ("**🌱 | Ruby**, hunt is empowered by <:cgem1:492572122120585240>`[57/100]` "
             "<:rgem3:510366792653340674>`[20/50]` <:ugem4:510366764249382922>`[9/30]`  !\n"
             "**<:blank:427371936482328596> |** You found:  :bee:")
    gs = b.parse_hunt_gem_status(three)
    await b.save_gem_status(gs, "u1"); await b.save_gem_status(gs, "u1")
    out = await b.save_gem_status(gs, "u1")
    check("event TẮT: không bao giờ coi thiếu slot star", "star" in out, False)
    # BẬT
    await b.set_event_mode(True)
    check("event mode: bật được", await b.get_event_mode(), True)
    r1 = await b.save_gem_status(gs, "u1")
    check("event BẬT: tin hunt 1 chưa xác nhận (chờ tin thứ 2)", "star" in r1, False)
    r2 = await b.save_gem_status(gs, "u1")
    check("event BẬT: sau 2 tin hunt thiếu gem Special -> xác nhận thiếu slot star", "star" in r2, True)
    msg = NS(channel=NS(send=AsyncMock()))
    await b.remind_gem_replacements(msg, {"star"}, "u1")
    cmd = await b.mdb[b.COL_AUTOMACRO_COMMANDS].find_one({"action": "swap_gem", "status": "pending"})
    check("event BẬT: tạo lệnh dùng gem Special", cmd and cmd["params"]["command_text"], "owo use 079")
    # TẮT lại: không tạo lệnh cho star dù slot star báo thiếu
    await b.mdb[b.COL_AUTOMACRO_COMMANDS].delete_many({})
    await b.set_event_mode(False)
    await b.remind_gem_replacements(msg, {"star"}, "u1")
    n = await b.mdb[b.COL_AUTOMACRO_COMMANDS].count_documents({"action": "swap_gem"})
    check("event TẮT: không tạo lệnh gem Special", n, 0)
    # đã đang dùng star thì không coi là thiếu
    await b.set_event_mode(True)
    four = three.replace("`[9/30]`  !", "`[9/30]` <:cstar:1101731000721096744>`[5/10]`  !")
    out = await b.save_gem_status(b.parse_hunt_gem_status(four), "u1")
    check("event BẬT + đang dùng star -> không thiếu", "star" in out, False)

    # API
    b.AUTOMACRO_API_TOKEN = "tok"
    class Req:
        def __init__(self, body, token="tok"):
            self.headers = {"Authorization": f"Bearer {token}"}; self._b = body
        async def json(self):
            return self._b
    ok = await b.handle_post_event_mode(Req({"enabled": False}))
    check("API /event-mode: tắt được", (ok.status, await b.get_event_mode()), (200, False))
    ok = await b.handle_post_event_mode(Req({"enabled": True}))
    check("API /event-mode: bật được", (ok.status, await b.get_event_mode()), (200, True))
    bad = await b.handle_post_event_mode(Req({"enabled": "yes"}))
    check("API /event-mode: giá trị sai -> 400", bad.status, 400)
    noauth = await b.handle_post_event_mode(Req({"enabled": False}, token="sai"))
    check("API /event-mode: sai token -> 401 và không đổi", (noauth.status, await b.get_event_mode()), (401, True))
    hub = await b.build_hub()
    check("hub có khóa event_mode", hub.get("event_mode"), True)
asyncio.run(run_event_mode())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test chế độ Event pass.")

# --- zoo: OwO chia 3 tin, tin có tiêu đề đến CUỐI (mẫu thật rawdump 2026-10-10)
import json as _json, os as _os
_FX = _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "fixtures_zoo_2026-10-10.json"), encoding="utf-8"))

async def run_zoo():
    b.mdb = AsyncMongoMockClient()["v29_zoo"]
    await b.load_emoji_cache()
    async def feed(order, ch=1):
        out = None
        for k in order:
            _, out = await b.handle_zoo_text(ch, _FX[k], "u")
        return out
    # A) thứ tự thật: tin điểm -> tin giữa -> tin tiêu đề
    mg = await feed(["points_part", "middle_part", "header"], ch=1)
    names = [p["name"] for p in mg["pets"]]
    check("zoo (thứ tự thật, tiêu đề đến cuối): đủ 89 loài", len(mg["pets"]), 89)
    check("zoo: có Zoo Points 16,284,290", mg["zoo_points"], 16284290)
    check("zoo: không trùng tên", len(names), len(set(n.lower() for n in names)))
    check("zoo: đã thấy tin tiêu đề", mg["has_header"], True)
    # B) thứ tự cũ: tiêu đề trước
    mg2 = await feed(["header", "middle_part", "points_part"], ch=2)
    check("zoo (thứ tự cũ, tiêu đề trước): vẫn đủ 89 loài + points", (len(mg2["pets"]), mg2["zoo_points"]), (89, 16284290))
    # C) gõ zoo lần 2 ngay sau lần 1: bắt đầu lại, không nhân đôi
    mg3 = await feed(["points_part", "middle_part", "header"], ch=1)
    check("zoo gõ lần 2: vẫn 89 loài, không nhân đôi", len(mg3["pets"]), 89)
    # D) pet mới: chỉ tiêu đề (thiếu 2 tin còn lại) -> KHÔNG kết luận (trước đây báo nhầm 35 loài)
    b.zoo_session.clear()
    await b.mdb[b.COL_ZOO].delete_many({})
    await feed(["header"], ch=3)
    mid_pet = next(p["name"] for p in (await b.handle_zoo_text(99, _FX["middle_part"], "u"))[1]["pets"] if p["count"] >= 0)
    await b.mdb[b.COL_ZOO].delete_many({}); b.zoo_session.clear()
    await feed(["header"], ch=3)
    old = (datetime.utcnow().replace(microsecond=0)).isoformat()
    await b.mdb[b.COL_ZOO].update_one({"_id": "latest"}, {"$set": {"updated_at": "2000-01-01T00:00:00"}})
    check("zoo chỉ có tin tiêu đề -> không kết luận pet mới", await b.record_new_pets({"animals": [{"name": mid_pet}]}, "u"), None)
    # E) đủ 3 tin + đã ổn định: pet có trong tin giữa KHÔNG bị báo mới; pet lạ thì báo
    b.zoo_session.clear(); await b.mdb[b.COL_ZOO].delete_many({})
    await feed(["points_part", "middle_part", "header"], ch=4)
    check("zoo vừa cập nhật (<10s) -> chưa kết luận", await b.record_new_pets({"animals": [{"name": mid_pet}]}, "u"), None)
    await b.mdb[b.COL_ZOO].update_one({"_id": "latest"}, {"$set": {"updated_at": "2000-01-01T00:00:00"}})
    check("zoo đủ: pet cũ ở tin giữa KHÔNG báo nhầm", await b.record_new_pets({"animals": [{"name": mid_pet}]}, "u"), [])
    check("zoo đủ: pet thật sự lạ vẫn được báo", await b.record_new_pets({"animals": [{"name": "pet_chua_tung_co"}]}, "u"), ["pet_chua_tung_co"])
asyncio.run(run_zoo())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test ghép zoo pass.")

# --- loi khuyen vu khi: app gui nguyen chu man hinh sau khi go `?tag <vu khi>` trong server OwO
def _screen(tag, reply_lines, noise_before=("Ruby, 20:01", "Oah", "OwO, 20:01")):
    return "\n".join(list(noise_before) + [f"?tag {tag}", "OwO, Ứng Dụng Đã Xác Minh, 20:02"] + reply_lines)

SHIELD = ["105 105shield — Defender's Aegis (Shield)", "Look for stats close to:", "WP Cost: 150-160 stat3wp",
          "Taunt: 47-50% ABtaunt",
          "Recommended Passives: PShgenPSkazePSthornsPSsproutPSfarmor (PSsacrifice only with 114rstaff)",
          "Ideal pets:", "Pure Tanks: high stat6hp and stat1mr/stat4pr - bot2lobster", "more"]
DAGGER = ["108 108pdagger — Poison Dagger", "WP Cost: 100-120 stat3wp",
          "Recommended Passives: PSmtapPScritPSmag(PSsacrifice only with 114rstaff) (PSgslayerPSsguardPSlifesteal only against bosses)",
          "Ideal pets:", "MAG Attackers: high stat2mag"]
HEAL = ["102 102hstaff — Healing Staff", "WP Cost: 150-160 stat3wp", "Recommended Passives: PSwgen",
        "Ideal pets:", "⚠️ This weapon has very limited viability and is not relevant in many setups.",
        "⚠️ This weapon is not recommended for beginners."]
GLUED = ["114 114rstaff — Resurrection Staff", "Recommended Passives: PShgenPSdischarge(PSsacrificeonly with high stat3wp pets)", "Ideal pets:"]

pa = b.parse_weapon_advice(b.slice_advice_reply("shield", _screen("shield", SHIELD)))
check("advice shield: mã + tên", (pa["code"], pa["name"]), ("105", "Defender's Aegis (Shield)"))
check("advice shield: WP cost", pa["wp_cost"], "150-160")
check("advice shield: passive khuyên dùng (emoji dính liền vẫn tách đúng)", pa["recommended"], ["hgen", "kaze", "thorns", "sprout", "farmor"])
check("advice shield: sacrifice là passive có điều kiện (chỉ với rstaff)", (pa["conditional"][0]["passives"], "only with" in pa["conditional"][0]["dieu_kien"]), (["sacrifice"], True))
pd = b.parse_weapon_advice(b.slice_advice_reply("dagger", _screen("dagger", DAGGER)))
check("advice dagger: khuyên dùng mtap/crit/mag", pd["recommended"], ["mtap", "crit", "mag"])
check("advice dagger: 2 nhóm điều kiện (rstaff, đánh boss)", [c["passives"] for c in pd["conditional"]], [["sacrifice"], ["gslayer", "sguard", "lifesteal"]])
ph = b.parse_weapon_advice(b.slice_advice_reply("hstaff", _screen("hstaff", HEAL)))
check("advice healstaff: wgen + 2 cảnh báo", (ph["recommended"], len(ph["warnings"])), (["wgen"], 2))
pg = b.parse_weapon_advice(b.slice_advice_reply("rstaff", _screen("rstaff", GLUED)))
check("advice: chữ dính 'PSsacrificeonly' vẫn tách đúng passive", pg["conditional"][0]["passives"], ["sacrifice"])
check("advice: lấy đúng phần SAU dòng `?tag` cuối (bỏ nhiễu phía trên)",
      b.slice_advice_reply("shield", _screen("shield", SHIELD)).startswith("OwO, Ứng Dụng"), True)
check("advice: không có dòng ?tag -> lấy cả màn hình", b.slice_advice_reply("zzz", "a\nb"), "a\nb")
none = b.parse_weapon_advice("Không có gì ở đây")
check("advice: tin lạ -> không bịa passive", (none["recommended"], none["co_muc_passive"]), ([], False))

async def run_advice():
    from datetime import datetime
    b.mdb = AsyncMongoMockClient()["v29_advice"]
    b.AUTOMACRO_API_TOKEN = "tok"
    sent = {}
    async def fake_send(text, filename, data):
        sent["text"], sent["filename"], sent["data"] = text, filename, data
        return True
    old = b.send_file_to_owner
    b.send_file_to_owner = fake_send
    try:
        class Req:
            def __init__(self, body, token="tok"):
                self.headers = {"Authorization": f"Bearer {token}"}; self._b = body
            async def json(self):
                return self._b
        r = await b.handle_post_weapon_advice(Req({"tags": {"Shield": _screen("shield", SHIELD), "dagger": _screen("dagger", DAGGER)}}))
        check("API /weapon-advice: lưu 2 loại", (r.status, await b.mdb[b.COL_WEAPON_ADVICE].count_documents({})), (200, 2))
        await asyncio.sleep(0.05)
        import json as _j
        payload = _j.loads(sent["data"].decode("utf-8"))
        check("bot gửi file weapon_advice.json cho Ruby", (sent["filename"], payload["so_tag"]), ("weapon_advice.json", 2))
        check("file có passive đã tách + chữ gốc", (payload["tags"]["shield"]["parsed"]["recommended"][:2], "Defender" in payload["tags"]["shield"]["raw_reply"]), (["hgen", "kaze"], True))
        check("tên tag được chuẩn hóa chữ thường", sorted(payload["tags"]), ["dagger", "shield"])
        bad = await b.handle_post_weapon_advice(Req({"tags": {}}))
        check("API /weapon-advice: rỗng -> 400", bad.status, 400)
        no = await b.handle_post_weapon_advice(Req({"tags": {"a": "b"}}, token="sai"))
        check("API /weapon-advice: sai token -> 401", no.status, 401)
    finally:
        b.send_file_to_owner = old
asyncio.run(run_advice())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test lời khuyên vũ khí pass.")

# --- chấm đội hình (2 yếu tố: chỉ số/cơ chế vũ khí + passive), huntbot xong tự chạy lại, chi tiết vũ khí
_FX2 = _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "fixtures_team_weapon_2026-10-10.json"), encoding="utf-8"))

tm = b.parse_team(_FX2["team_raw"])
check("team: đọc 3 pet + loại vũ khí/độ hiếm/passive", [(m["weapon_emoji"], m["weapon_rarity"], m["passive_emojis"]) for m in tm],
      [("mrstaff", "mythic", ["msac"]), ("erstaff", "epic", ["esac"]), ("eshield", "epic", ["rsac"])])
check("team: vẫn đọc đúng chỉ số cũ", (tm[0]["hp"], tm[0]["wp"], tm[0]["weaponId"], tm[0]["quality"]), (1148, 1076, "C2PRPT", 82.7))
wd = b.parse_weapon_detail(_FX2["weapon_raw"])
check("vũ khí: chi phí WP, giá bán (cowoncy/ws), độ hiếm, wear", (wd["wp_cost"], wd["sell_cowoncy"], wd["sell_ws"], wd["rarity"], wd["wear"]), (125, 900, 37, "epic", "WORN"))
orb = b.parse_weapon_advice(b.slice_advice_reply("orb", _json.load(open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "fixtures_weapon_advice_2026-10-11.json"), encoding="utf-8"))["tags"]["orb"]["raw_screen"]))
check("lời khuyên orb: passive sau 'not with' chỉ là ghi chú", orb["conditional"][0]["passives"], ["sacrifice", "kaze"])
check("lời khuyên orb: mã/tên + 2 vai trò (STR Attacker, HP Tank)", (orb["code"], orb["name"], [r["role"] for r in orb["roles"]]), ("106", "Orb of Potency", ["STR Attacker", "HP Tank"]))
rules = b.load_weapon_rules(force=True)
check("bộ luật: 28 loại + Rune không bao giờ dismantle", (len(rules["types"]), rules["never_dismantle"]), (28, ["118", "122"]))

async def run_team():
    from datetime import datetime, timedelta
    b.mdb = AsyncMongoMockClient()["v29_team"]
    await b.load_emoji_cache()
    await b.save_team(tm)
    txt, res = await b.build_team_check()
    check("teamcheck: cả 3 pet dùng sacrifice -> hợp 3/3 (bạn chọn cho shield/rstaff)", [r["passive_verdict"] for r in res], ["ruby", "ruby", "ruby"])
    check("teamcheck: tiêu đề 3/3", "passive hợp: 3/3" in txt, True)
    check("teamcheck: có chấm chất lượng 🟢 🟢 🟡", ("🟢 xuất sắc" in txt and "🟡 khá" in txt), True)
    check("teamcheck: có số lượt dùng ước tính theo WP điển hình", "lượt" in txt, True)
    check("teamcheck: không có ❌", "❌" not in txt, True)
    # đổi passive pet 3 thành crit (không khuyên cho shield) -> báo cần xem lại
    bad = [dict(m) for m in tm]; bad[2]["passive_emojis"] = ["rcrit"]
    await b.save_team(bad)
    txt2, res2 = await b.build_team_check()
    check("teamcheck: passive crit trên shield -> ❌ + nêu tên pet cần xem lại", (res2[2]["passive_verdict"], "cần xem lại" in txt2), ("no", True))
    # có chi tiết cây vũ khí -> dùng chi phí thật
    await b.save_team(tm)
    await b.mdb[b.COL_WEAPON_INSTANCES].insert_one({"_id": "C2PRPT", "wp_cost": 315, "quality": 82.7})
    txt3, _ = await b.build_team_check()
    check("teamcheck: có chi tiết cây -> 'tốn 315 WP, đủ khoảng 3 lượt'", "tốn 315 WP" in txt3 and "khoảng 3 lượt" in txt3, True)
    # đội hình cũ chưa có loại vũ khí
    old = [{k: v for k, v in m.items() if k not in ("weapon_emoji", "weapon_rarity", "passive_emojis")} for m in tm]
    await b.save_team(old)
    txt4, _ = await b.build_team_check()
    check("teamcheck: dữ liệu cũ thiếu loại vũ khí -> nhắc gõ owo team lại, không sập", "owo team" in txt4, True)
asyncio.run(run_team())

async def run_hb_idle():
    from datetime import datetime, timedelta
    b.mdb = AsyncMongoMockClient()["v29_hbidle"]
    await b.load_emoji_cache()
    notes = []
    async def fake_notify(text, **kw):
        notes.append(text); return True
    old_n = b.notify_owner
    b.notify_owner = fake_notify
    try:
        # 1) đang săn, chưa tới giờ xong -> tin chỉ-thông-tin KHÔNG làm đổi trạng thái
        now = datetime.utcnow()
        await b.mdb[b.COL_HUNTBOT].insert_one({"hunting": True, "time_remaining": "1H 0M", "status_at": now.isoformat(), "created_at": now.isoformat(), "traits": {"cost": 5}})
        r = await b.save_huntbot(b.parse_huntbot_status(_hb_text("")))
        check("hb: chưa tới giờ xong, tin chỉ-thông-tin -> không coi là rảnh", r, None)
        # 2) đã quá giờ xong + tin gộp KHÔNG còn chữ 'currently hunting' -> huntbot rảnh
        old_t = (now - timedelta(hours=2)).isoformat()
        await b.mdb[b.COL_HUNTBOT].insert_one({"hunting": True, "time_remaining": "1H 0M", "status_at": old_t, "created_at": old_t, "traits": {"cost": 5}})
        r = await b.save_huntbot(b.parse_huntbot_status(_hb_text("")))
        row = await b.mdb[b.COL_HUNTBOT].find_one(sort=[("_id", -1)])
        check("hb: quá giờ xong + trang không còn trạng thái săn -> 'idle', hunting=False", (r, row["hunting"]), ("idle", False))
        # 3) tin 'I AM BACK WITH' cũng là idle
        r = await b.save_huntbot(b.parse_huntbot_status(_hb_text("\n**BEEP BOOP. I AM BACK WITH 4512 ANIMALS, 95265 ESSENCE**")))
        check("hb: tin 'I AM BACK WITH' -> idle", r, "idle")
        # 4) tự nhờ app chạy lại huntbot: lần 1 được, lần 2 trong 30 phút thì không, tắt thì không
        b.hb_pending["at"] = 0.0
        check("hb auto: lần 1 -> nhờ app gõ owo hb 24h", await b.maybe_auto_hb_restart("u"), True)
        cmd = await b.mdb[b.COL_AUTOMACRO_COMMANDS].find_one({"action": "hb_start"})
        check("hb auto: lệnh app = 'owo hb 24h' + nhắn acc phụ", (cmd["params"]["command_text"], bool(notes)), ("owo hb 24h", True))
        check("hb auto: lần 2 trong 30 phút -> không lặp", await b.maybe_auto_hb_restart("u"), False)
        await b.set_config("hb_auto_last", "0"); await b.set_config("hb_auto", "off")
        check("hb auto: đã tắt (,hbauto off) -> không làm", await b.maybe_auto_hb_restart("u"), False)
    finally:
        b.notify_owner = old_n
asyncio.run(run_hb_idle())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test chấm đội hình + huntbot rảnh pass.")
