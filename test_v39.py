"""test_v39.py — Dọn kho theo bậc: kế hoạch sao MỌI cây Giữ + rã theo bậc, kết thúc bằng export và đối chiếu kho sạch.
Chạy: python test_v39.py"""
import sys, asyncio, json
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

def W(i, q, l=False, bp=None, t=1):
    w = {"id": i, "t": t, "q": q, "p": [], "l": l}
    if bp: w["bp"] = bp
    return w

GOOD = "sword 95,95"
BAD = "sword 10,10"

async def main():
    b.mdb = AsyncMongoMockClient()["v39"]
    sent = []
    async def fake_file(*a, **k): return None
    async def fake_notify(text, **k): sent.append(text)
    b.send_file_to_owner, b.notify_owner = fake_file, fake_notify
    queued = []
    async def fake_queue(action, params): queued.append((action, params)); return len(queued)
    b.queue_automacro_command = fake_queue

    # Lan 1: 1 cay Giu q cao (chua khoa), 1 cay Giu chua xem, 2 cay Bo (q thap, q cao)
    export1 = [W("KEEP1", 90, bp=GOOD), W("SEEN0", 30), W("JUNK1", 20, bp=BAD), W("JUNK2", 85, bp=BAD)]
    text = await b.import_weapon_export(json.dumps(export1).encode(), auto_session=True)
    s = await b.clean_session()
    acts = [x["action"] for x in s["steps"]]
    check("kế hoạch: sao cây Giữ bậc thấp (Chưa xem q 30) rồi rã theo ID cây Bỏ bậc cao", acts[:2], ["clean_star", "clean_id"])
    check("kế hoạch: rã theo bậc cho cây Bỏ bậc thấp, kết thúc bằng export", ("clean_tier" in acts, acts[-1]), (True, "clean_export"))
    check("tóm tắt có 4 danh sách", all(k in text for k in ("Giữ **", "Bỏ **", "Chưa rõ **", "Chưa xem **")), True)

    # Giả lập app làm xong bước export -> bot đánh dấu chờ file cuối phiên
    await b.mdb[b.COL_CONFIG].update_one({"_id": b.CLEAN_KEY}, {"$set": {"value.awaiting_export": True, "value.cursor": len(acts)}})

    # Lan 2 (export cuoi phien): kho sach (cay Giu da sao = khoa, cay Bo da mat)
    export2 = [W("KEEP1", 90, l=True, bp=GOOD), W("SEEN0", 30, l=True)]
    text = await b.import_weapon_export(json.dumps(export2).encode(), auto_session=True)
    check("đối chiếu: kho sạch", "Kho đã sạch" in text, True)
    s = await b.clean_session()
    check("đối chiếu: không mở phiên mới", (s["active"], s["steps"]), (False, []))

    # Lan 3: lai co phien dang cho export nhung con sot cay Bo + 1 cay Giu chua sao
    await b.mdb[b.COL_CONFIG].update_one({"_id": b.CLEAN_KEY}, {"$set": {"value.awaiting_export": True}})
    export3 = [W("KEEP1", 90, l=True, bp=GOOD), W("SEEN0", 30), W("JUNK1", 20, bp=BAD)]
    text = await b.import_weapon_export(json.dumps(export3).encode(), auto_session=True)
    check("đối chiếu: còn sót -> nêu ID cây Bỏ và cây Giữ chưa sao", ("chưa sạch" in text, "`JUNK1`" in text, "`SEEN0`" in text), (True, True, True))
    s = await b.clean_session()
    check("đối chiếu: còn sót -> mở phiên mới (cần Ruby bật lại)", (s["active"], len(s["steps"]) > 0, "awaiting_export" in s), (True, True, False))

    # Export thuong (khong sau phien don) khong in doi chieu
    await b.mdb[b.COL_CONFIG].update_one({"_id": b.CLEAN_KEY}, {"$set": {"value.awaiting_export": False}})
    text = await b.import_weapon_export(json.dumps(export3).encode(), auto_session=True)
    check("export thường: không in đối chiếu", "Kho đã sạch" in text or "chưa sạch" in text, False)

    # Watchdog: qua han ma van cho file -> bao Ruby; file da ve (phien moi) -> im lang
    b.CLEAN_EXPORT_WAIT_SECONDS = 0
    sent.clear()
    await b.mdb[b.COL_CONFIG].update_one({"_id": b.CLEAN_KEY}, {"$set": {"value.awaiting_export": True, "value.at": "T1"}})
    await b._clean_export_watch("T1")
    check("watchdog: chưa thấy file -> báo Ruby", len(sent), 1)
    sent.clear()
    await b._clean_export_watch("T0")
    check("watchdog: phiên đã đổi (file đã về) -> im lặng", sent, [])

    # Bucket 4 danh sach
    check("bucket: chưa xem", b.review_bucket({"decision": "keep", "reason": "chua_xem_bp"}), "unseen")
    check("bucket: chưa rõ (bp_la)", b.review_bucket({"decision": "keep", "reason": "bp_la"}), "unknown")
    check("bucket: quyết tay thắng", b.review_bucket({"decision": "keep", "reason": "chua_xem_bp", "manual": True}), "keep")

asyncio.run(main())
print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
