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
          [empty[k] for k in ("gems", "huntbot", "quest", "team", "zoo", "inventory", "weapons")],
          [None] * 7)
    check("hub: khong con muc battles", "battles" in empty, False)

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


# ========================================================================
# 4. DAILY / COWONCY / QUEST (tin nhan that tu anh chup man hinh)
# ========================================================================
print("\n=== Daily / Cowoncy / Quest / tin nhan kieu moi ===")

from types import SimpleNamespace

DAILY_WAIT = "⏱ | **Nu!** **Ruby**! You need to wait **3H 11M 28S**"
DAILY_CLAIMED = """💰 | **Ruby**, Here is your daily <:cowoncy:416043450337853441> **5000 Cowoncy**!
<:blank:427371936482328596> | You're on a **337** daily streak!
📦 | You received a **lootbox**!
⏱ | Your next daily is in: 23H 29M 17S

📮 | **Ruby**, you have **3** unread mail!"""

check("parse_daily: chua toi gio (co lenh daily)", bot_mod.parse_daily(DAILY_WAIT, "odaily"),
      {"state": "waiting", "reward": None, "streak": None, "seconds_until_next": 3 * 3600 + 11 * 60 + 28})
check("parse_daily: 'need to wait' nhung lenh KHONG phai daily -> bo qua",
      bot_mod.parse_daily(DAILY_WAIT, "owo cookie"), None)
check("parse_daily: khong biet lenh nao -> bo qua (tranh nham)", bot_mod.parse_daily(DAILY_WAIT, ""), None)
check("parse_daily: viet 'Owo daily' co dau cach", bot_mod.parse_daily(DAILY_WAIT, "owo daily")["seconds_until_next"], 11488)
check("parse_daily: da nhan (thuong, streak, gio ke tiep)", bot_mod.parse_daily(DAILY_CLAIMED, "owo daily"),
      {"state": "claimed", "reward": 5000, "streak": 337, "seconds_until_next": 23 * 3600 + 29 * 60 + 17})
check("parse_daily: da nhan — khong an nham dong 'unread mail' o cuoi",
      bot_mod.parse_daily(DAILY_CLAIMED, "")["seconds_until_next"], 84557)
check("parse_daily: tin nhan khong lien quan", bot_mod.parse_daily("Ruby, you currently have 5 cowoncy", "odaily"), None)

check("parse_cowoncy: co in dam + gach chan", bot_mod.parse_cowoncy(
    "<:cash:416043450337853441> | **Ruby**, you currently have **__2,061,145__ cowoncy**!"), {"amount": 2061145})
check("parse_cowoncy: dang tron", bot_mod.parse_cowoncy("Ruby, you currently have 2,061,145 cowoncy!"), {"amount": 2061145})
check("parse_cowoncy: tin khac", bot_mod.parse_cowoncy("Nu! You need to wait 3H"), None)

quest_v2 = bot_mod.parse_quest_status("""@Ruby's Quest Log
Complete quests to earn rewards!
Balance: **64** <:questseal:123> Quest Seals
1. Receive an action from a friend 0/3
2. Earn battle xp 0/2,000
⏰ Next quest: <t:1790000000:R>""")
check("parse_quest_status: Balance in dam (**64**) van doc duoc", quest_v2["seals"], 64)
check("parse_quest_status: lay moc thoi gian <t:...>", quest_v2.get("next_quest_epoch"), 1790000000)
check("parse_quest_status: van con quest chua xong", quest_v2["all_done"], False)


def fake_component_message(components, content=""):
    return SimpleNamespace(content=content, embeds=[], components=components,
                           channel=SimpleNamespace(id=42))


tree = [SimpleNamespace(children=[
    SimpleNamespace(content="@Ruby's Quest Log"),
    SimpleNamespace(children=[SimpleNamespace(content="Balance: **64** Quest Seals")],
                    accessory=SimpleNamespace(content="[nut]")),
    SimpleNamespace(children=[SimpleNamespace(label="Claim")]),  # hang nut bam, khong co chu
])]
flat = bot_mod.flatten_message(fake_component_message(tree, content="ngoai"))
check("flatten_message: doc chu trong Container/Section/TextDisplay long nhau",
      ("@Ruby's Quest Log" in flat, "Balance: **64** Quest Seals" in flat, "[nut]" in flat, "ngoai" in flat),
      (True, True, True, True))
check("flatten_message: tin thuong khong co components van chay",
      bot_mod.flatten_message(SimpleNamespace(content="xin chao", embeds=[])), "xin chao")


async def run_daily_flow_tests():
    db = AsyncMongoMockClient()["daily_flow"]
    bot_mod.mdb = db
    ch = 42

    # Tin quest kieu moi di qua ca luong xu ly that
    bot_mod.last_owo_command[ch] = "oq"
    quest_msg = fake_component_message([SimpleNamespace(children=[
        SimpleNamespace(content="@Ruby's Quest Log\nBalance: **64** Quest Seals\n⏰ Next quest: <t:1790000000:R>")])])
    await bot_mod.handle_owo_response(quest_msg, "u1")
    q = await db[bot_mod.COL_QUEST].find_one(sort=[("_id", -1)])
    check("luong that: tin quest kieu moi duoc doc + luu", (q["seals"], q["next_quest_epoch"]), (64, 1790000000))

    # Daily: chua toi gio
    bot_mod.last_owo_command[ch] = "odaily"
    await bot_mod.handle_owo_response(SimpleNamespace(content=DAILY_WAIT, embeds=[], components=[],
                                                      channel=SimpleNamespace(id=ch)), "u1")
    now = datetime.utcnow()
    hub = await bot_mod.build_hub(now)
    check("luong that: daily 'chua toi gio' vao hub", hub["daily"]["state"], "waiting")
    check("luong that: daily con ~3h11m (sai so vai giay)", 11400 <= hub["daily"]["seconds_left"] <= 11488, True)
    check("luong that: chua co streak/thuong khi chi thay tin cho", (hub["daily"]["streak"], hub["daily"]["last_reward"]), (None, None))

    # Daily: da nhan
    await bot_mod.handle_owo_response(SimpleNamespace(content=DAILY_CLAIMED, embeds=[], components=[],
                                                      channel=SimpleNamespace(id=ch)), "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    check("luong that: daily 'da nhan' -> streak + thuong + gio ke tiep",
          (hub["daily"]["state"], hub["daily"]["streak"], hub["daily"]["last_reward"],
           84400 <= hub["daily"]["seconds_left"] <= 84557), ("claimed", 337, 5000, True))

    # Sau do go lai daily -> tin 'cho' KHONG duoc xoa streak/thuong
    await bot_mod.handle_owo_response(SimpleNamespace(content=DAILY_WAIT, embeds=[], components=[],
                                                      channel=SimpleNamespace(id=ch)), "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    check("luong that: tin 'cho' giu nguyen streak/thuong cu",
          (hub["daily"]["state"], hub["daily"]["streak"], hub["daily"]["last_reward"]), ("waiting", 337, 5000))

    # Tin 'need to wait' cua lenh khac khong duoc tinh la daily
    before = (await db[bot_mod.COL_DAILY].find_one({"_id": "latest"}))["ready_at"]
    bot_mod.last_owo_command[ch] = "owo cookie"
    await bot_mod.handle_owo_response(SimpleNamespace(content="Nu! You need to wait **9M 5S**", embeds=[], components=[],
                                                      channel=SimpleNamespace(id=ch)), "u1")
    after = (await db[bot_mod.COL_DAILY].find_one({"_id": "latest"}))["ready_at"]
    check("luong that: 'need to wait' cua lenh khac khong ghi de daily", after, before)

    # Cowoncy
    bot_mod.last_owo_command[ch] = "owo money"
    await bot_mod.handle_owo_response(SimpleNamespace(
        content="<:cash:1> | **Ruby**, you currently have **__2,061,145__ cowoncy**!", embeds=[], components=[],
        channel=SimpleNamespace(id=ch)), "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    check("luong that: cowoncy vao hub", hub["cowoncy"]["amount"], 2061145)

    # Hub: quest co dem nguoc tu moc <t:...>
    now2 = datetime(1970, 1, 1) + timedelta(seconds=1790000000 - 600)
    hub_q = await bot_mod.build_hub(now2)
    check("hub: quest con 600 giay toi quest ke tiep, khong lo chuoi <t:...>",
          (hub_q["quest"]["next_quest_seconds"], hub_q["quest"]["next_quest"]), (600, None))
    check("hub: JSON hop le", isinstance(json.dumps(hub), str), True)


asyncio.run(run_daily_flow_tests())


# ========================================================================
# 5. QUEST tung cai (mau THAT lay tu log Railway ngay 24/09/2026)
# ========================================================================
print("\n=== Quest chi tiet ===")

QUEST_REAL = ("\n### 📜 <@846332174734983219>'s Quest Log\n-# Complete quests to earn rewards!\n"
              "-# Balance: **112** <:seal:1508740094125932614> Quest Seals\n"
              "<:blank_box:808212600533942322> **1. <:common:416520037713838081> ⚔️ Battle**\n"
              "> Battle 10 times!\n"
              "> Reward: <:cowoncy:416043450337853441> +120  •  <:seal:1508740094125932614> +12\n"
              "▰▱▱▱▱▱▱▱▱▱ `1/10`\n-# ⏰ Next quest: **<t:1790319600:R>**")
qr = bot_mod.parse_quest_status(QUEST_REAL)
check("quest that: seals / chua xong / moc ke tiep",
      (qr["seals"], qr["all_done"], qr["next_quest_epoch"]), (112, False, 1790319600))
check("quest that: 1 quest, dung ten + do hiem + mo ta", (len(qr["quests"]), qr["quests"][0]["title"],
      qr["quests"][0]["rarity"], qr["quests"][0]["description"]), (1, "Battle", "common", "Battle 10 times!"))
check("quest that: thuong (cowoncy +120, seal +12)", qr["quests"][0]["rewards"],
      [{"item": "cowoncy", "amount": 120}, {"item": "seal", "amount": 12}])
check("quest that: tien do 1/10, chua xong", (qr["quests"][0]["current"], qr["quests"][0]["max"], qr["quests"][0]["done"]),
      (1, 10, False))

QUEST_TWO = """### 📜 <@1>'s Quest Log
-# Balance: **64** <:seal:1> Quest Seals
<:blank_box:2> **1. <:rare:3> 😂 Receive an action from a friend**
> Have a friend use an action command on you 3 times!
> Reward: 📦 +2  •  <:seal:1> +12
▱▱▱▱▱▱▱▱▱▱▱▱ `0/3`
<:checked:9> **2. <:epic:4> <:xp:5> Earn battle xp**
> Earn 2000 xp from hunting
> and battling!
> Reward: <:crate:6> +2  •  <:seal:1> +12
▰▰▰▰▰▰▰▰▰▰▰▰ `2,000/2,000`
-# ⏰ Next quest: **<t:1790319600:R>**"""
q2 = bot_mod.parse_quest_status(QUEST_TWO)["quests"]
check("quest 2 cai: dem dung + ten sach emoji", (len(q2), q2[0]["title"], q2[1]["title"]),
      (2, "Receive an action from a friend", "Earn battle xp"))
check("quest 2 cai: thuong dang emoji chuan (📦) + emoji tuy chinh", (q2[0]["rewards"][0], q2[1]["rewards"][0]),
      ({"item": "📦", "amount": 2}, {"item": "crate", "amount": 2}))
check("quest 2 cai: so co dau phay 2,000/2,000 -> xong", (q2[1]["current"], q2[1]["max"], q2[1]["done"]), (2000, 2000, True))
check("quest 2 cai: mo ta nhieu dong duoc noi lai", q2[1]["description"], "Earn 2000 xp from hunting and battling!")
check("quest 2 cai: quest chua xong khong bi danh dau xong", q2[0]["done"], False)

qd = bot_mod.parse_quest_status("""### 📜 <@1>'s Quest Log
-# Balance: **112** <:seal:1> Quest Seals
UwU You finished all of your quests! Come back tomorrow! <3
-# ⏰ Next quest: **<t:1790233200:R>**""")
check("quest da xong het: khong co danh sach quest", ("quests" in qd, qd["all_done"], qd["seals"]), (False, True, 112))


async def run_quest_items_hub_test():
    db = AsyncMongoMockClient()["quest_items"]
    bot_mod.mdb = db
    bot_mod.last_owo_command[5] = "owo quest"
    await bot_mod.handle_owo_response(
        SimpleNamespace(content="", embeds=[], components=[SimpleNamespace(children=[SimpleNamespace(content=QUEST_REAL)])],
                        channel=SimpleNamespace(id=5)), "u1")
    hub = await bot_mod.build_hub(datetime(1970, 1, 1) + timedelta(seconds=1790319600 - 3600))
    hq = hub["quest"]
    check("hub: quest co danh sach + dem nguoc", (len(hq["quests"]), hq["quests"][0]["title"], hq["next_quest_seconds"]),
          (1, "Battle", 3600))
    check("hub: JSON hop le", isinstance(json.dumps(hub), str), True)


asyncio.run(run_quest_items_hub_test())


# ========================================================================
# 6. HuntBot: essence khong duoc doc nham ID emoji
# ========================================================================
print("\n=== HuntBot essence ===")
HB_TAIL = "\nHUNTBOT is currently hunting!\nBEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 9H 41M\n55.58% DONE | 2580 ANIMALS CAPTURED"
for label, head, want in (
    ("emoji dung truoc chu", "BEEP. BOOP. I AM HUNTBOT.\n<:essence:1508740094125932614> Animal Essence - 1,234", 1234),
    ("emoji nam SAU chu (truoc day doc nham ID)", "BEEP. BOOP. I AM HUNTBOT.\nAnimal Essence <:essence:1508740094125932614> - 0", 0),
    ("in dam", "BEEP. BOOP. I AM HUNTBOT.\n**Animal Essence** - 5000", 5000),
    ("mau cu", "BEEP. BOOP. I AM HUNTBOT.\nAnimal Essence - 0", 0),
):
    check("huntbot essence: " + label, bot_mod.parse_huntbot_status(head + HB_TAIL)["essence"], want)
check("huntbot: khong co dong essence -> None", bot_mod.parse_huntbot_status("BEEP. BOOP. I AM HUNTBOT." + HB_TAIL)["essence"], None)


# ========================================================================
# 7. ZOO bi OwO chia thanh 2 tin nhan (mau THAT bot gui ngay 24/09/2026)
# ========================================================================
print("\n=== Zoo nhieu tin nhan ===")

ZOO_MSG1 = """🌿 🌱 🌳** Ruby's zoo! **🌳 🌿 🌱
<:common:416520037713838081>   :bee:¹⁹⁰  :bug:²⁰²  :snail:¹⁹²  :beetle:¹⁹⁷  :butterfly:¹⁸⁵  
<:uncommon:416520056269176842>   :baby_chick:¹¹⁶  :mouse2:¹⁰⁷  :rooster:¹¹³  :rabbit2:¹⁰⁸  :chipmunk:¹⁰⁶  
<:rare:416520066629107712>   :sheep:⁰⁴⁰  :pig2:⁰⁴²  :cow2:⁰²⁹  :dog2:⁰³⁰  :cat2:⁰³⁴  
<:epic:416520722987614208>   :crocodile:⁰⁰³  :tiger2:⁰⁰³  :penguin:⁰⁰⁴  :elephant:⁰⁰²  :whale:⁰⁰³  
<:patreon:449705754522419222>    <:pbird:449867323990343690>⁰⁰⁴  <:pdolphin:449867323898068992>⁰⁰³  <:pogre:449705625681788958>⁰⁰¹  <:pscorpion:449704671721029632>⁰⁰¹  <:ptiger:449703897980993545>⁰⁰²  
<:special:427935192137859073>    <a:2024nov_diwaliOwO:1301754663892422746>⁰⁰⁰  <a:2024nov_tiago:1301754667633606657>⁰⁰⁰  <a:2025aug_clowncat:1409782335620120587>⁰⁰⁰  <a:2025aug_cuba:1409486185813901332>⁰⁰⁰  <a:2025aug_worldwideweb:1409486209914376192>⁰⁰⁰  
<:blank:427371936482328596>    <a:2025may_mothersDayOwO:1377197500414427146>⁰⁰⁰  <a:2025may_sportsdayowo:1377197478868418570>⁰⁰⁰  <a:2026april_aprilfools:1488087565251772428>⁰⁰⁰  <a:2026april_easter:1488087538563551368>⁰⁰⁰  <a:2026aug_cattodoggo:1533255278047399988>⁰⁰⁰  
<:blank:427371936482328596>    <a:2026aug_HungryGhost:1533255252646695065>⁰⁰⁰  <a:2026feb_huba:1467699766321217538>⁰⁰⁰  <a:2026feb_SnowSlug:1467699778048757771>⁰⁰⁰  <a:2026july_mothweek:1521417260273766521>⁰⁰⁰  <a:2026july_pecan:1521417280397905941>⁰⁰⁰  
<:blank:427371936482328596>    <a:2026may_beeday:1498231408169058304>⁰⁰⁰  <a:2026may_frank:1498231420949233665>⁰⁰⁰  <a:2026may_graduates:1498232154344263782>⁰⁰⁰  <a:2026sept_midautumn:1544270989716627538>⁰⁰⁰  <a:2026sept_september:1544270975929942026>⁰⁰⁰  
<:blank:427371936482328596>    <a:2026sept_WHDViva:1544271003075477504>⁰⁰⁰  <a:4m_jellyfish:1455800572975386717>⁰⁰⁰  <a:4m_owo:1461956620698259634>⁰⁰⁰  
<:mythic:416520808501084162>   :dragon:⁰⁰⁰  :unicorn:⁰⁰¹  :snowman2:⁰⁰⁰  :ghost:⁰⁰⁰  :dove:⁰⁰⁰"""
ZOO_MSG2 = """<a:gem:510023576489951232>    <a:gcamel:510023576573837322>⁰⁰⁰  <a:gfish:510023576892473364>⁰⁰⁰  <a:gpanda:510023577320292353>⁰⁰⁰  <a:gshrimp:510023577295388672>⁰⁰⁰  <a:gspider:510023576775032844>⁰⁰⁰  
<a:legendary:417955061801680909>    <a:gdeer:418290217989046274>⁰⁰⁰  <a:gfox:418291892376305664>⁰⁰⁰  <a:glion:418289164736528404>⁰⁰⁰  <a:gowl:418284974593277954>⁰⁰⁰  <a:gsquid:417968419984375808>⁰⁰⁰  
<a:botrank:716545289497870407>    <a:slothbot:711772997320441897>⁰⁰⁰  
<a:cpatreon:483053960337293321>    <:azula:820592681340108822>⁰⁰⁰  <:i_heart_pizza:842340973333708810>⁰⁰⁰  <:Kawaii_unicorn:1351430048951042151>⁰⁰⁰  <:Peepolax:885437252363239484>⁰⁰⁰  <:priestessmeden:808621201634492466>⁰⁰⁰  
<:blank:427371936482328596>    <:Riyo_Reaper:1547675941424201858>⁰⁰⁰  <a:highfive:1394681900970279077>⁰⁰⁰  <a:kavusamadik:1213065151742476339>⁰⁰⁰  <a:lisapie:768383943643758612>⁰⁰⁰  
<a:fabled:438857004493307907>    <a:dfrog:435592209883070474>⁰⁰⁰  <a:dgorilla:438842240865927180>⁰⁰⁰  <a:dwolf:435592220758769684>⁰⁰⁰
**Zoo Points: __13,559,875__**
	**F-3, CP-9, B-1, G-77, L-371, P-730, M-810, S-82, E-7448, R-74914, U-223757, C-439810**"""


def zoo_msg(text, ch=77):
    return SimpleNamespace(content=text, embeds=[], components=[], channel=SimpleNamespace(id=ch))


# --- parse_zoo don le ---
first = bot_mod.parse_zoo(ZOO_MSG1)
check("zoo tin 1: 53 pet, CHUA co Zoo Points (nam o tin sau)", (len(first["pets"]), first["zoo_points"]), (53, None))
check("zoo tin 2: khong tieu de -> bo qua neu khong bao 'tiep noi'", bot_mod.parse_zoo(ZOO_MSG2), None)
second = bot_mod.parse_zoo(ZOO_MSG2, continuation=True)
check("zoo tin 2 (tiep noi): 23 pet + Zoo Points + breakdown",
      (len(second["pets"]), second["zoo_points"], second["breakdown_raw"]),
      (23, 13559875, "F-3, CP-9, B-1, G-77, L-371, P-730, M-810, S-82, E-7448, R-74914, U-223757, C-439810"))
check("zoo tin 2: cac tier moi (gem/legendary/botrank/cpatreon/fabled)",
      sorted({p["tier"] for p in second["pets"]}), ["botrank", "cpatreon", "fabled", "gem", "legendary"])
check("zoo tin 2: dong 'blank' noi tiep tier cpatreon (5+4 = 9 con)",
      sum(1 for p in second["pets"] if p["tier"] == "cpatreon"), 9)
midtier = bot_mod.parse_zoo("""<:blank:427371936482328596>    <a:y:2>⁰⁰²
**Zoo Points: __5__**""", continuation=True, start_tier="special")
check("zoo tin tiep noi bat dau bang 'blank' -> ke thua tier truoc",
      midtier["pets"], [{"tier": "special", "name": "y", "count": 2, "emoji_id": "2", "emoji_animated": True}])
check("zoo tin tiep noi KHONG bat dau bang tier tag -> khong nhan pet nham",
      bot_mod.parse_zoo("`051`<:cgem1:1>¹⁰⁴\n**Zoo Points: __7__**", continuation=True, start_tier="rare")["pets"], [])


async def run_zoo_split_tests():
    db = AsyncMongoMockClient()["zoo_split"]
    bot_mod.mdb = db
    bot_mod.zoo_session.clear()

    # Tin 2 toi 1 minh (chua co tin 1) -> bo qua
    await bot_mod.handle_owo_response(zoo_msg(ZOO_MSG2), "u1")
    check("luong that: tin 2 toi 1 minh -> khong luu gi", await db[bot_mod.COL_ZOO].find_one({"_id": "latest"}), None)

    # Tin 1 -> luu tam (chua co diem)
    await bot_mod.handle_owo_response(zoo_msg(ZOO_MSG1), "u1")
    doc = await db[bot_mod.COL_ZOO].find_one({"_id": "latest"})
    check("luong that: sau tin 1 -> 53 pet, chua co diem", (len(doc["pets"]), doc["zoo_points"]), (53, None))

    # Tin khong lien quan trong luc cho -> khong lam hong
    await bot_mod.handle_owo_response(zoo_msg("Ruby, you currently have 5 cowoncy!"), "u1")
    check("luong that: tin khac chen giua khong anh huong",
          len((await db[bot_mod.COL_ZOO].find_one({"_id": "latest"}))["pets"]), 53)

    # Tin 2 -> ghep du
    await bot_mod.handle_owo_response(zoo_msg(ZOO_MSG2), "u1")
    doc = await db[bot_mod.COL_ZOO].find_one({"_id": "latest"})
    check("luong that: sau tin 2 -> du 76 pet + Zoo Points", (len(doc["pets"]), doc["zoo_points"]), (76, 13559875))
    hub = await bot_mod.build_hub(datetime.utcnow())
    z = hub["zoo"]
    check("hub: zoo co du tier moi + diem", (z["zoo_points"], "cpatreon" in z["by_tier"], "gem" in z["by_tier"]),
          (13559875, True, True))
    check("hub: tong pet lay tu DONG CUOI (748,012), khong phai cong cac so nho",
          (z["total_pets"], z["total_source"], z["list_total"]), (748012, "breakdown", 1718))
    check("hub: tung tier theo dong cuoi (common 439,810; epic 7,448; fabled 3)",
          (z["by_tier"]["common"]["total"], z["by_tier"]["epic"]["total"], z["by_tier"]["fabled"]["total"]),
          (439810, 7448, 3))
    check("hub: so loai (species) van dem tu bang (common 5 loai, mythic 1 loai)",
          (z["by_tier"]["common"]["species"], z["by_tier"]["mythic"]["species"]), (5, 1))
    check("hub: chi liet ke pet co so luong > 0", len(z["pets"]), 26)
    check("hub: JSON hop le", isinstance(json.dumps(hub), str), True)

    # Go lai owo zoo -> tin co tieu de bat dau lai tu dau (khong cong don)
    await bot_mod.handle_owo_response(zoo_msg(ZOO_MSG1), "u1")
    doc = await db[bot_mod.COL_ZOO].find_one({"_id": "latest"})
    check("luong that: go lai owo zoo -> bat dau ban moi, khong cong don", (len(doc["pets"]), doc["zoo_points"]), (53, None))

    # Tin 2 toi qua muon (qua cua so) -> bo qua
    bot_mod.zoo_session[77]["ts"] -= bot_mod.ZOO_PART_WINDOW + 5
    await bot_mod.handle_owo_response(zoo_msg(ZOO_MSG2), "u1")
    doc = await db[bot_mod.COL_ZOO].find_one({"_id": "latest"})
    check("luong that: tin 2 toi qua muon -> khong ghep", len(doc["pets"]), 53)

    # Zoo ngan (vua 1 tin) van chay nhu cu
    bot_mod.zoo_session.clear()
    await bot_mod.handle_owo_response(zoo_msg(
        "🌿 🌱 🌳** Ruby's zoo! **🌳 🌿 🌱\n<:common:416520037713838081>   :bee:¹⁹⁰\n**Zoo Points: __50__**\n\t**F-0, C-190**"), "u1")
    doc = await db[bot_mod.COL_ZOO].find_one({"_id": "latest"})
    check("luong that: zoo vua 1 tin van dung", (len(doc["pets"]), doc["zoo_points"]), (1, 50))


asyncio.run(run_zoo_split_tests())

check("parse_zoo_breakdown: dong that", bot_mod.parse_zoo_breakdown(
    "F-3, CP-9, B-1, G-77, L-371, P-730, M-810, S-82, E-7448, R-74914, U-223757, C-439810"),
    {"fabled": 3, "cpatreon": 9, "botrank": 1, "gem": 77, "legendary": 371, "patreon": 730, "mythic": 810,
     "special": 82, "epic": 7448, "rare": 74914, "uncommon": 223757, "common": 439810})
check("parse_zoo_breakdown: tong 12 tier = 748,012", sum(bot_mod.parse_zoo_breakdown(
    "F-3, CP-9, B-1, G-77, L-371, P-730, M-810, S-82, E-7448, R-74914, U-223757, C-439810").values()), 748012)
check("parse_zoo_breakdown: rong / None / ma la", (bot_mod.parse_zoo_breakdown(""), bot_mod.parse_zoo_breakdown(None),
      bot_mod.parse_zoo_breakdown("ZZ-5, C-10")), ({}, {}, {"common": 10}))


# ========================================================================
# 8. Ten emoji, team doc nham ID emoji, chu vu khi
# ========================================================================
print("\n=== Ten emoji / Team / Chu vu khi ===")

check("emoji_to_name: emoji dong <a:slothbot:ID>", bot_mod.emoji_to_name("<a:slothbot:711772997320441897>"), "slothbot")
check("emoji_to_name: emoji tinh <:gowl:ID>", bot_mod.emoji_to_name("<:gowl:418284974593277954>"), "gowl")
check("emoji_to_name: dang :dragon:", bot_mod.emoji_to_name(":dragon:"), "dragon")
check("emoji_to_name: chu thuong giu nguyen", bot_mod.emoji_to_name("slothbot"), "slothbot")
check("emoji_to_name: None/rong", (bot_mod.emoji_to_name(None), bot_mod.emoji_to_name("")), ("", ""))

# Tin nhan team THAT: pet hien bang emoji -> chuoi <a:slothbot:ID>, ID la day so ~18 chu so
team_raw = bot_mod.parse_team("""[1] <a:slothbot:711772997320441897>
Lvl 26 [181,880/457,976]
968 916
100 100
45% 45%
`C2PRPT` 82.7%
[2] <:gowl:418284974593277954>
Lvl 10 [1,000/2,000]
120 80
30 40
5% 6%
`ABC123` 90.0%""")
check("team emoji: ten lay dung tu emoji", [m["name"] for m in team_raw], ["slothbot", "gowl"])
check("team emoji: HP/WP/ATT/MAG/PR/MR KHONG bi lech boi ID emoji",
      {k: team_raw[0][k] for k in ("hp", "wp", "att", "mag", "pr", "mr")},
      {"hp": 968, "wp": 916, "att": 100, "mag": 100, "pr": 45, "mr": 45})
check("team emoji: pet thu 2 cung dung", {k: team_raw[1][k] for k in ("hp", "wp", "att", "mag", "pr", "mr")},
      {"hp": 120, "wp": 80, "att": 30, "mag": 40, "pr": 5, "mr": 6})
check("team emoji: level + vu khi van dung", (team_raw[0]["level"], team_raw[0]["weaponId"], team_raw[0]["quality"]),
      (26, "C2PRPT", 82.7))


async def run_emoji_owner_tests():
    db = AsyncMongoMockClient()["emoji_owner"]
    bot_mod.mdb = db

    # Du lieu team CU da luu sai (ten emoji tho + HP la ID emoji) -> hub tu lam sach
    await db[bot_mod.COL_TEAM].insert_one({"_id": 1, "pos": 1, "name": "<a:slothbot:711772997320441897>",
        "level": 26, "hp": 711772997320441897, "wp": 968, "att": 916, "mag": 100, "pr": 100, "mr": 45,
        "weaponId": "C2PRPT", "quality": 82.7, "updated_at": datetime.utcnow().isoformat()})
    hub = await bot_mod.build_hub(datetime.utcnow())
    m0 = hub["team"]["members"][0]
    check("hub team: du lieu cu -> ten sach, so ID emoji bi bo (None)", (m0["name"], m0["hp"], m0["wp"]), ("slothbot", None, 968))

    # --- Chu vu khi ---
    ME = SimpleNamespace(id=555, display_name="Ruby", global_name="Ruby", nick=None, name="ruby_dev")
    bot_mod.tracked_names.clear()
    bot_mod.tracked_names["555"] = {"Ruby", "ruby_dev"}

    def weapon_text(owner, wid="FJJ8N2"):
        return f"""## {owner}'s Culling Scythe [2]
**Name:** Culling Scythe
**ID:** `{wid}`
**Quality:** 95.2%

**__Giant Slayer__** - Deal +23.95% more damage to bosses.
Reroll Changes: 0"""

    check("parse_weapon_detail: doc chu so huu", bot_mod.parse_weapon_detail(weapon_text("Ruby"))["owner"], "Ruby")
    check("parse_weapon_detail: chu co emoji dung truoc ten",
          bot_mod.parse_weapon_detail(weapon_text("<:owo:123456789012345678> Ruby"))["owner"], "Ruby")
    check("weapon_owner_matches: khop / khong phan biet hoa thuong / bo ky hieu",
          (bot_mod.weapon_owner_matches("Ruby", {"Ruby"}), bot_mod.weapon_owner_matches("ruby", {"Ruby"}),
           bot_mod.weapon_owner_matches("Ruby✨", {"Ruby"}), bot_mod.weapon_owner_matches("Rubi", {"Ruby"}),
           bot_mod.weapon_owner_matches("Ru", {"Ruby"}), bot_mod.weapon_owner_matches("", {"Ruby"}),
           bot_mod.weapon_owner_matches("Ruby", set())), (True, True, True, False, False, False, False))

    def owo_msg(text):
        return SimpleNamespace(content=text, embeds=[], components=[], channel=SimpleNamespace(id=9))

    bot_mod.last_owo_command[9] = "owo weapon FJJ8N2"
    await bot_mod.handle_owo_response(owo_msg(weapon_text("Ruby", "FJJ8N2")), "555")
    check("chu dung -> ghi vu khi", await db[bot_mod.COL_WEAPON_INSTANCES].count_documents({"_id": "FJJ8N2"}), 1)
    check("chu dung -> ghi ca loai vu khi + passive",
          (await db[bot_mod.COL_WEAPON_TYPES].count_documents({}) > 0, await db[bot_mod.COL_PASSIVES].count_documents({}) > 0),
          (True, True))

    await bot_mod.handle_owo_response(owo_msg(weapon_text("Nguoi Khac", "ZZZZZ9")), "555")
    check("chu SAI -> KHONG ghi vu khi", await db[bot_mod.COL_WEAPON_INSTANCES].count_documents({"_id": "ZZZZZ9"}), 0)
    check("chu SAI -> nho lai de lenh ,weaponowner bao", (bot_mod.skipped_weapon["owner"], bot_mod.skipped_weapon["id"]),
          ("Nguoi Khac", "ZZZZZ9"))
    types_before = await db[bot_mod.COL_WEAPON_TYPES].count_documents({})
    await bot_mod.handle_owo_response(owo_msg(weapon_text("Nguoi Khac", "ZZZZZ8")), "555")
    check("chu SAI -> khong them gi vao loai vu khi/passive", await db[bot_mod.COL_WEAPON_TYPES].count_documents({}), types_before)

    # Ten them tay (alias) qua ,weaponowner
    await bot_mod.set_config("weapon_owner_aliases", "Rubynek, Ruby Nek")
    await bot_mod.handle_owo_response(owo_msg(weapon_text("Rubynek", "ALIAS1")), "555")
    check("ten them tay (alias) -> duoc chap nhan", await db[bot_mod.COL_WEAPON_INSTANCES].count_documents({"_id": "ALIAS1"}), 1)

    # Chua biet ten nguoi theo doi -> khong the xac minh -> khong ghi
    bot_mod.tracked_names.clear()
    await bot_mod.set_config("weapon_owner_aliases", "")
    await bot_mod.handle_owo_response(owo_msg(weapon_text("Ruby", "NONAME1")), "555")
    check("chua biet ten nguoi theo doi -> khong ghi (khong the xac minh)",
          await db[bot_mod.COL_WEAPON_INSTANCES].count_documents({"_id": "NONAME1"}), 0)


asyncio.run(run_emoji_owner_tests())


async def run_on_message_names_test():
    db = AsyncMongoMockClient()["on_message_names"]
    bot_mod.mdb = db
    bot_mod.tracked_names.clear()
    await bot_mod.set_config("tracked_user_id", "555")

    async def _noop(msg):
        return None
    original = bot_mod.bot.process_commands
    bot_mod.bot.process_commands = _noop
    try:
        me = SimpleNamespace(id=555, display_name="Ruby", global_name="Ruby Dev", nick=None, name="ruby_dev")
        msg = SimpleNamespace(content="Owo weapon FJJ8N2", author=me, channel=SimpleNamespace(id=31))
        await bot_mod.on_message(msg)
        check("on_message: ghi lai cac ten Discord cua nguoi theo doi",
              bot_mod.tracked_names.get("555"), {"Ruby", "Ruby Dev", "ruby_dev"})
        # Nguoi khac go lenh owo -> khong ghi ten
        other = SimpleNamespace(id=999, display_name="Khach", global_name=None, nick=None, name="khach")
        await bot_mod.on_message(SimpleNamespace(content="owo daily", author=other, channel=SimpleNamespace(id=31)))
        check("on_message: nguoi khac go lenh -> khong ghi ten", "999" in bot_mod.tracked_names, False)
    finally:
        bot_mod.bot.process_commands = original


asyncio.run(run_on_message_names_test())


# ========================================================================
# 9. ICON THAT: ID emoji Discord de app tai hinh anh, hoac Unicode co san
# ========================================================================
print("\n=== Icon (emoji_id / unicode) ===")

check("extract_emoji_tags: dong + tinh, lay dung ID", bot_mod.extract_emoji_tags(
    "<a:slothbot:711772997320441897> va <:common:416520037713838081> va :bee: (khong ID)"),
    [("slothbot", "711772997320441897", True), ("common", "416520037713838081", False)])
check("EMOJI_UNICODE: co du 25 con vat trong zoo", len(bot_mod.EMOJI_UNICODE), 25)


async def run_icon_tests():
    db = AsyncMongoMockClient()["icons"]
    bot_mod.mdb = db

    def msg(t, ch=3):
        return SimpleNamespace(content=t, embeds=[], components=[], channel=SimpleNamespace(id=ch))

    # --- Zoo: pet co ID (custom) + pet khong ID (unicode) trong cung 1 tin ---
    zoo_text = ("Ruby's zoo!\n<:common:100> :bee:¹⁹⁰ :bug:²⁰²\n"
                "<:gem:200> <a:gowl:300>⁰⁰¹\n**Zoo Points: __191__**")
    await bot_mod.handle_owo_response(msg(zoo_text), "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    zoo = hub["zoo"]
    bee = next(p for p in zoo["pets"] if p["name"] == "bee")
    gowl = next(p for p in zoo["pets"] if p["name"] == "gowl")
    check("zoo: pet KHONG co ID -> dung Unicode that", bee.get("emoji"), "🐝")
    check("zoo: pet CO ID -> dung emoji_id that (khong phai Unicode)",
          (gowl.get("emoji_id"), gowl.get("emoji_animated"), "emoji" in gowl), ("300", True, False))
    check("zoo: tier cung co icon (tra tu registry, ID cua chinh tag tier)",
          zoo["by_tier"]["common"].get("emoji_id"), "100")
    check("zoo: tier gem cung co icon", zoo["by_tier"]["gem"].get("emoji_id"), "200")

    # --- Gem dang trang bi: icon la ID that cua chinh vien gem ---
    hunt_text = "hunt is empowered by <a:cgem1:400>[47/75] tôi ơi"
    bot_mod.last_owo_command[3] = "owo hunt"
    await bot_mod.handle_owo_response(msg(hunt_text), "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    slot1 = hub["gems"]["equipped"][0]
    check("gem dang dung: icon dung ID that cua vien gem (khong phai suy doan)",
          (slot1["emoji_id"], slot1["emoji_animated"]), ("400", True))

    # --- Kho: gem du phong cung mang theo icon da luu tu truoc ---
    inv = bot_mod.parse_inventory("Inventory\n`051`<a:cgem1:500>¹⁰⁴")
    await bot_mod.save_inventory(inv, "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    spare = hub["gems"]["spare"][0]
    check("gem du phong: icon dung ID that", (spare["emoji_id"], spare["emoji_animated"]), ("500", True))

    # --- Doi hinh: icon la ID that cua pet ---
    team = bot_mod.parse_team("[1] <a:slothbot:600>\nLvl 26 [1/2]\n100 100\n10 10\n1% 1%")
    await bot_mod.save_team(team)
    hub = await bot_mod.build_hub(datetime.utcnow())
    m0 = hub["team"]["members"][0]
    check("doi hinh: icon dung ID that cua pet", (m0["emoji_id"], m0["emoji_animated"]), ("600", True))

    # --- Cowoncy: icon la ID that cua dong xu (hoc duoc tu tin nhan money) ---
    bot_mod.last_owo_command[3] = "owo money"
    await bot_mod.handle_owo_response(msg("<:cowoncy:700> | Ruby, you currently have 999 cowoncy!"), "u1")
    hub = await bot_mod.build_hub(datetime.utcnow())
    check("cowoncy: icon dung ID that", hub["cowoncy"]["emoji_id"], "700")
    check("daily: dung chung icon cowoncy da hoc duoc (chua co tin daily nao)",
          (await bot_mod.build_hub(datetime.utcnow()))["daily"], None)

    # --- Chua tung thay emoji nao -> khong co icon, khong bao loi ---
    check("resolve_emoji: ten la khong ai biet -> tra ve rong", bot_mod.resolve_emoji("con_vat_khong_ton_tai"), {})
    check("resolve_emoji: ten rong/None -> tra ve rong", (bot_mod.resolve_emoji(""), bot_mod.resolve_emoji(None)), ({}, {}))

    # --- Quest: icon do hiem + icon phan thuong ---
    quest_row = {"seals": 10, "all_done": False, "quests": [
        {"index": 1, "title": "Battle", "rarity": "common", "rewards": [
            {"item": "cowoncy", "amount": 120}, {"item": "📦", "amount": 2}], "current": 1, "max": 10, "done": False}]}
    await db[bot_mod.COL_QUEST].insert_one(dict(quest_row, created_at=datetime.utcnow().isoformat()))
    await bot_mod.remember_emojis("<:common:800>")  # tier "common" da co ID=100 tu truoc — khong ghi de (setOnInsert)
    hub = await bot_mod.build_hub(datetime.utcnow())
    qi = hub["quest"]["quests"][0]
    check("quest: icon do hiem lay tu registry (van la ID dau tien hoc duoc, khong bi ghi de)", qi.get("emoji_id"), "100")
    check("quest: phan thuong cowoncy co icon, phan thuong 📦 (unicode san, khong can tra) khong co gi them",
          (qi["rewards"][0].get("emoji_id"), qi["rewards"][1].get("emoji_id")), ("700", None))

    # --- ID emoji la co dinh: ghi de bang ten khac ID van GIU ID dau tien ---
    await bot_mod.remember_emojis("<:common:999999>")
    await bot_mod.load_emoji_cache()
    check("remember_emojis: ID 1 ten la co dinh, khong bi doi boi lan thay sau",
          bot_mod.resolve_emoji("common").get("emoji_id"), "100")


asyncio.run(run_icon_tests())

print("\n" + ("=" * 40))
if failures:
    print(f"{FAIL} {len(failures)} test thất bại: {failures}")
else:
    print(f"{PASS} Toàn bộ test pass.")
