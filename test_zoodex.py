"""test_zoodex.py — `,zoodex`: pet nào trong zoo hiện tại chưa có dex thì nhờ app gõ `owo dex <pet>`.
Chạy: python test_zoodex.py"""
import sys, asyncio
from datetime import timedelta
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

def pets(*items):
    return [{"name": n, "count": c, "tier": "gem"} for n, c in items]

async def put_zoo(db, plist, age_hours=0):
    at = (b._utcnow() - timedelta(hours=age_hours)).isoformat()
    await db[b.COL_ZOO].replace_one({"_id": "latest"}, {"_id": "latest", "pets": plist, "updated_at": at}, upsert=True)

async def put_dex(db, name, aliases=None):
    await db[b.COL_PET_SPECIES].replace_one({"_id": name.lower()}, {"_id": name.lower(), "display_name": name,
                                            "aliases": aliases or [name]}, upsert=True)

async def pending_dex(db):
    return [(c["action"], c["params"]["command_text"], c["params"]["pet"])
            async for c in db[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending", "action": "dex_pet"})]

async def run():
    db = b.mdb = AsyncMongoMockClient()["zoodex_test"]
    b._app_off_cache.update({"v": None, "at": 0}); b._dex_requested.clear()
    said = []
    async def send(text=None, **kw): said.append(text)
    ctx = NS(send=send)
    last = lambda: said[-1]

    # --- chưa có zoo ---
    await b.zoodex_cmd(ctx)
    check("chưa có zoo -> hướng dẫn gõ owo zoo, không xếp lệnh", ("owo zoo" in last(), await pending_dex(db)), (True, []))

    # --- tìm pet thiếu dex ---
    await put_zoo(db, pets(("gowl", 3), ("dboar", 1), ("cat2", 0), ("slothbot", 2), ("Fox", 5)))
    await put_dex(db, "gowl", ["gowl", "owl"])            # có dex theo tên
    await put_dex(db, "sloth", ["sloth", "slothbot"])     # có dex theo BÍ DANH
    info = await b.zoo_pets_missing_dex()
    check("thiếu dex: chỉ pet đang giữ (count>0) mà chưa có dex; bí danh cũng tính là có",
          (info["missing"], info["held"]), (["dboar", "Fox"], 4))

    # --- xem (không xếp lệnh) ---
    await b.zoodex_cmd(ctx, mode="xem")
    check("zoodex xem: liệt kê, KHÔNG nhờ app", (("dboar" in last() and "Fox" in last()), await pending_dex(db)), (True, []))

    # --- nhờ app tra ---
    await b.zoodex_cmd(ctx)
    check("zoodex: xếp lệnh `owo dex <pet>` cho từng pet thiếu dex",
          sorted(await pending_dex(db)), [("dex_pet", "owo dex Fox", "Fox"), ("dex_pet", "owo dex dboar", "dboar")])
    check("zoodex: báo đã nhờ app + số pet", ("Đã nhờ app gõ" in last() and "**2**" in last()), True)
    await b.zoodex_cmd(ctx)
    check("zoodex gõ lại ngay: KHÔNG xếp trùng (đang chờ / vừa nhờ)", len(await pending_dex(db)), 2)
    check("zoodex gõ lại: báo là đã nhờ gần đây", "đã nhờ app tra gần đây" in last(), True)

    # --- app trả dex về -> hết thiếu ---
    await b.save_pet_species({"name": "dboar", "aliases": ["dboar"], "rank": "Legendary", "rank_vi": None,
                              "stats": [1, 2, 3, 4, 5, 6], "count": "1/9"}, "555")
    check("sau khi dex dboar được ghi nhận -> còn thiếu mỗi Fox", (await b.zoo_pets_missing_dex())["missing"], ["Fox"])
    await b.save_pet_species({"name": "Fox", "aliases": ["Fox"], "rank": "Common", "rank_vi": None,
                              "stats": [1, 2, 3, 4, 5, 6], "count": "5/9"}, "555")
    await db[b.COL_AUTOMACRO_COMMANDS].delete_many({}); b._dex_requested.clear()
    await b.zoodex_cmd(ctx)
    check("đủ dex hết -> báo ✅, không xếp lệnh", ("✅" in last(), await pending_dex(db)), (True, []))

    # --- nhiều pet: giới hạn mỗi lượt ---
    await db[b.COL_PET_SPECIES].delete_many({})
    many = [(f"pet{i:02d}", 1) for i in range(27)]
    await put_zoo(db, pets(*many)); b._dex_requested.clear()
    await b.zoodex_cmd(ctx)
    check("27 pet thiếu dex: mỗi lượt xếp tối đa 20", len(await pending_dex(db)), 20)
    check("27 pet thiếu dex: báo còn 7 pet, gõ lại để làm tiếp", ("Còn 7 pet" in last()), True)
    # app làm xong 20 -> lệnh hết pending; gõ lại sau khi hết thời gian chờ -> xếp nốt 7 (20 con kia vừa nhờ gần đây nên bỏ qua)
    await db[b.COL_AUTOMACRO_COMMANDS].update_many({}, {"$set": {"status": "done"}})
    await b.zoodex_cmd(ctx)
    got = [p for _, _, p in await pending_dex(db)]
    check("gõ lại: xếp nốt 7 pet còn lại (không lặp 20 con vừa nhờ)", sorted(got), [f"pet{i:02d}" for i in range(20, 27)])

    # --- tên lạ không an toàn để gõ vào Discord ---
    await db[b.COL_AUTOMACRO_COMMANDS].delete_many({}); b._dex_requested.clear()
    await put_zoo(db, pets(("good", 1), ("bad name; owo daily", 1), ("x" * 40, 1)))
    await b.zoodex_cmd(ctx)
    check("tên lạ (có khoảng trắng/ký tự đặc biệt/quá dài) bị bỏ qua, chỉ nhờ tên an toàn",
          ([p for _, _, p in await pending_dex(db)], "Bỏ qua 2 tên lạ" in last()), (["good"], True))

    # --- zoo cũ -> nhắc ---
    await db[b.COL_AUTOMACRO_COMMANDS].delete_many({}); b._dex_requested.clear()
    await put_zoo(db, pets(("zed", 1)), age_hours=10)
    await b.zoodex_cmd(ctx, mode="xem")
    check("zoo đọc cách đây 10 giờ -> nhắc gõ owo zoo lại", "10 giờ" in last() and "owo zoo" in last(), True)

    # --- app đang TẮT -> bị chặn ngay từ đầu ---
    await b.set_app_off(True)
    guard_msgs = []
    async def gsend(text=None, **kw): guard_msgs.append(text)
    blocked = False
    try:
        await b._app_off_guard(NS(command=NS(name="zoodex"), send=gsend))
    except Exception as e:
        blocked = "app_off" in str(e)
    check("app đang TẮT (,off / Hub tắt): ,zoodex bị chặn và báo cho Ruby", (blocked, any("TẮT" in (m or "") for m in guard_msgs)), (True, True))
    await b.set_app_off(False)
    ok = await b._app_off_guard(NS(command=NS(name="zoodex"), send=gsend))
    check("app BẬT: ,zoodex được phép", ok, True)

asyncio.run(run())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test zoodex pass.")
