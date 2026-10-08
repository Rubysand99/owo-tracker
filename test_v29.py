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
