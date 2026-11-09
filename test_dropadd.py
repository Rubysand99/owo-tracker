"""test_dropadd.py — lệnh ,dropadd (thêm ID vào danh sách rã, bền qua ,weaponimport). Chạy: python test_dropadd.py"""
import sys, asyncio
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import weapon_import
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

async def main():
    b.mdb = AsyncMongoMockClient()["dropadd_test"]
    for i, (dec, why, q) in enumerate([("keep", "x", 60.9), ("drop", "q_thap", 61.0), ("keep", "khoa", 90.0)]):
        await b.mdb[b.COL_WEAPON_REVIEW].insert_one({"_id": ["C06P72", "F40IBT", "LOCK1"][i], "decision": dec, "reason": why,
                                                    "q": q, "source": "neon_export"})
    check("ban đầu danh sách trống", await b.extra_drop_ids(), [])
    r = await b.dropadd_apply("c06p72 F40IBT LOCK1 ZZZ999 !!")
    check("thêm: nhớ ID viết hoa, bỏ cây khóa, báo ID lạ/không hợp lệ",
          (await b.extra_drop_ids(), "KHÓA" in r and "LOCK1" in r, "ZZZ999" in r, "không hợp lệ" in r),
          (["C06P72", "F40IBT", "ZZZ999"], True, True, True))
    r = await b.dropadd_apply("c06p72")
    check("thêm trùng không nhân đôi", await b.extra_drop_ids(), ["C06P72", "F40IBT", "ZZZ999"])
    docs = await b.mdb[b.COL_WEAPON_REVIEW].find({"source": "neon_export"}).to_list(length=100)
    st = weapon_import.cleanup_stages(docs, await b.extra_drop_ids())
    check("kế hoạch: 2 cây vào rã theo ID, hết vùng chưa rõ, cây khóa không đụng",
          (st["id_drop"], st["unsure"], st["star_ids"]), (["C06P72", "F40IBT"], [], []))
    r = await b.dropadd_apply("-x zzz999")
    check("gỡ ID", (await b.extra_drop_ids(), "Đã gỡ 1" in r), (["C06P72", "F40IBT"], True))
    r = await b.dropadd_apply("-x NOPE")
    check("gỡ ID không có -> báo, không đổi", (await b.extra_drop_ids(), "Không có ID nào" in r), (["C06P72", "F40IBT"], True))
    r = await b.dropadd_apply("")
    check("không tham số = xem danh sách", ("C06P72" in r, "(2)" in r), (True, True))
asyncio.run(main())
print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
