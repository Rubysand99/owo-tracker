"""test_auto_refresh.py — nhắc huntbot còn 10 phút + tự chen lệnh check khi app đang farm.
Chạy: python test_auto_refresh.py"""
import sys, asyncio, time
from datetime import timedelta
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import auto_refresh as ar
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# ---------- nhắc huntbot: hàm thuần ----------
E = 1_800_000_000
check("nhắc: còn 9 phút -> nhắc", ar.huntbot_alert_due(True, 540, E, None), True)
check("nhắc: đúng 10 phút -> nhắc", ar.huntbot_alert_due(True, 600, E, None), True)
check("nhắc: còn 11 phút -> chưa", ar.huntbot_alert_due(True, 660, E, None), False)
check("nhắc: còn 30 giây -> thôi (muộn)", ar.huntbot_alert_due(True, 30, E, None), False)
check("nhắc: không săn -> không", ar.huntbot_alert_due(False, 540, E, None), False)
check("nhắc: chưa biết giờ về -> không", ar.huntbot_alert_due(True, None, None, None), False)
check("nhắc: đã nhắc chuyến này -> không lặp", ar.huntbot_alert_due(True, 500, E, E), False)
check("nhắc: giờ về dao động 2 phút vẫn là cùng chuyến", ar.huntbot_alert_due(True, 500, E + 120, E), False)
check("nhắc: chuyến MỚI (24h sau) -> nhắc lại", ar.huntbot_alert_due(True, 500, E + 86400, E), True)

# ---------- check huntbot đến hạn ----------
check("hb: chưa từng thấy -> check", ar.huntbot_check_due(E, False, None, None), True)
check("hb: đến hạn 61s, chưa quan sát lại -> check", ar.huntbot_check_due(E + 61, True, E, E - 3600), True)
check("hb: đến hạn mới 30s (chờ OwO tự báo) -> chưa", ar.huntbot_check_due(E + 30, True, E, E - 3600), False)
check("hb: đã quan sát lại SAU giờ về -> thôi", ar.huntbot_check_due(E + 600, True, E, E + 100), False)
check("hb: đang săn, còn lâu, dữ liệu mới -> thôi", ar.huntbot_check_due(E, True, E + 20000, E - 600), False)
check("hb: quá 3 giờ chưa thấy -> check", ar.huntbot_check_due(E, True, E + 20000, E - 3 * 3600 - 5), True)

# ---------- chọn lệnh ----------
fresh = {k: 0 for k, _, _ in ar.CHECK_PLAN}
hb_ok = {"hunting": True, "ready_epoch": E + 20000, "observed_epoch": E - 60}
check("chọn: mọi thứ mới -> không chen", ar.pick_check(E, hb_ok, fresh, 0, {}), None)
check("chọn: vừa chen xong (<3 phút) -> chờ", ar.pick_check(E, hb_ok, {**fresh, "cowoncy": None}, E - 60, {}), None)
check("chọn: cowoncy chưa có -> owo cash", ar.pick_check(E, hb_ok, {**fresh, "cowoncy": None}, 0, {}), ("cowoncy", "owo cash"))
check("chọn: chỉ kho đồ cũ -> owo inv", ar.pick_check(E, hb_ok, {**fresh, "inventory": 7200}, 0, {}), ("inventory", "owo inv"))
check("chọn: huntbot đến hạn được ưu tiên trước cash",
      ar.pick_check(E + 100, {"hunting": True, "ready_epoch": E, "observed_epoch": E - 500}, {**fresh, "cowoncy": None}, 0, {}),
      ("huntbot", "owo hb"))
check("chọn: vừa xin cash 5 phút trước mà chưa thấy mới -> chưa xin lại",
      ar.pick_check(E, hb_ok, {**fresh, "cowoncy": None}, 0, {"cowoncy": E - 300}), None)
check("chọn: xin cash >15 phút trước -> xin lại",
      ar.pick_check(E, hb_ok, {**fresh, "cowoncy": None}, 0, {"cowoncy": E - 1000}), ("cowoncy", "owo cash"))

# ---------- vòng nền với DB giả ----------
async def pending(db):
    return [d async for d in db[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending"})]

def reset_state(farming=True):
    b._auto_check_state.update({"last_auto": 0.0, "last_eval": 0.0, "requested": {}})
    b.farm_watch.update({"active": farming, "resting": False, "last_seen": time.time()})

async def hb_row(db, left_text, hunting=True):
    now = b._utcnow().isoformat()
    await db[b.COL_HUNTBOT].insert_one({"hunting": hunting, "time_remaining": left_text, "status_at": now,
                                        "created_at": now, "essence": 1})

async def scenarios():
    db = b.mdb = AsyncMongoMockClient()["autorefresh_test"]
    b._app_off_cache.update({"v": None, "at": 0})
    now, now_ts = b._utcnow(), time.time()

    # 1) đang farm, chưa có dữ liệu gì -> chen `owo hb` trước
    reset_state()
    check("tick: farm + chưa có dữ liệu -> chen owo hb", await b.auto_check_tick(now_ts, now), "owo hb")
    cmds = await pending(db)
    check("tick: lệnh xếp đúng dạng app hiểu (action + command_text)",
          [(c["action"], c["params"]["command_text"]) for c in cmds], [("auto_check", "owo hb")])
    check("tick: ngay sau đó KHÔNG chen thêm (cách tối thiểu 3 phút)", await b.auto_check_tick(now_ts + 10, now), None)

    # 2) cùng dữ liệu, app KHÔNG farm / đang nghỉ -> không tự gõ
    await db[b.COL_AUTOMACRO_COMMANDS].delete_many({})
    reset_state(farming=False)
    check("tick: app không farm -> không tự gõ gì", await b.auto_check_tick(now_ts, now), None)
    reset_state(); b.farm_watch["resting"] = True
    check("tick: app đang nghỉ giải lao -> không gõ", await b.auto_check_tick(now_ts, now), None)
    reset_state(); b.farm_watch["last_seen"] = now_ts - 300
    check("tick: app im >60s (mất kết nối) -> không xếp lệnh", await b.auto_check_tick(now_ts, now), None)

    # 3) các điều kiện lùi lại
    reset_state(); await b.set_app_off(True)
    check("tick: ,off -> không giao việc", await b.auto_check_tick(now_ts, now), None)
    await b.set_app_off(False)
    reset_state(); await b.set_config("auto_check", "off")
    check("tick: ,autocheck off -> không giao việc", await b.auto_check_tick(now_ts, now), None)
    await b.set_config("auto_check", "on")
    reset_state(); await db[b.COL_ALERTS].update_one({"_id": "captcha"}, {"$set": {"active": True, "at": now.isoformat()}}, upsert=True)
    check("tick: đang captcha -> không giao việc", await b.auto_check_tick(now_ts, now), None)
    await db[b.COL_ALERTS].delete_many({})
    reset_state(); await b.record_slowdown()
    check("tick: vừa bị Slow down -> lùi lại", await b.auto_check_tick(time.time(), now), None)
    await db[b.COL_ALERTS].delete_many({})
    reset_state(); await db[b.COL_AUTOMACRO_COMMANDS].insert_one(
        {"_id": 99, "action": "swap_gem", "params": {}, "status": "pending", "created_at": now.isoformat(), "completed_at": None})
    check("tick: app còn lệnh chưa làm -> không chồng thêm", await b.auto_check_tick(now_ts, now), None)
    await db[b.COL_AUTOMACRO_COMMANDS].delete_many({})

    # 4) huntbot đã biết & còn lâu mới về -> chuyển sang mục dữ liệu khác (cash)
    await hb_row(db, "5H 0M")
    reset_state()
    check("tick: huntbot ổn -> chen owo cash (chưa có số dư)", await b.auto_check_tick(now_ts, now), "owo cash")
    await db[b.COL_AUTOMACRO_COMMANDS].delete_many({})

    # 5) huntbot đã tới hạn (gia lập: quan sát cách đây 2 giờ, hẹn 30 phút) -> check owo hb
    await db[b.COL_HUNTBOT].delete_many({})
    old = (now - timedelta(hours=2)).isoformat()
    await db[b.COL_HUNTBOT].insert_one({"hunting": True, "time_remaining": "30M", "status_at": old, "created_at": old})
    reset_state()
    check("tick: huntbot đã quá giờ về -> chen owo hb", await b.auto_check_tick(now_ts, now), "owo hb")

    # 6) nhắc huntbot còn 10 phút
    await db[b.COL_HUNTBOT].delete_many({})
    await hb_row(db, "9M")
    sent = []
    async def fake_notify(text, dm=True, min_gap=90, target="owner", images=None):
        sent.append((text, target)); return True
    real_notify, b.notify_owner = b.notify_owner, fake_notify
    try:
        check("nhắc: mặc định TẮT (app tự thông báo) -> bot không DM", await b.hb_reminder_tick(now), None)
        await b.set_config("hb_alert", "on")
        check("nhắc: bật + còn 9 phút -> DM", await b.hb_reminder_tick(now), 9)
        check("nhắc: nội dung + gửi acc phụ", sent, [("⏰ Huntbot còn khoảng 9 phút nữa là về.", "alt")])
        check("nhắc: lần sau cùng chuyến -> KHÔNG lặp", await b.hb_reminder_tick(now), None)
        await db[b.COL_HUNTBOT].delete_many({}); await hb_row(db, "3H 0M")
        check("nhắc: còn 3 giờ -> chưa nhắc", await b.hb_reminder_tick(now), None)
    finally:
        b.notify_owner = real_notify

    # 7) dữ liệu /alerts cho app
    await db[b.COL_HUNTBOT].delete_many({}); await hb_row(db, "9M")
    t = await b._huntbot_timing(b._utcnow())
    check("alerts: huntbot đang săn, còn ~9 phút", (t["hunting"], 530 <= t["seconds_left"] <= 540, t["ready_epoch"] is not None),
          (True, True, True))
    await db[b.COL_HUNTBOT].delete_many({}); await hb_row(db, "9M", hunting=False)
    t = await b._huntbot_timing(b._utcnow())
    check("alerts: huntbot không săn -> không có giờ về", (t["hunting"], t["seconds_left"], t["ready_epoch"]), (False, None, None))
    await db[b.COL_HUNTBOT].delete_many({})
    t = await b._huntbot_timing(b._utcnow())
    check("alerts: chưa có dữ liệu huntbot -> rỗng, không lỗi", (t["hunting"], t["seconds_left"]), (False, None))

asyncio.run(scenarios())

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test auto_refresh pass.")
