"""test_performance.py — cache cấu hình, lưu emoji gộp, cache duyệt vũ khí, /hub?dex=0, dọn hàng đợi lệnh.
Chạy: python test_performance.py"""
import asyncio
from datetime import timedelta

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


async def main():
    db = AsyncMongoMockClient()["perf"]
    b.mdb = db

    await b.set_config("tracked_channel_id", "1")
    check("cấu hình: đọc đúng", await b.get_config("tracked_channel_id"), "1")
    await b.set_config("tracked_channel_id", "2")
    check("cấu hình: ghi xong thấy ngay", await b.get_config("tracked_channel_id"), "2")
    await db[b.COL_CONFIG].update_one({"_id": "tracked_channel_id"}, {"$set": {"value": "3"}})
    check("cấu hình: đọc từ bộ nhớ tạm", await b.get_config("tracked_channel_id"), "2")
    check("cấu hình: khóa chưa đặt trả mặc định", await b.get_config("owo_prefixes", "x"), "x")
    check("cấu hình: mặc định khác nhau không bị nhớ", await b.get_config("owo_prefixes", "y"), "y")
    b.mdb = AsyncMongoMockClient()["perf2"]
    check("cấu hình: đổi database thì đọc lại", await b.get_config("tracked_channel_id"), None)
    b.mdb = db

    await b.remember_emojis("<:a:1> <a:b:2> <:a:9>")
    await b.remember_emojis("<:a:5> <:c:3> chữ thường")
    await b.remember_emojis("không có emoji")
    rows = await db[b.COL_EMOJI].find().sort("_id", 1).to_list(length=10)
    check("emoji: lưu đủ, ID cũ giữ nguyên", [(r["_id"], r["id"], r["animated"]) for r in rows],
          [("a", "1", False), ("b", "2", True), ("c", "3", False)])

    await b.set_config(b.REVIEW_KEY, {"active": False})
    await db[b.COL_WEAPON_LIST].insert_many([{"_id": "AAAA"}, {"_id": "BBBB"}, {"_id": "CCCC", "starred": True}])
    await db[b.COL_WEAPON_REVIEW].insert_one({"_id": "AAAA", "decision": "keep"})
    r = await b._hub_weapon_review()
    lists = await b.review_lists()
    check("duyệt: số đếm khớp danh sách",
          (r["remaining"], r["kept"], r["dropped"], r["unknown"], r["unseen"]),
          (1, 1, 0, len(lists["unknown"]), len(lists["unseen"])))
    await db[b.COL_WEAPON_REVIEW].insert_one({"_id": "BBBB", "decision": "drop"})
    check("duyệt tắt: dùng lại số đã tính", (await b._hub_weapon_review())["remaining"], 1)
    await db[b.COL_CONFIG].update_one({"_id": b.REVIEW_KEY}, {"$set": {"value.active": True}})
    check("duyệt bật: luôn tính mới", (await b._hub_weapon_review())["remaining"], 0)

    await db[b.COL_PET_SPECIES].insert_one({"_id": "bee", "display_name": "bee"})
    full, light = await b.build_hub(), await b.build_hub(include_pet_dex=False)
    check("/hub mặc định có sổ pet", full["pet_dex"]["total_known"], 1)
    check("/hub?dex=0 bỏ sổ pet", light["pet_dex"], None)
    check("/hub: hai bản có cùng các mục", set(full), set(light))

    now = b._utcnow()
    old = (now - timedelta(days=b.COMMAND_KEEP_DAYS + 1)).isoformat()
    new = (now - timedelta(days=1)).isoformat()
    cmds = db[b.COL_AUTOMACRO_COMMANDS]
    await cmds.insert_many([{"_id": i, "status": s, "created_at": at} for i, (s, at) in enumerate(
        [(s, old) for s in b.COMMAND_FINISHED] + [("pending", old), ("done", new)])])
    await b.ensure_indexes()
    b._command_purge_at["ts"] = 0.0
    await b.purge_old_commands_tick(10 ** 9, now)
    left = sorted((d["status"], d["created_at"] == new) for d in await cmds.find().to_list(length=20))
    check("dọn lệnh: chỉ xóa lệnh đã xong và cũ", left, [("done", True), ("pending", False)])


asyncio.run(main())
if fails:
    raise SystemExit(f"{len(fails)} kiểm tra hỏng")
