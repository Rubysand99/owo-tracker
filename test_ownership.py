"""test_ownership.py — bot KHÔNG đọc nhầm tin OwO của người khác trong server (quest, huntbot...).
Chạy: python test_ownership.py"""
import sys, asyncio, time
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

ME, OTHER = "111", "222"
V = b.owner_verdict

# ---------- nhận diện chủ tin (hàm thuần) ----------
check("chủ: tiêu đề Quest Log <@id> của mình", V(f"### 📜 <@{ME}>'s Quest Log\n-# Balance: **1**", ME, set())[0], "mine")
check("chủ: tiêu đề Quest Log <@id> của người khác", V(f"\n### 📜 <@{OTHER}>'s Quest Log\n-# x", ME, set())[0], "other")
check("chủ: ping đầu tin là mình", V(f"<@{ME}> **BEEP BOOP. I AM BACK WITH 5 ANIMALS**", ME, set())[0], "mine")
check("chủ: ping đầu tin là người khác", V(f"<@{OTHER}> **BEEP BOOP. I AM BACK WITH 5 ANIMALS**", ME, set())[0], "other")
check("chủ: tên ở dòng đầu khớp tên mình", V("**🌱 | Ruby**, hunt is empowered by", ME, {"Ruby"})[0], "mine")
check("chủ: tên ở dòng đầu là người khác", V("**🌱 | Nguoi Khac**, hunt is empowered by", ME, {"Ruby"})[0], "other")
check("chủ: chưa biết tên mình thì không kết luận 'other'", V("**🌱 | Nguoi Khac**, hunt is empowered by", ME, set())[0], None)
check("chủ: tin không có tên/mention -> None", V("BEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 9H 41M", ME, {"Ruby"})[0], None)
check("chủ: tracked_id không phải ID số (test/giả) -> không so mention", V("### <@999>'s Quest Log", "u1", set())[0], None)

# ---------- lệnh gần đây ----------
b.recent_owo_commands.clear()
b.record_recent_command(7, "owo hb 24h", ["owo", "o"])
b.record_recent_command(7, "owo hunt", ["owo", "o"])
check("lệnh gần đây: thấy hb dù sau đó có lệnh khác", b.command_recent(7, b.HB_COMMAND_RE), True)
check("lệnh gần đây: kênh khác không thấy", b.command_recent(8, b.HB_COMMAND_RE), False)
b.recent_owo_commands.clear()
b.record_recent_command(7, "owo hunt", ["owo"])
check("lệnh gần đây: chỉ gõ hunt -> không phải hb", b.command_recent(7, b.HB_COMMAND_RE), False)
b.recent_owo_commands.clear()
b.record_recent_command(7, "owo hb", ["owo"], now=time.time() - 60)
check("lệnh gần đây: hb đã quá 20 giây -> hết hiệu lực", b.command_recent(7, b.HB_COMMAND_RE), False)
b.recent_owo_commands.clear()
b.record_recent_command(7, "oah 24h", ["owo", "o"])
check("lệnh gần đây: prefix 'o' + 'ah' (autohunt) vẫn là hb", b.command_recent(7, b.HB_COMMAND_RE), True)

QUEST = "### 📜 <@{uid}>'s Quest Log\n-# Balance: **112** <:seal:1> Quest Seals\nUwU You finished all of your quests! Come back tomorrow! <3\n-# ⏰ Next quest: **<t:1790233200:R>**"
HB_STATUS = "**BEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 9H 41M**\n55.58% DONE | 2580 ANIMALS CAPTURED"
HB_BACK = "**BEEP BOOP. I AM BACK WITH 4512 ANIMALS, 95265 ESSENCE**"


async def scenarios():
    def msg(text, ch=5):
        return NS(content=text, embeds=[], components=[], channel=NS(id=ch), reference=None, id=1)

    async def fresh(name):
        b.mdb = AsyncMongoMockClient()[name]
        await b.load_emoji_cache()
        b.recent_owo_commands.clear()
        b.tracked_names.clear()
        await b.set_config("tracked_user_id", ME)

    async def count(col):
        return await b.mdb[col].count_documents({})

    # ----- Quest Log -----
    await fresh("own_quest")
    await b.handle_owo_response(msg(QUEST.format(uid=OTHER)), ME)
    check("quest của người khác -> KHÔNG lưu", await count(b.COL_QUEST), 0)
    raw = await b.mdb[b.COL_RAW].find_one({"_id": "foreign_skipped"})
    check("quest của người khác -> ghi nhận là tin bị bỏ qua", bool(raw), True)
    await b.handle_owo_response(msg(QUEST.format(uid=ME)), ME)
    check("quest của mình -> lưu", await count(b.COL_QUEST), 1)

    # ----- Huntbot không có tên người chơi -----
    await fresh("own_hb_nocmd")
    await b.handle_owo_response(msg(HB_STATUS), ME)
    check("huntbot không rõ chủ, bạn không gõ lệnh gì -> KHÔNG lưu", await count(b.COL_HUNTBOT), 0)

    await fresh("own_hb_otherCmd")
    b.record_recent_command(5, "owo hunt", ["owo"])
    await b.handle_owo_response(msg(HB_STATUS), ME)
    check("huntbot không rõ chủ, bạn chỉ vừa gõ hunt (đang farm) -> KHÔNG lưu", await count(b.COL_HUNTBOT), 0)

    await fresh("own_hb_cmd")
    b.record_recent_command(5, "owo hb", ["owo"])
    await b.handle_owo_response(msg(HB_STATUS), ME)
    check("bạn vừa gõ owo hb -> lưu", await count(b.COL_HUNTBOT), 1)
    h = await b.mdb[b.COL_HUNTBOT].find_one()
    check("huntbot lưu đúng: đang săn, còn 9H 41M", (h["hunting"], h["time_remaining"]), (True, "9H 41M"))

    await fresh("own_hb_expired")
    b.record_recent_command(5, "owo hb", ["owo"], now=time.time() - 120)
    await b.handle_owo_response(msg(HB_STATUS), ME)
    check("lệnh hb đã quá lâu -> tin huntbot không rõ chủ KHÔNG lưu", await count(b.COL_HUNTBOT), 0)

    await fresh("own_hb_ping_me")
    await b.handle_owo_response(msg(f"<@{ME}> {HB_BACK}"), ME)
    check("huntbot về có ping bạn (không cần lệnh) -> lưu", await count(b.COL_HUNTBOT), 1)

    await fresh("own_hb_ping_other")
    b.record_recent_command(5, "owo hb", ["owo"])          # kể cả khi bạn vừa gõ hb
    await b.handle_owo_response(msg(f"<@{OTHER}> {HB_BACK}"), ME)
    check("huntbot về có ping NGƯỜI KHÁC -> KHÔNG lưu", await count(b.COL_HUNTBOT), 0)

    await fresh("own_hb_reply_me")
    reply_me = NS(content=HB_STATUS, embeds=[], components=[], channel=NS(id=5), id=1,
                  reference=NS(resolved=NS(author=NS(id=int(ME)))))
    await b.handle_owo_response(reply_me, ME)
    check("OwO reply thẳng tin của bạn -> lưu (kể cả không có lệnh gần đây)", await count(b.COL_HUNTBOT), 1)

    # ----- Hub: giờ huntbot không bị người khác ghi đè -----
    await fresh("own_hb_overwrite")
    b.record_recent_command(5, "owo hb", ["owo"])
    await b.handle_owo_response(msg(HB_STATUS), ME)                          # của bạn: còn 9H 41M
    b.recent_owo_commands.clear()                                            # 1 phút sau: lệnh hb của bạn đã cũ
    b.record_recent_command(5, "owo hunt", ["owo"])                          # bạn farm tiếp
    await b.handle_owo_response(msg("**BEEP BOOP. I AM STILL HUNTING. I WILL BE BACK IN 1H 2M**\n10% DONE | 5 ANIMALS CAPTURED"), ME)  # người khác
    hub = await b._hub_huntbot(b._utcnow())
    check("người khác `owo hb` lúc bạn farm -> giờ huntbot của bạn giữ nguyên (~9h41m)",
          34800 <= (hub["seconds_left"] or 0) <= 34860, True)

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test nhận diện chủ tin pass.")
