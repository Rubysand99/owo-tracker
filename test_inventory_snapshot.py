"""test_inventory_snapshot.py — kiểm tra "mỗi lần gõ owo inv = 1 lần chụp mới, món không còn thì bị xóa".
Dùng đúng 2 tin kho thật (4/10/2026) mà Ruby gửi. Chạy: python test_inventory_snapshot.py"""
import asyncio
from datetime import datetime

from mongomock_motor import AsyncMongoMockClient

import owo_tracker_bot as b

fails = []


def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want)
        print("   thực tế :", got)
        fails.append(label)


PART1 = """**====== Ruby's Inventory ======**
`001`<:cring:590393333331918859>⁰⁰¹    `010`<:wcticket:930641266159517726>⁰⁰¹    `051`<:cgem1:492572122120585240>¹¹⁸    `052`<:ugem1:492572122514980864>¹¹⁵
`053`<:rgem1:492572122888011776>¹²³    `054`<:egem1:492572122477101056>⁰⁴⁸    `055`<:mgem1:492572122590478356>⁰⁰³    `056`<a:lgem1:492572124251422720>⁰⁰²
`065`<:cgem3:510366792024195072>¹²⁸    `066`<:ugem3:510366792095367189>¹¹³    `067`<:rgem3:510366792653340674>¹⁰⁸    `068`<:egem3:510366792800272394>⁰⁶¹
`069`<:mgem3:510366792447819777>⁰⁰⁶    `072`<:cgem4:510366763255463936>¹¹²    `073`<:ugem4:510366764249382922>¹²³    `074`<:rgem4:510366763884478464>¹²³
`075`<:egem4:510366763972558848>⁰³⁵    `076`<:mgem4:510366763993661440>⁰⁰¹    `101`<:greatsword:538196865129250817>⁰²¹    `102`<:healstaff:538196865410138125>⁰³⁴
`103`<:bow:538196864277807105>⁰³⁰    `105`<:shield:546552900986601493>⁰³¹    `106`<:orb:548783216379559966>⁰³³    `107`<:vampstaff:562175262075387904>⁰²¹
`108`<:pdagger:572285296272736256>⁰²⁶    `109`<:awand:572620163434676265>⁰²¹    `110`<:fstaff:572663875749675018>⁰¹⁴    `111`<:estaff:572983470465220608>⁰²⁸
`112`<:sstaff:572984070158680088>⁰²⁰    `113`<:ascept:618001305692274698>⁰³⁵    `114`<:rstaff:618001309483925504>⁰³⁴    `115`<:gaxe:618389128043692043>⁰²³
`116`<:vban:618001308837740545>⁰¹⁸    `117`<:sythe:618001309622337566>⁰²⁶    `118`<:crune:1080441105117614142>⁰⁰¹    `119`<:pstaff:1082882869459947520>⁰¹³
`120`<:lsyth:1107927037190090804>⁰¹⁶    `121`<:ffish:1154635943685394433>⁰¹⁹    `122`<:lrune:1223813026004598795>⁰⁰¹    `123`<:cstaff:1449685764966453349>⁰¹³"""

PART2 = """`124`<:stithe:1456101001152036895>⁰⁰⁹    `125`<:bhstaff:1457225335140778075>⁰¹⁷    `126`<:aedge:1458734694396067971>⁰¹⁰    `127`<:woundb:1473904241822142535>⁰¹⁶
`128`<:bgaz:1476067737812865076>⁰⁰⁸    `129`<:cclaw:1479707582779232428>⁰¹⁷    `2--`🖼⁰⁰⁸"""

# Những dòng "ma" Hub đang hiện nhưng KHÔNG có trong tin kho thật (xem ảnh Hub của Ruby)
GHOSTS = {
    "050": ("box", 2), "070": ("lgem3", 1), "077": ("lgem4", 1), "078": ("fgem4", 1),
    "079": ("cstar", 1), "080": ("ustar", 1), "081": ("rstar", 1), "082": ("estar", 1),
    "083": ("mstar", 1), "084": ("lstar", 1), "085": ("fstar", 4), "099": ("bcrate", 6), "100": ("crate", 1),
}

b.INV_PRUNE_GRACE = 0.05  # test không cần chờ 20 giây


async def seed_old_db(db):
    """Kho CŨ: các món thật (số lượng cũ) + 13 dòng ma + lgem1 còn x3."""
    old_real = b.parse_inventory(PART1)["items"] + b.parse_inventory(PART2, continuation=True)["items"]
    await b.save_inventory({"items": old_real}, "old")  # không có snapshot_id, như dữ liệu cũ
    await db[b.COL_INVENTORY].update_one({"_id": "056"}, {"$set": {"count": 3}})
    for code, (name, cnt) in GHOSTS.items():
        gem = b.parse_gem_name(name)
        await db[b.COL_INVENTORY].update_one({"_id": code}, {"$set": {
            "code": code, "name": name, "count": cnt, "is_gem": gem is not None,
            "gem_tier": gem["tier"] if gem else None, "gem_slot": gem["slot"] if gem else None,
            "gem_tier_rank": b._GEM_TIER_RANK.get(gem["tier"]) if gem else None,
            "updated_at": "2026-10-03T19:00:00"}}, upsert=True)


async def codes(db):
    return {r["_id"] async for r in db[b.COL_INVENTORY].find()}


async def main():
    # ---- 1) Kịch bản thật: tin 1 + tin 2 -> kho cũ bị thay hẳn --------------
    db = b.mdb = AsyncMongoMockClient()["inv_snapshot_1"]
    b.inv_session.clear(); b.inv_snapshot.clear(); b.inv_prune_tasks.clear()
    await seed_old_db(db)
    before = await codes(db)
    check("trước khi chụp: Hub đang có 13 dòng ma", len(before & set(GHOSTS)), 13)

    k1, _ = await b.handle_inventory_text(1, PART1, "u1")
    k2, _ = await b.handle_inventory_text(1, PART2, "u1")
    check("tin 1 là 'inventory', tin 2 là 'inventory_2'", (k1, k2), ("inventory", "inventory_2"))
    await asyncio.sleep(0.3)

    after = await codes(db)
    check("sau khi chụp: KHÔNG còn dòng ma nào (gem F, star, box, crate...)", after & set(GHOSTS), set())
    check("fgem4 (078) đã mất", "078" in after, False)
    expected = {i["code"] for i in b.parse_inventory(PART1)["items"] + b.parse_inventory(PART2, continuation=True)["items"]}
    check("kho = đúng các món có trong 2 tin (không thừa, không thiếu)", after, expected)
    check("lgem1 đã cập nhật x3 -> x2", (await db[b.COL_INVENTORY].find_one({"_id": "056"}))["count"], 2)
    check("món của tin 2 (129 cclaw) còn nguyên, không bị tin 1 xóa", (await db[b.COL_INVENTORY].find_one({"_id": "129"}))["count"], 17)
    snaps = {r["snapshot_id"] async for r in db[b.COL_INVENTORY].find()}
    check("mọi món cùng 1 snapshot id", len(snaps), 1)

    # ---- 2) Hub: gem dự phòng không còn fgem4, có giờ cập nhật riêng ----------
    hub = await b.build_hub(datetime.utcnow())
    spare_ids = {(g["slot"], g["tier"]) for g in hub["gems"]["spare"]}
    check("Hub: slot 4 không còn Fabled", ("4", "Fabled") in spare_ids, False)
    check("Hub: slot 1 Legendary còn x2", [g["count"] for g in hub["gems"]["spare"] if (g["slot"], g["tier"]) == ("1", "Legendary")], [2])
    check("Hub: gem dự phòng có giờ cập nhật riêng", isinstance(hub["gems"]["spare_age_seconds"], int), True)
    check("Hub: kho chỉ còn món thật", hub["inventory"]["kinds"], len(expected))

    # ---- 3) Tin 1 đọc hỏng (chỉ 2 món) -> GIỮ kho cũ ----------------------------
    db = b.mdb = AsyncMongoMockClient()["inv_snapshot_3"]
    b.inv_session.clear(); b.inv_snapshot.clear(); b.inv_prune_tasks.clear()
    await seed_old_db(db)
    n_before = len(await codes(db))
    await b.handle_inventory_text(1, "Ruby's Inventory\n`051`<:cgem1:1>¹¹⁸ `052`<:ugem1:2>¹¹⁵", "u1")
    await asyncio.sleep(0.3)
    check("đọc hỏng (2 món < 3): KHÔNG xóa gì", len(await codes(db)), n_before)

    # ---- 4) Tin 2 mồ côi (bot khởi động lại giữa chừng) -> chỉ ghi thêm -----------
    db = b.mdb = AsyncMongoMockClient()["inv_snapshot_4"]
    b.inv_session.clear(); b.inv_snapshot.clear(); b.inv_prune_tasks.clear()
    await seed_old_db(db)
    n_before = len(await codes(db))
    b.inv_session[1] = __import__("time").time()  # còn nhớ "vừa có kho" nhưng không có snapshot
    kind, _ = await b.handle_inventory_text(1, PART2, "u1")
    await asyncio.sleep(0.3)
    check("tin 2 mồ côi: nhận ra là phần tiếp", kind, "inventory_2")
    check("tin 2 mồ côi: KHÔNG xóa kho (chỉ ghi thêm)", len(await codes(db)), n_before)

    # ---- 5) Gõ owo inv lần 2, ít món hơn -> lần chụp mới thắng ------------------
    db = b.mdb = AsyncMongoMockClient()["inv_snapshot_5"]
    b.inv_session.clear(); b.inv_snapshot.clear(); b.inv_prune_tasks.clear()
    await b.handle_inventory_text(1, PART1, "u1")
    await b.handle_inventory_text(1, PART2, "u1")
    await asyncio.sleep(0.3)
    n_full = len(await codes(db))
    shorter = PART1.replace("`129`", "`999`")  # giả lập: lần sau còn ít món hơn (bỏ phần 2)
    await b.handle_inventory_text(1, shorter, "u1")
    await asyncio.sleep(0.3)
    left = await codes(db)
    check("lần chụp 2 (không có tin 2): các món của tin 2 (124-129) bị xóa", left & {"124", "125", "126", "127", "128", "129"}, set())
    check("lần chụp 2: số món giảm đúng", len(left) < n_full, True)

    # ---- 6) Tin 2 tới SAU khi đã dọn (trễ hơn 20 giây) -> vẫn nhập vào kho --------
    db = b.mdb = AsyncMongoMockClient()["inv_snapshot_6"]
    b.inv_session.clear(); b.inv_snapshot.clear(); b.inv_prune_tasks.clear()
    await b.handle_inventory_text(1, PART1, "u1")
    await asyncio.sleep(0.3)  # đã dọn xong
    await b.handle_inventory_text(1, PART2, "u1")
    await asyncio.sleep(0.3)
    left = await codes(db)
    check("tin 2 trễ: các món 124-129 vẫn vào kho", {"124", "125", "126", "127", "128", "129"} <= left, True)
    check("tin 2 trễ: món của tin 1 không bị xóa", {"051", "123"} <= left, True)


asyncio.run(main())
print()
print("✅ Toàn bộ test kho pass." if not fails else f"❌ {len(fails)} test lỗi: {fails}")
raise SystemExit(1 if fails else 0)
