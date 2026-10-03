"""test_v14.py — kiểm tra các sửa của bản v14 bằng tin OwO THẬT (không cần discord/motor/mongomock).
Chạy: python test_v14.py"""
import sys, types, asyncio
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

TEAM = """
`owo team add {animal} {pos}` Add an animal to your team
**[1] <a:slothbot:711772997320441897> **bot mắt đỏ**:** Lvl 35 `[1,085,152/1,501,625]`
<:hp:531620120410456064> `1130` <:wp:531620120976687114> `1060`
<:att:531616155450998794> `0100` <:mag:531616156231139338> `0100`
<:pr:531616156222488606> `50%` <:mr:531616156226945024> `50%`
`C2PRPT` <:mythic:416520808501084162> <:mrstaff:618001309362290691> <:msac:1107928502893826098> 82.7%
**[2] <a:gowl:418284974593277954> **con cu**:** Lvl 39 `[2,206,355/2,314,441]`
<:hp:531620120410456064> `1280` <:wp:531620120976687114> `0578`
<:att:531616155450998794> `0139` <:mag:531616156231139338> `0178`
<:pr:531616156222488606> `58%` <:mr:531616156226945024> `58%`
`FIWFAP` <:epic:416520722987614208> <:erstaff:618001309085466665> <:esac:1107928494329040968> 80.2%
Current Streak: 101 | Highest Streak: 685 ⭐
"""
team = b.parse_team(TEAM)
STATS = ("hp", "wp", "att", "mag", "pr", "mr")
check("team mới: slothbot đủ 6 chỉ số", {k: team[0][k] for k in STATS}, dict(hp=1130, wp=1060, att=100, mag=100, pr=50, mr=50))
check("team mới: gowl", {k: team[1][k] for k in STATS}, dict(hp=1280, wp=578, att=139, mag=178, pr=58, mr=58))
check("team mới: level/vũ khí/chất lượng", [(t["level"], t["weaponId"], t["quality"]) for t in team], [(35, "C2PRPT", 82.7), (39, "FIWFAP", 80.2)])

HUNT = ("**🌱 | Ruby**, hunt is empowered by <a:lgem1:492572124251422720>`[57/100]` "
        "<:mgem4:510366763993661440>`[253/525]`  !\n**<:blank:427371936482328596> |** You found:  :bee: :bug:")
check("gem: 2 viên đọc đúng", [(g["slot"], g["current"], g["max"]) for g in b.parse_hunt_gem_status(HUNT)["gems"]], [("1", 57, 100), ("4", 253, 525)])
check("tên người: tin hunt", b.speaker_name(HUNT), "Ruby")
check("tên người: tin cash", b.speaker_name("<:cowoncy:416043450337853441> **| Ruby**, you currently have **__2,499,349__ cowoncy!**"), "Ruby")
check("tên chủ: zoo", b.header_owner("🌿 🌱 🌳** Ruby's zoo! **🌳 🌿 🌱"), "Ruby")
check("tên chủ: kho", b.header_owner("**====== Ruby's Inventory ======**"), "Ruby")
check("tin team/huntbot không có tên", (b.speaker_name(TEAM), b.header_owner(TEAM)), (None, None))

INV2 = "`123`<:cstaff:1449685764966453349>⁰¹³    `124`<:stithe:1456101001152036895>⁰⁰⁹"
check("kho phần 2 (không tiêu đề) chỉ đọc khi bật continuation",
      (b.parse_inventory(INV2), [i["count"] for i in b.parse_inventory(INV2, continuation=True)["items"]]), (None, [13, 9]))

# v15: tên toàn ký hiệu không bị coi là người khác
check("tên ký hiệu: khớp nguyên văn", b.weapon_owner_matches("✨", {"✨"}), True)
check("tên ký hiệu: khác tên thì không khớp", b.weapon_owner_matches("✨", {"Ruby"}), False)
check("tên thường vẫn khớp không phân biệt hoa/thường/dấu cách", b.weapon_owner_matches("ruby  ", {"Ruby"}), True)
check("tên rỗng không khớp gì", b.weapon_owner_matches("", {"Ruby", ""}), False)

# v15: reply — chỉ bỏ khi CHẮC CHẮN OwO trả lời người khác
ns = types.SimpleNamespace
def reply_msg(author_id):
    return ns(reference=ns(resolved=ns(author=ns(id=author_id))))
check("reply: không có reference -> khong_co", b.reply_target(ns(reference=None), "5"), "khong_co")
check("reply: tin gốc đã bị xóa (không có author) -> khong_co (giữ tin)", b.reply_target(ns(reference=ns(resolved=ns())), "5"), "khong_co")
check("reply: trả lời bạn -> ban", b.reply_target(reply_msg(5), "5"), "ban")
check("reply: trả lời người khác -> nguoi_khac", b.reply_target(reply_msg(9), "5"), "nguoi_khac")
check("reply: message không có thuộc tính reference -> khong_co", b.reply_target(ns(), "5"), "khong_co")

# Luồng đầy đủ với DB giả tối thiểu
class Col:
    def __init__(s): s.d = {}
    async def update_one(s, f, u, upsert=False):
        k = f["_id"]; s.d.setdefault(k, {"_id": k}).update(u.get("$set", {}))
    async def find_one(s, f): return s.d.get(f.get("_id"))
    async def delete_one(s, f): s.d.pop(f["_id"], None)
    def find(s, f=None):
        rows = list(s.d.values())
        class Cur:
            def sort(c, *a): return c
            async def to_list(c, length=None): return rows
        return Cur()
class DB(dict):
    def __getitem__(s, k): return s.setdefault(k, Col())
b.mdb = DB()
b.flatten_message = lambda m: m._t
def msg(t, ch=1):
    m = types.SimpleNamespace(channel=types.SimpleNamespace(id=ch)); m._t = t; return m

async def run():
    b.inv_session.clear()
    await b.handle_owo_response(msg("**====== Ruby's Inventory ======**\n`051`<:cgem1:492572122120585240>¹¹⁸"), "u1")
    n1 = len(b.mdb[b.COL_INVENTORY].d)
    await b.handle_continuation_only(msg(INV2), "u1")  # cửa sổ lệnh đã đóng
    check("kho: phần 2 được ghép dù cửa sổ lệnh đã đóng", (n1, len(b.mdb[b.COL_INVENTORY].d)), (1, 3))

    b.tracked_names["u1"] = {"Ruby"}
    await b.handle_owo_response(msg(HUNT.replace("| Ruby**", "| Linh**"), 2), "u1")
    check("người khác: gem KHÔNG bị ghi", len(b.mdb[b.COL_GEM_STATUS].d), 0)
    check("người khác: bot nhớ tên bị bỏ để ,status báo", (b.skipped_foreign["name"], b.skipped_foreign["count"]), ("Linh", 1))
    await b.handle_owo_response(msg(HUNT, 2), "u1")
    check("của mình: gem được ghi", sorted(b.mdb[b.COL_GEM_STATUS].d), ["1", "4"])
    await b.set_config("tracked_user_id", "5")
    await b.record_raw("kiem_tra", "x", {}, ns(channel=ns(id=2), reference=ns(resolved=ns(author=ns(id=5)))))
    check("record_raw ghi reply_to để biết OwO có dùng reply không", b.mdb[b.COL_RAW].d["kiem_tra"]["reply_to"], "ban")

asyncio.run(run())
print("\n❌ CÓ LỖI:" if fails else "\n✅ Toàn bộ test v14 pass", fails or "")
sys.exit(1 if fails else 0)
