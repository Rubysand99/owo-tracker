"""
test_parsers.py
================
Test 2 lớp:
  1. Parser thuần (regex) — không cần DB, dùng dữ liệu mẫu thật từ ảnh
     chụp màn hình đã gửi trong lúc trò chuyện.
  2. Lưu/đọc MongoDB — dùng mongomock-motor (giả lập, cùng interface
     với motor thật) để test toàn bộ chu trình save_*/get_* mà không
     cần kết nối MongoDB thật.

Chạy: python test_parsers.py
"""
import asyncio
from mongomock_motor import AsyncMongoMockClient

import owo_tracker_bot as bot_mod

PASS = "✅"
FAIL = "❌"
failures = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"{PASS if ok else FAIL} {label}")
    if not ok:
        print(f"   Mong đợi: {expected}")
        print(f"   Thực tế:  {actual}")
        failures.append(label)


# ========================================================================
# 1. PARSER THUẦN
# ========================================================================
print("\n=== Parser thuần ===")

check("parse_battle_result", bot_mod.parse_battle_result(
    "You won in 4 turns! | +2,200 xp | Streak: 5"
), {"result": "won", "turns": 4, "xp": 2200, "streak": 5})

check("parse_huntbot_status", bot_mod.parse_huntbot_status("""BEEP. BOOP. I AM HUNTBOT.
Animal Essence - 0
HUNTBOT is currently hunting!
BEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 9H 41M
55.58% DONE | 2580 ANIMALS CAPTURED"""), {
    "essence": 0, "hunting": True, "progress_pct": 55.58,
    "animals_captured": 2580, "time_remaining": "9H 41M",
})

check("parse_quest_status", bot_mod.parse_quest_status("""@Ruby's Quest Log
Balance: 6 Quest Seals
UwU You finished all of your quests! Come back tomorrow! <3
Next quest: 19 gio toi"""), {"seals": 6, "all_done": True, "next_quest": "19 gio toi"})

check("parse_owodex", bot_mod.parse_owodex("""*Forever petrified in this golden state, the owl is always watching you.*

**Count:** 0/63
**Rank:** legendary
**Rarity:** 24,508,696 total caught
**Alias:** gowl, owl
**Points:** 10000
**Sell:** 15000 Cowoncy | 10 sold
**Sacrifice:** 10000 Essence | 53 killed
HP `10` ATT `1` PR `3`
WP `1` MAG `2` MR `3`"""), {
    "name": "gowl", "aliases": ["gowl", "owl"], "rank": "Legendary", "rank_vi": "Huyền thoại",
    "stats": [10, 1, 3, 1, 2, 3], "count": "0/63",
    "flavor_text": "Forever petrified in this golden state, the owl is always watching you.",
    "rarity_caught": "24,508,696", "points": 10000,
    "sell_cowoncy": 15000, "sell_sold_count": 10,
    "sacrifice_essence": 10000, "sacrifice_killed_count": 53,
})

# Pet không bán/hy sinh được (OwO hiện "???" thay vì số) — không được vỡ,
# phải trả None cho các trường đó thay vì crash hoặc gán nhầm số.
pet_unsellable = bot_mod.parse_owodex("""**Count:** 0/1
**Rank:** hidden
**Alias:** hsnake, snake
**Sell:** ???
**Sacrifice:** 500000 Essence | 1 killed
HP `2` ATT `13` PR `3`
WP `1` MAG `1` MR `2`""")
check("parse_owodex: pet không bán được -> sell = None (không crash)",
      (pet_unsellable["sell_cowoncy"], pet_unsellable["sell_sold_count"]), (None, None))
check("parse_owodex: sacrifice vẫn đọc đúng dù sell là ???",
      pet_unsellable["sacrifice_essence"], 500000)

print("\n=== Dịch tiếng Việt (translate_effect_text) ===")
TRANSLATE_CASES = [
    ("Deals 97.6% of your STR to an enemy and apply Mortality for 2 turns.",
     "Gây 97.6% STR lên 1 địch và áp Mortality trong 2 lượt."),
    ("Deals 50.4% of your STR to all opponents.", "Gây 50.4% STR lên TẤT CẢ địch."),
    ("Deal 43% of your MAG to ALL enemies and heal ALL allies by the damage dealt.",
     "Gây 43% MAG lên TẤT CẢ địch, đồng thời hồi máu TẤT CẢ đồng minh bằng đúng lượng damage vừa gây ra."),
    ("At the start of the turn, apply Taunt to your animal for 2 turns.",
     "Đầu mỗi lượt, tự áp Taunt lên bản thân trong 2 lượt."),
    ("Increases your PR by 33.8%.", "Tăng PR thêm 33.8%."),
    ("Increases your STR by 17.45%.", "Tăng STR thêm 17.45%."),
    ("Increases your WP by 29%.", "Tăng WP thêm 29%."),
    ("Decreases all healing for this animal by -74.7%.", "Giảm 74.7% hồi máu nhận vào."),
    ("Deal +23.95% more damage to bosses.", "Gây thêm 23.95% sát thương khi đánh boss."),
]
for en, vi in TRANSLATE_CASES:
    check(f"dịch: {en[:40]}...", bot_mod.translate_effect_text(en), vi)

check("dịch: câu lạ chưa từng thấy -> giữ nguyên None (không đoán bừa)",
      bot_mod.translate_effect_text("Some brand new weapon effect never seen before."), None)

# Mẫu ĐẦY ĐỦ: có cả hiệu ứng cố định (Mortality) LẪN passive roll thật (Giant Slayer)
weapon_full = bot_mod.parse_weapon_detail("""## Ruby's Culling Scythe [2]
**Name:** Culling Scythe
**ID:** `FJJ8N2`
**Quality:** 95.2%

Deals 97.6% of your STR to an enemy and apply Mortality for 2 turns.
> **__Mortality__** - Decreases all healing for this animal by -74.7%.

**__Giant Slayer__** - Deal +23.95% more damage to bosses.
Reroll Changes: 0""")
check("parse_weapon_detail: id", weapon_full["id"], "FJJ8N2")
check("parse_weapon_detail: quality", weapon_full["quality"], 95.2)
check("parse_weapon_detail: passive roll (KHÔNG được lấy nhầm Mortality)",
      weapon_full["passive"], {"name": "Giant Slayer", "desc": "Deal +23.95% more damage to bosses."})
check("parse_weapon_detail: hiệu ứng cố định tách riêng đúng",
      weapon_full["inherent_effects"],
      [{"name": "Mortality", "desc": "Decreases all healing for this animal by -74.7%."}])

# Mẫu chỉ có 1 block duy nhất (Great Sword) — không có hiệu ứng cố định riêng
weapon_simple = bot_mod.parse_weapon_detail("""## Ruby's Great Sword
**Name:** Great Sword
**ID:** `FEGHU5`
**Quality:** 74.3%

Deals 50.4% of your STR to all opponents.

**__Strength__** - Increases your STR by 17.45%.""")
check("parse_weapon_detail (1 block): passive", weapon_simple["passive"],
      {"name": "Strength", "desc": "Increases your STR by 17.45%."})
check("parse_weapon_detail (1 block): không có hiệu ứng cố định thừa",
      weapon_simple["inherent_effects"], [])

team = bot_mod.parse_team("""[1] slothbot
Lvl 26 [181,880/457,976]
968 916
100 100
45% 45%
`C2PRPT` 82.7%""")
check("parse_team: hp/wp/att/mag/pr/mr đúng thứ tự",
      {k: team[0][k] for k in ("hp", "wp", "att", "mag", "pr", "mr")},
      {"hp": 968, "wp": 916, "att": 100, "mag": 100, "pr": 45, "mr": 45})
check("parse_team: quality không lẫn với PR/MR", team[0]["quality"], 82.7)
check("parse_team: weaponId không lẫn số liệu", team[0]["weaponId"], "C2PRPT")


# ========================================================================
# 2. LƯU / ĐỌC MONGODB (giả lập)
# ========================================================================
print("\n=== MongoDB (giả lập qua mongomock-motor) ===")


async def run_db_tests():
    fake_client = AsyncMongoMockClient()
    bot_mod.mdb = fake_client["owo_tracker_test"]

    await bot_mod.set_config("tracked_user_id", "111222333")
    val = await bot_mod.get_config("tracked_user_id")
    check("config set/get", val, "111222333")

    pet = bot_mod.parse_owodex("""**Count:** 0/63
**Rank:** legendary
**Alias:** gowl, owl
HP `10` ATT `1` PR `3`
WP `1` MAG `2` MR `3`""")
    await bot_mod.save_pet_species(pet, "111222333")
    doc = await bot_mod.mdb[bot_mod.COL_PET_SPECIES].find_one({"_id": "gowl"})
    check("pet species lưu đúng", (doc["display_name"], doc["hp"], doc["rank"]), ("gowl", 10, "Legendary"))

    await bot_mod.save_pet_species(pet, "111222333")
    count = await bot_mod.mdb[bot_mod.COL_PET_SPECIES].count_documents({"_id": "gowl"})
    check("pet species upsert không tạo trùng", count, 1)

    await bot_mod.save_weapon_type(weapon_full, "111222333")
    await bot_mod.save_weapon_instance(weapon_full, "111222333")
    await bot_mod.save_passive(weapon_full["passive"]["name"], weapon_full["passive"]["desc"], "111222333")
    for eff in weapon_full["inherent_effects"]:
        await bot_mod.save_passive(eff["name"], eff["desc"], "111222333")

    wtype = await bot_mod.mdb[bot_mod.COL_WEAPON_TYPES].find_one({"_id": "culling scythe"})
    check("weapon type lưu đúng inherent_effects (kèm bản dịch)", wtype["inherent_effects"],
          [{"name": "Mortality", "desc": "Decreases all healing for this animal by -74.7%.",
            "desc_vi": "Giảm 74.7% hồi máu nhận vào."}])

    winst = await bot_mod.mdb[bot_mod.COL_WEAPON_INSTANCES].find_one({"_id": "FJJ8N2"})
    check("weapon instance lưu đúng passive (không lẫn Mortality)", winst["passive_name"], "Giant Slayer")
    check("weapon instance lưu bản dịch passive", winst["passive_desc_vi"],
          "Gây thêm 23.95% sát thương khi đánh boss.")

    passive_doc = await bot_mod.mdb[bot_mod.COL_PASSIVES].find_one({"_id": "giant slayer"})
    check("passive Giant Slayer được lưu", passive_doc["display_name"], "Giant Slayer")
    check("passive Giant Slayer có bản dịch", passive_doc["description_vi"],
          "Gây thêm 23.95% sát thương khi đánh boss.")
    mortality_doc = await bot_mod.mdb[bot_mod.COL_PASSIVES].find_one({"_id": "mortality"})
    check("hiệu ứng Mortality cũng được lưu vào passives", mortality_doc["display_name"], "Mortality")

    pet_doc = await bot_mod.mdb[bot_mod.COL_PET_SPECIES].find_one({"_id": "gowl"})
    check("pet species lưu rank_vi", pet_doc["rank_vi"], "Huyền thoại")
    check("pet species lưu đủ alias (không chỉ tên đầu)", pet_doc["aliases"], ["gowl", "owl"])

    battle = bot_mod.parse_battle_result("You won in 4 turns! | +2,200 xp | Streak: 5")
    await bot_mod.save_battle(battle)
    battle2 = bot_mod.parse_battle_result("You won in 6 turns! | +2,200 xp | Streak: 4")
    await bot_mod.save_battle(battle2)
    cursor = bot_mod.mdb[bot_mod.COL_BATTLES].find().sort("_id", -1)
    rows = await cursor.to_list(length=10)
    check("battle log lưu đúng thứ tự (mới nhất trước)", [r["turns"] for r in rows], [6, 4])

    nid1 = await bot_mod.next_note_id()
    nid2 = await bot_mod.next_note_id()
    check("note counter tự tăng", (nid1, nid2), (1, 2))


asyncio.run(run_db_tests())

print("\n=== Zoo / Inventory / Gem (mới) ===")

check("decode_superscript_number", [bot_mod.decode_superscript_number(s) for s in ["¹¹⁰", "⁰⁶⁸", "⁰⁰¹", "¹⁰⁴", "⁰⁰⁰"]],
      [110, 68, 1, 104, 0])

zoo_result = bot_mod.parse_zoo("""🌿 🌱 🌳 Ruby's zoo! 🌳 🌿 🌱
<:common:416520037713838081>   :bee:¹¹⁰  :bug:¹¹³  :snail:¹³²  :beetle:¹¹³  :butterfly:¹¹⁹  
<:patreon:449705754522419222>    <:pbird:449867323990343690>⁰⁰¹  <:pdolphin:449867323898068992>⁰⁰¹  
<:special:427935192137859073>    <a:2024nov_diwaliOwO:1301754663892422746>⁰⁰⁰  
<:blank:427371936482328596>    <a:2025may_sportsdayowo:1377197478868418570>⁰⁰⁰  
**Zoo Points: __11,272,674__**
\t**F-3, CP-1, B-1, G-60, L-322, P-164, M-696, S-82, E-6509, R-58287, U-173131, C-340666** """)
check("parse_zoo: tổng số pet", len(zoo_result["pets"]), 9)
check("parse_zoo: zoo_points", zoo_result["zoo_points"], 11272674)
check("parse_zoo: dòng blank nối đúng về tier trước (special)",
      [p for p in zoo_result["pets"] if p["name"] == "2025may_sportsdayowo"][0]["tier"], "special")
check("parse_zoo: số lượng bee đúng", [p for p in zoo_result["pets"] if p["name"] == "bee"][0]["count"], 110)

inv_text = """`051`<:cgem1:492572122120585240>¹⁰⁴    `052`<:ugem1:492572122514980864>⁰⁹⁷    `053`<:rgem1:492572122888011776>¹⁰³
`100`<:crate:523771259302182922>⁰⁰⁵"""
inv_result = bot_mod.parse_inventory("Ruby's Inventory\n" + inv_text)
check("parse_inventory: tổng số item", len(inv_result["items"]), 4)
gem_items = [i for i in inv_result["items"] if i["is_gem"]]
check("parse_inventory: nhận diện đúng 3 gem (kể cả rgem1 — từng bị bỏ sót)", len(gem_items), 3)
check("parse_inventory: rgem1 -> tier Rare, slot 1",
      [i for i in inv_result["items"] if i["name"] == "rgem1"][0]["gem_tier"], "Rare")
check("parse_inventory: item thường (crate) is_gem=False",
      [i for i in inv_result["items"] if i["name"] == "crate"][0]["is_gem"], False)

hunt_text = "Ruby, hunt is empowered by <:cgem1:492572122120585240>[47/75] <:rgem3:510366792653340674>[300/525] !"
hunt_result = bot_mod.parse_hunt_gem_status(hunt_text)
check("parse_hunt_gem_status: số gem đang trang bị", len(hunt_result["gems"]), 2)
check("parse_hunt_gem_status: slot + độ bền đúng",
      [(g["slot"], g["current"], g["max"]) for g in hunt_result["gems"]],
      [("1", 47, 75), ("3", 300, 525)])


async def run_gem_reminder_scenario():
    """Mô phỏng đúng kịch bản thật: gem slot 1 đang [5/75] ở lần hunt
    trước, lần hunt sau BIẾN MẤT (hết độ bền) — bot phải phát hiện và
    tìm đúng lựa chọn thay thế trong inventory."""
    fake_client = AsyncMongoMockClient()
    bot_mod.mdb = fake_client["gem_test"]

    inv = bot_mod.parse_inventory("Ruby's Inventory\n" + inv_text)
    await bot_mod.save_inventory(inv, "u1")

    gs1 = bot_mod.parse_hunt_gem_status(
        "hunt is empowered by <:cgem1:492572122120585240>[5/75] <:rgem3:510366792653340674>[300/525] !"
    )
    vanished1 = await bot_mod.save_gem_status(gs1, "u1")
    check("gem reminder: lần đầu quan sát, chưa có slot nào biến mất", vanished1, set())

    gs2 = bot_mod.parse_hunt_gem_status(
        "hunt is empowered by <:rgem3:510366792653340674>[295/525] !"
    )
    vanished2 = await bot_mod.save_gem_status(gs2, "u1")
    check("gem reminder: phát hiện đúng slot 1 vừa biến mất", vanished2, {"1"})

    options = await bot_mod.mdb[bot_mod.COL_INVENTORY].find(
        {"is_gem": True, "gem_slot": "1", "count": {"$gt": 0}}
    ).sort("gem_tier_rank", 1).to_list(length=10)
    check("gem reminder: tìm đúng mã thay thế, ưu tiên tier thấp trước",
          [o["_id"] for o in options], ["051", "052", "053"])


asyncio.run(run_gem_reminder_scenario())


# ========================================================================
# 3. HUB — tong hop du lieu cho man hinh Hub trong app AutoMacro
# ========================================================================
print("\n=== Hub (API cho app AutoMacro) ===")

import json
from datetime import datetime, timedelta
from aiohttp.test_utils import make_mocked_request

check("duration_to_seconds: 1H 23M", bot_mod.duration_to_seconds("1H 23M"), 4980)
check("duration_to_seconds: 23H 5M 10S", bot_mod.duration_to_seconds("23H 5M 10S"), 83110)
check("duration_to_seconds: chuoi rong / None / khong doc duoc",
      (bot_mod.duration_to_seconds(""), bot_mod.duration_to_seconds(None), bot_mod.duration_to_seconds("abc")),
      (None, None, None))


async def run_hub_tests():
    now = datetime(2026, 9, 24, 12, 0, 0)
    ago = lambda minutes: (now - timedelta(minutes=minutes)).isoformat()

    # --- DB rong: moi muc phai la null, khong loi ---
    bot_mod.mdb = AsyncMongoMockClient()["hub_empty"]
    empty = await bot_mod.build_hub(now)
    check("hub: DB rong -> moi muc = null",
          [empty[k] for k in ("gems", "huntbot", "quest", "team", "battles", "zoo", "inventory", "weapons")],
          [None] * 8)

    # --- DB co du lieu ---
    db = AsyncMongoMockClient()["hub_full"]
    bot_mod.mdb = db

    inv = bot_mod.parse_inventory("Ruby's Inventory\n" + inv_text)
    await bot_mod.save_inventory(inv, "u1")
    await db[bot_mod.COL_GEM_STATUS].insert_one({
        "_id": "1", "tier": "Common", "emoji_name": "cgem1", "current": 47, "max": 75,
        "updated_at": ago(10)})
    await db[bot_mod.COL_HUNTBOT].insert_one({
        "hunting": True, "progress_pct": 40.0, "animals_captured": 120, "essence": 500,
        "time_remaining": "1H 30M", "created_at": ago(30)})
    await db[bot_mod.COL_QUEST].insert_one({
        "seals": 3, "all_done": False, "next_quest": "Hunt 5 animals", "created_at": ago(60)})
    await bot_mod.save_team([{"pos": 1, "name": "gowl", "level": 10, "weaponId": "ABC123",
                              "quality": 88.5, "hp": 100, "wp": 20, "att": 30, "mag": 5, "pr": 1, "mr": 2}])
    for res, streak in (("won", 1), ("lost", 0), ("won", 1)):
        await db[bot_mod.COL_BATTLES].insert_one({"result": res, "turns": 4, "xp": 100,
                                                  "streak": streak, "created_at": ago(5)})
    await bot_mod.save_zoo({"pets": [
        {"tier": "common", "name": "bee", "count": 110}, {"tier": "common", "name": "bug", "count": 113},
        {"tier": "special", "name": "x", "count": 0}], "zoo_points": 1000, "breakdown_raw": "F-1"}, "u1")
    await db[bot_mod.COL_WEAPON_INSTANCES].insert_one({
        "_id": "FJJ8N2", "type_name": "Culling Scythe", "quality": 90.0, "passive_name": "Giant Slayer",
        "passive_desc": "Deals more damage to bosses.", "passive_desc_vi": "Gay them sat thuong khi danh boss.",
        "updated_at": ago(2)})

    hub = await bot_mod.build_hub(now)
    check("hub: gem dang trang bi + phan tram", (hub["gems"]["equipped"][0]["slot"], hub["gems"]["equipped"][0]["percent"]),
          ("1", 63))
    check("hub: gem du phong lay tu inventory (3 vien, xep theo tier)",
          [g["code"] for g in hub["gems"]["spare"]], ["051", "052", "053"])
    check("hub: gem age_seconds = 600", hub["gems"]["equipped"][0]["age_seconds"], 600)
    check("hub: huntbot tinh dung gio xong (con 3600s)", (hub["huntbot"]["seconds_left"], hub["huntbot"]["ready_at"]),
          (3600, "2026-09-24T13:00:00Z"))
    check("hub: huntbot age_seconds = 1800", hub["huntbot"]["age_seconds"], 1800)
    check("hub: quest", (hub["quest"]["seals"], hub["quest"]["next_quest"]), (3, "Hunt 5 animals"))
    check("hub: team", (hub["team"]["members"][0]["name"], hub["team"]["members"][0]["weaponId"]), ("gowl", "ABC123"))
    check("hub: battles thang/thua + streak moi nhat", (hub["battles"]["wins"], hub["battles"]["losses"],
                                                         hub["battles"]["current_streak"]), (2, 1, 1))
    check("hub: zoo tong pet + bo qua pet count=0",
          (hub["zoo"]["total_pets"], len(hub["zoo"]["pets"]), hub["zoo"]["by_tier"]["common"]["species"]),
          (223, 2, 2))
    check("hub: inventory dem dung", (hub["inventory"]["kinds"], hub["inventory"]["total_items"]), (4, 104 + 97 + 103 + 5))
    check("hub: weapons dung uu tien ban dich tieng Viet", hub["weapons"]["weapons"][0]["passive_desc"],
          "Gay them sat thuong khi danh boss.")
    check("hub: toan bo ket qua chuyen duoc sang JSON", isinstance(json.dumps(hub), str), True)

    # --- huntbot khong hunt -> khong co gio xong ---
    await db[bot_mod.COL_HUNTBOT].insert_one({
        "hunting": False, "progress_pct": None, "animals_captured": None, "essence": 500,
        "time_remaining": None, "created_at": ago(1)})
    hub2 = await bot_mod.build_hub(now)
    check("hub: huntbot khong hunt -> ready_at/seconds_left = None",
          (hub2["huntbot"]["hunting"], hub2["huntbot"]["ready_at"], hub2["huntbot"]["seconds_left"]),
          (False, None, None))

    # --- xac thuc token + handler that ---
    bot_mod.AUTOMACRO_API_TOKEN = "token-thu"
    r_bad = await bot_mod.handle_get_hub(make_mocked_request("GET", "/hub"))
    check("hub API: khong co token -> 401", r_bad.status, 401)
    r_wrong = await bot_mod.handle_get_hub(
        make_mocked_request("GET", "/hub", headers={"Authorization": "Bearer sai"}))
    check("hub API: sai token -> 401", r_wrong.status, 401)
    r_ok = await bot_mod.handle_get_hub(
        make_mocked_request("GET", "/hub", headers={"Authorization": "Bearer token-thu"}))
    body = json.loads(r_ok.body)
    check("hub API: dung token -> 200 + co du lieu", (r_ok.status, body["hub_version"], body["zoo"]["zoo_points"]),
          (200, 1, 1000))
    bot_mod.AUTOMACRO_API_TOKEN = None
    r_off = await bot_mod.handle_get_hub(
        make_mocked_request("GET", "/hub", headers={"Authorization": "Bearer "}))
    check("hub API: chua dat token tren server -> luon 401", r_off.status, 401)


asyncio.run(run_hub_tests())

print("\n" + ("=" * 40))
if failures:
    print(f"{FAIL} {len(failures)} test thất bại: {failures}")
else:
    print(f"{PASS} Toàn bộ test pass.")
