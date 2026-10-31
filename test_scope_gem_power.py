"""test_scope_gem_power.py — theo dõi cả SERVER (,setserver), gem hiện 0/xx thì thay NGAY, công tắc Hub bật/tắt (/power).
Chạy: python test_scope_gem_power.py"""
import sys, asyncio, json
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

# ---------- phạm vi: hàm thuần ----------
S = b.scope_allows
check("phạm vi: không giới hạn -> mọi nơi", S("", "", 1, 2), True)
check("phạm vi: không giới hạn -> cả tin riêng", S("", "", None, 2), True)
check("phạm vi: theo server, đúng server (kênh nào cũng được)", S("900", "", 900, 5), True)
check("phạm vi: theo server, server khác -> bỏ", S("900", "", 800, 5), False)
check("phạm vi: theo server, tin riêng -> bỏ", S("900", "", None, 5), False)
check("phạm vi: theo kênh, đúng kênh", S("", "42", 1, 42), True)
check("phạm vi: theo kênh, kênh khác -> bỏ", S("", "42", 1, 43), False)
check("phạm vi: server thắng kênh khi đặt cả hai", S("900", "42", 900, 7), True)

async def scenarios():
    db = b.mdb = AsyncMongoMockClient()["scope_test"]
    await b.set_config("tracked_user_id", "555")
    b.tracked_names.clear(); b.pending_commands.clear(); b.last_owo_command.clear()
    b._last_farm_channel["id"] = None
    async def noop(msg): return None
    orig_pc, b.bot.process_commands = b.bot.process_commands, noop
    me = NS(id=555, display_name="Ruby", global_name="Ruby", nick=None, name="ruby")
    def cmd(text, ch, guild):
        return NS(content=text, author=me, guild=NS(id=guild) if guild else None, channel=NS(id=ch))
    def owo(text, ch, guild):
        return NS(content=text, embeds=[], components=[], guild=NS(id=guild) if guild else None,
                  author=NS(id=b.OWO_BOT_ID, bot=True), channel=NS(id=ch), reference=None, id=1)
    async def cash():
        hub = await b.build_hub()
        return (hub.get("cowoncy") or {}).get("amount")
    try:
        # ===== theo dõi cả SERVER 900 =====
        await b.set_config("tracked_guild_id", "900"); await b.set_config("tracked_channel_id", "")
        await b.on_message(cmd("owo cash", 111, 900)); await b.on_message(owo("Ruby, you currently have 500 cowoncy!", 111, 900))
        check("server: kênh 111 của server 900 được đọc", await cash(), 500)
        await b.on_message(cmd("owo cash", 222, 900)); await b.on_message(owo("Ruby, you currently have 700 cowoncy!", 222, 900))
        check("server: kênh 222 (kênh KHÁC, cùng server) cũng được đọc", await cash(), 700)
        await b.on_message(cmd("owo cash", 333, 800)); await b.on_message(owo("Ruby, you currently have 999999 cowoncy!", 333, 800))
        check("server: server khác (800) bị bỏ qua", await cash(), 700)
        check("server: lệnh ở server khác không tính là lệnh chờ", 333 in b.pending_commands, False)
        await b.on_message(owo("Ruby, you currently have 999998 cowoncy!", 5, None))
        check("server: tin riêng (DM) bị bỏ qua", await cash(), 700)
        b.pending_commands.clear()   # không có lệnh chờ ở kênh 444
        await b.on_message(owo("Ruby, you currently have 321 cowoncy!", 444, 900))
        check("server: đã biết tên -> đọc cả tin OwO ở kênh chưa gõ lệnh (không cần đợi lệnh)", await cash(), 321)

        # nhớ kênh farm gần nhất
        await b.on_message(cmd("owo hunt", 222, 900))
        check("server: nhớ kênh gần nhất Ruby gõ lệnh", await b.get_config("last_farm_channel_id"), "222")
        check("server: kênh nhận tag = kênh gần nhất", await b.notify_channel_id(), "222")
        ch = await b._hub_channel()
        check("server: link mở Discord vào đúng kênh gần nhất", (ch["id"], ch["link"]),
              ("222", "https://discord.com/channels/900/222"))
        await b.set_config("last_farm_channel_id", "")
        ch = await b._hub_channel()
        check("server: chưa biết kênh -> link vào cả server", ch["link"], "https://discord.com/channels/900")

        # ===== giới hạn 1 KÊNH vẫn như cũ =====
        await b.set_config("tracked_guild_id", ""); await b.set_config("tracked_channel_id", "42")
        check("kênh: kênh nhận tag = kênh chỉ định", await b.notify_channel_id(), "42")
        await b.set_config("tracked_channel_id", "")
        check("không giới hạn: không có kênh nhận tag", await b.notify_channel_id(), None)
    finally:
        b.bot.process_commands = orig_pc

    # ===== lệnh ,setserver =====
    sent = []
    async def fake_send(text=None, **kw): sent.append(text)
    in_server = NS(send=fake_send, guild=NS(id=900, name="Server Của Ruby"))
    in_dm = NS(send=fake_send, guild=None)
    await b.set_config("tracked_channel_id", "42")
    await b.setserver_cmd(in_server, arg="here")
    check("setserver here: lưu server", await b.get_config("tracked_guild_id"), "900")
    check("setserver here: bỏ giới hạn 1 kênh", await b.get_config("tracked_channel_id"), "")
    await b.setserver_cmd(in_server, arg="")
    check("setserver rỗng: báo đang theo dõi cả server", "cả server" in sent[-1] and "900" in sent[-1], True)
    await b.setserver_cmd(in_dm, arg="here")
    check("setserver here trong tin riêng: báo lỗi, không đổi", ("phải gõ trong một server" in sent[-1], await b.get_config("tracked_guild_id")), (True, "900"))
    await b.setserver_cmd(in_server, arg="abc")
    check("setserver sai ID: báo lỗi, không đổi", ("Không đọc được" in sent[-1], await b.get_config("tracked_guild_id")), (True, "900"))
    await b.setserver_cmd(in_server, arg="777")
    check("setserver <ID>: dán thẳng ID server", await b.get_config("tracked_guild_id"), "777")
    await b.setchannel_cmd(in_server, arg="42")
    check("setchannel sau đó: thay cho giới hạn server", (await b.get_config("tracked_guild_id"), await b.get_config("tracked_channel_id")), ("", "42"))
    await b.setserver_cmd(in_server, arg="xoa")
    check("setserver xoa: bỏ giới hạn server", await b.get_config("tracked_guild_id"), "")

    # ===== gem hiện 0/xx =====
    b.mdb = AsyncMongoMockClient()["gem_test"]; b.gem_missing_streak.clear()
    def hunt(*gems):
        body = " ".join(f"<:{n}:{i}>`[{c}/{m}]`" for i, (n, c, m) in enumerate(gems, 100))
        return f"**🌱 | Ruby**, hunt is empowered by {body}!"
    gs = b.parse_hunt_gem_status(hunt(("cgem1", 0, 50), ("cgem3", 40, 50)))
    out = await b.save_gem_status(gs, "555")
    check("gem 0/50 -> báo hết NGAY (không đợi 2 tin hunt thiếu gem)", out, {"1"})
    doc = await b.mdb[b.COL_GEM_STATUS].find_one({"_id": "1"})
    check("gem 0/50: vẫn lưu trạng thái 0/50 cho Hub (chưa xoá)", (doc["current"], doc["max"]), (0, 50))
    b.gem_missing_streak.clear()
    gs = b.parse_hunt_gem_status(hunt(("cgem1", 12, 50), ("cgem3", 40, 50)))
    check("gem còn độ bền (12/50, 40/50) -> không báo", await b.save_gem_status(gs, "555"), set())
    gs = b.parse_hunt_gem_status(hunt(("cgem1", 11, 50)))
    check("gem slot 3 vắng 1 tin -> chưa báo (vẫn chờ xác nhận 2 tin như cũ)", await b.save_gem_status(gs, "555"), set())
    gs = b.parse_hunt_gem_status(hunt(("cgem1", 10, 50)))
    check("gem slot 3 vắng tin thứ 2 -> báo hết (hành vi cũ giữ nguyên)", await b.save_gem_status(gs, "555"), {"3"})

    # đầu-cuối: gem 0/50 + kho còn gem -> xếp lệnh `owo use` ngay
    b.mdb = AsyncMongoMockClient()["gem_e2e"]; b.gem_missing_streak.clear()
    b._app_off_cache.update({"v": None, "at": 0})
    await b.mdb[b.COL_INVENTORY].insert_one({"_id": "051", "is_gem": True, "gem_slot": "1", "count": 3,
                                              "gem_tier": "Common", "gem_tier_rank": 1})
    said = []
    async def ch_send(text, **kw): said.append(text)
    msg = NS(channel=NS(send=ch_send, id=1))
    gs = b.parse_hunt_gem_status(hunt(("cgem1", 0, 50), ("cgem3", 40, 50)))
    vanished = await b.save_gem_status(gs, "555")
    await b.remind_gem_replacements(msg, vanished, "555")
    cmds = [c async for c in b.mdb[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending"})]
    check("đầu-cuối: gem 0/50 + kho còn gem -> xếp lệnh owo use NGAY",
          [(c["action"], c["params"]["command_text"]) for c in cmds], [("swap_gem", "owo use 051")])
    check("đầu-cuối: có nhắc trong kênh là gem vừa hết độ bền", any("hết độ bền" in (t or "") for t in said), True)

    # ===== công tắc Hub bật/tắt: /power =====
    b.mdb = AsyncMongoMockClient()["power_test"]; b._app_off_cache.update({"v": None, "at": 0})
    old_token, b.AUTOMACRO_API_TOKEN = b.AUTOMACRO_API_TOKEN, "tok"
    try:
        def req(body, token="tok"):
            async def j():
                if body is None: raise ValueError("no json")
                return body
            return NS(headers={"Authorization": f"Bearer {token}"}, json=j)
        r = await b.handle_post_power(req({"on": True}, token="sai"))
        check("power: sai token -> 401", r.status, 401)
        r = await b.handle_post_power(req({"on": "yes"}))
        check("power: body sai -> 400", r.status, 400)
        r = await b.handle_post_power(req(None))
        check("power: không có body -> 400", r.status, 400)
        r = await b.handle_post_power(req({"on": False}))
        check("power: Hub TẮT -> 200, app OFF", (r.status, json.loads(r.text)["off"], await b.is_app_off()), (200, True, True))
        check("power: Hub tắt -> bot KHÔNG giao việc cho app", await b.queue_automacro_command("swap_gem", {"command_text": "owo use 1"}), None)
        # Hub TẮT chỉ chặn việc giao việc cho app — bot VẪN theo dõi bình thường khi Ruby tự chơi
        await b.mdb[b.COL_AUTOMACRO_COMMANDS].insert_one(
            {"_id": 7, "action": "swap_gem", "params": {"command_text": "owo use 5"}, "status": "pending",
             "created_at": b._utcnow().isoformat(), "completed_at": None})
        r = await b.handle_post_power(req({"on": False}))
        pend = await b.mdb[b.COL_AUTOMACRO_COMMANDS].count_documents({"status": "pending"})
        check("power: Hub tắt -> hủy các lệnh đang chờ app (không tự chạy bất ngờ khi bật lại)",
              (json.loads(r.text)["cancelled"], pend), (1, 0))
        await b.set_config("tracked_user_id", "555"); b.tracked_names.clear(); b.pending_commands.clear()
        async def noop(msg): return None
        orig_pc, b.bot.process_commands = b.bot.process_commands, noop
        me = NS(id=555, display_name="Ruby", global_name="Ruby", nick=None, name="ruby")
        try:
            await b.set_config("tracked_guild_id", ""); await b.set_config("tracked_channel_id", "")
            await b.on_message(NS(content="owo cash", author=me, guild=NS(id=1), channel=NS(id=9)))
            await b.on_message(NS(content="Ruby, you currently have 4242 cowoncy!", embeds=[], components=[], guild=NS(id=1), id=1,
                                  reference=None, author=NS(id=b.OWO_BOT_ID, bot=True), channel=NS(id=9)))
        finally:
            b.bot.process_commands = orig_pc
        hub = await b.build_hub()
        check("Hub TẮT: bot VẪN đọc tin OwO khi Ruby tự chơi (số dư cập nhật)", (hub.get("cowoncy") or {}).get("amount"), 4242)
        check("Hub TẮT: vẫn báo giờ huntbot cho thông báo trên điện thoại (không phụ thuộc Hub)",
              (await b._huntbot_timing(b._utcnow()))["hunting"], False)
        r = await b.handle_post_power(req({"on": True}))
        check("power: Hub BẬT -> 200, app ON", (r.status, json.loads(r.text)["off"], await b.is_app_off()), (200, False, False))
        check("power: Hub bật -> giao việc lại bình thường", await b.queue_automacro_command("swap_gem", {"command_text": "owo use 1"}) is not None, True)
    finally:
        b.AUTOMACRO_API_TOKEN = old_token

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test scope/gem/power pass.")
