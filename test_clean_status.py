"""test_clean_status.py — phần bot phục vụ màn hiển thị trạng thái Dọn kho tự động của app:
lý do "không có bước tự động", step_no/step_total gửi kèm mỗi bước, GET /clean.
Chạy: python test_clean_status.py   (cần mongomock-motor như các test khác)"""
import sys, asyncio, json
from types import SimpleNamespace as NS
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

def req(token="tok"):
    return NS(headers={"Authorization": f"Bearer {token}"}, query={})

# ----- cleanup_empty_reason (thuần) -----
r = weapon_import.cleanup_empty_reason({"missing_q": 3, "unsure": []})
check("lý do: thiếu chất lượng -> nêu số cây + cách xử lý", ("3 cây chưa có chất lượng" in r, "weaponimport" in r), (True, True))
check("lý do: cây Bỏ ở vùng chưa rõ bậc KHÔNG còn chặn kế hoạch",
      weapon_import.cleanup_empty_reason({"missing_q": 0, "unsure": ["C06P72", "F40IBT"]}), "kho không có cây nào cần dọn tự động")
check("lý do: missing_q được ưu tiên hơn unsure",
      "chưa có chất lượng" in weapon_import.cleanup_empty_reason({"missing_q": 1, "unsure": ["X"]}), True)
check("lý do: không vướng gì -> kho không có gì cần dọn",
      weapon_import.cleanup_empty_reason({"missing_q": 0, "unsure": []}), "kho không có cây nào cần dọn tự động")

# ----- clean_status_snapshot (thuần) -----
snap = b.clean_status_snapshot({"active": True, "cursor": 2, "total": 5, "at": "2026-11-09T06:00:00+00:00", "empty_reason": ""})
check("snapshot: at -> epoch giây", snap, {"active": True, "cursor": 2, "total": 5, "at_epoch": 1794204000, "empty_reason": ""})
check("snapshot: phiên rỗng -> toàn 0", b.clean_status_snapshot({}),
      {"active": False, "cursor": 0, "total": 0, "at_epoch": 0, "empty_reason": ""})
check("snapshot: at hỏng -> 0, không văng lỗi", b.clean_status_snapshot({"at": "linh tinh"})["at_epoch"], 0)

async def scenarios():
    b.mdb = AsyncMongoMockClient()["clean_test"]
    old_token, b.AUTOMACRO_API_TOKEN = b.AUTOMACRO_API_TOKEN, "tok"
    old_q = b.queue_automacro_command
    queued = []
    async def fake_queue(action, params):
        queued.append((action, params)); return len(queued)
    b.queue_automacro_command = fake_queue
    try:
        r = await b.handle_get_clean(req(token="sai"))
        check("/clean: sai token -> 401", r.status, 401)

        d = json.loads((await b.handle_get_clean(req())).text)
        check("/clean: chưa có phiên -> toàn 0", d, {"active": False, "cursor": 0, "total": 0, "at_epoch": 0, "empty_reason": "", "pending": 0})

        steps = [{"action": "clean_star", "params": {"command_text": "owo w AAA", "clean_mode": "star"}},
                 {"action": "clean_tier", "params": {"command_text": "owo dismantle rare", "clean_mode": "tier", "expect": "54"}},
                 {"action": "clean_id", "params": {"command_text": "owo dismantle BBB", "clean_mode": "id", "expect_id": "BBB"}}]
        await b.mdb[b.COL_CONFIG].insert_one({"_id": b.CLEAN_KEY, "value": {
            "active": True, "steps": steps, "cursor": 1, "total": 3, "at": "2026-11-09T06:00:00+00:00", "empty_reason": ""}})
        d = json.loads((await b.handle_get_clean(req())).text)
        check("/clean: phiên đang chạy", (d["active"], d["cursor"], d["total"], d["at_epoch"], d["pending"]), (True, 1, 3, 1794204000, 0))

        # ----- clean_queue_batch gửi kèm step_no / step_total -----
        await b.clean_queue_batch()
        check("batch: xếp các bước còn lại (từ cursor), đánh số theo vị trí trong CẢ phiên",
              [(a, p["step_no"], p["step_total"]) for a, p in queued], [("clean_tier", "2", "3"), ("clean_id", "3", "3")])
        check("batch: giữ nguyên params gốc (command_text, expect...)", (queued[0][1]["command_text"], queued[0][1]["expect"], queued[1][1]["expect_id"]),
              ("owo dismantle rare", "54", "BBB"))
        check("batch: không sửa dữ liệu gốc của phiên (không lẫn step_no vào steps đã lưu)",
              all("step_no" not in st["params"] for st in steps), True)

        # có bước đang chờ -> không xếp thêm; /clean báo đúng số bước chờ
        await b.mdb[b.COL_AUTOMACRO_COMMANDS].insert_one({"_id": 1, "action": "clean_tier", "params": {}, "status": "pending"})
        queued.clear()
        await b.clean_queue_batch()
        check("batch: còn bước đang chờ -> không xếp thêm", queued, [])
        d = json.loads((await b.handle_get_clean(req())).text)
        check("/clean: pending đếm đúng bước clean_ đang chờ", d["pending"], 1)

        # phiên rỗng có lý do (như khi vướng cây chưa rõ bậc)
        await b.mdb[b.COL_CONFIG].update_one({"_id": b.CLEAN_KEY}, {"$set": {"value": {
            "active": False, "steps": [], "cursor": 0, "total": 0, "at": "2026-11-09T06:05:00+00:00",
            "empty_reason": "5 cây có chất lượng ở vùng chưa rõ bậc (C06P72)"}}})
        d = json.loads((await b.handle_get_clean(req())).text)
        check("/clean: phiên rỗng trả đúng lý do cho app", (d["active"], d["total"], "C06P72" in d["empty_reason"]), (False, 0, True))
    finally:
        b.AUTOMACRO_API_TOKEN = old_token
        b.queue_automacro_command = old_q

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test trạng thái dọn kho (bot) pass.")
