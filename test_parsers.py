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

print("\n" + ("=" * 40))
if failures:
    print(f"{FAIL} {len(failures)} test thất bại: {failures}")
else:
    print(f"{PASS} Toàn bộ test pass.")
