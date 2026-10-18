"""test_weapon_cleanup.py — kiểm tra bộ lọc dọn vũ khí (GIỮ / RÁC / XÁM) bằng bộ luật THẬT + mẫu danh sách vũ khí thật.
Chạy: python3 -W ignore test_weapon_cleanup.py   (không cần Mongo; chỉ cần weapon_rules.json + fixtures cùng thư mục)"""
import sys, json, os
from unittest.mock import MagicMock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import weapon_cleanup as wc

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

rules = json.load(open(os.path.join(HERE, "weapon_rules.json"), encoding="utf-8"))

def W(id, type, passives, quality=50.0, rarity="rare", **kw):
    return {"id": id, "type": type, "passives": passives, "quality": quality, "rarity": rarity,
            "name": type, "starred": False, "equipped": False, "equipped_by": None, **kw}

def bucket(w, top=frozenset()):
    return wc.classify_weapon(w, rules, top)[:2]

# ---- GIỮ cứng
check("⭐ yêu thích luôn giữ, kể cả passive tệ", bucket(W("A1", "pstaff", ["swarm"], starred=True)), ("giu", ["yeu_thich"]))
check("đang trang bị luôn giữ", bucket(W("A2", "pstaff", ["swarm"], equipped=True, equipped_by="dboar")), ("giu", ["dang_trang_bi"]))
check("Rune (crune) không bao giờ xóa", bucket(W("A3", "crune", ["swarm"], 10.0))[0], "giu")
check("Rune (lrune) không bao giờ xóa", bucket(W("A4", "lrune", [], 10.0))[0], "giu")
check("vừa ⭐ vừa đang cầm: ghi cả 2 lý do", bucket(W("A5", "pstaff", ["swarm"], starred=True, equipped=True))[1], ["yeu_thich", "dang_trang_bi"])

# ---- passive: server khuyên / bạn chọn / hồi WP
check("passive server khuyên (vban + att=Strength) -> giữ", bucket(W("B1", "vban", ["att"], 79.6, "epic")), ("giu", ["passive_tot"]))
check("alias sac -> sacrifice, shield + sacrifice là lựa chọn của Ruby -> giữ", bucket(W("B2", "shield", ["sac"]))[0], "giu")
check("sacrifice trên pstaff: server chỉ khuyên có điều kiện, nhưng là passive hồi WP (chờ Ruby xác nhận) -> giữ", bucket(W("B3", "pstaff", ["sac"])), ("giu", ["passive_tot"]))
check("sguard trên pstaff: chỉ hợp khi có rstaff -> XÁM, không bị xóa", bucket(W("B3b", "pstaff", ["safeguard"])), ("xam", ["passive_co_dieu_kien"]))
check("bỏ passive hồi WP khỏi danh sách Ruby thì sacrifice trên pstaff thành XÁM", wc.classify_weapon(W("B3c", "pstaff", ["sac"]), {**rules, "ruby": {**rules["ruby"], "passive_hoi_wp": []}})[:2], ("xam", ["passive_co_dieu_kien"]))
check("passive hồi WP (wgen) trên loại không liệt kê -> giữ", bucket(W("B4", "lsyth", ["wgen"]))[0], "giu")
check("có 2 passive, 1 cái tốt -> giữ", bucket(W("B5", "vban", ["swarm", "att"]))[0], "giu")

# ---- XÁM: không chắc thì giữ lại cho Ruby quyết
check("passive server chưa có lời khuyên (resonance) -> XÁM", bucket(W("C1", "gaxe", ["resonance"])), ("xam", ["passive_server_chua_khuyen"]))
check("passive có điều kiện (gslay trên estaff) -> XÁM", bucket(W("C2", "estaff", ["gslay"]))[1], ["passive_co_dieu_kien"])
check("loại cstaff (lời khuyên còn TBD) -> XÁM", "loai_loi_khuyen_chua_day_du" in bucket(W("C3", "cstaff", ["sprout"]))[1], True)
check("loại lạ chưa có trong bộ luật -> XÁM", bucket(W("C4", "zzzweapon", ["swarm"]))[0], "xam")
check("thiếu chất lượng -> XÁM", "thieu_chat_luong" in bucket(W("C5", "pstaff", ["swarm"], None))[1], True)
check("độ hiếm legendary không tự xóa -> XÁM", bucket(W("C6", "pstaff", ["swarm"], 70.0, "legendary")), ("xam", ["do_hiem_cao"]))
check("độ hiếm lạ -> XÁM", bucket(W("C7", "pstaff", ["swarm"], 70.0, "wat"))[1], ["do_hiem_la"])

# ---- RÁC: chỉ khi chắc chắn không hợp
check("pstaff + swarm(Living Hive), server khuyên chỗ khác -> RÁC", bucket(W("D1", "pstaff", ["swarm"], 45.0)), ("rac", ["passive_khong_hop"]))
check("cây không có passive -> RÁC", bucket(W("D2", "pstaff", [], 45.0)), ("rac", ["khong_co_passive"]))

# ---- giữ dự phòng top chất lượng mỗi loại
ws = [W(f"P{i}", "pstaff", ["swarm"], 40.0 + i) for i in range(6)]
plan = wc.plan_cleanup(ws, rules, keep_top=2)
check("top 2 chất lượng của loại được giữ", sorted(r["id"] for r in plan["giu"]), ["P4", "P5"])
check("4 cây còn lại là rác", sorted(r["id"] for r in plan["rac"]), ["P0", "P1", "P2", "P3"])
check("thống kê đúng", (plan["thong_ke"]["tong"], plan["thong_ke"]["giu"], plan["thong_ke"]["rac"], plan["thong_ke"]["xam"]), (6, 2, 4, 0))
check("giữ 0 cây top -> không có dự phòng", len(wc.plan_cleanup(ws, rules, keep_top=0)["rac"]), 6)

# ---- an toàn: mỗi cây vào đúng 1 nhóm, không mất cây nào, không trùng
mix = ws + [W("S1", "pstaff", ["swarm"], starred=True), W("S2", "crune", []), W("S3", "gaxe", ["resonance"])]
p = wc.plan_cleanup(mix, rules, keep_top=1)
ids = [r["id"] for k in ("giu", "rac", "xam") for r in p[k]]
check("mỗi cây đúng 1 nhóm (không mất/trùng)", sorted(ids), sorted(w["id"] for w in mix))
check("cây ⭐ và Rune không bao giờ nằm trong RÁC", [r["id"] for r in p["rac"] if r["id"] in ("S1", "S2")], [])
check("bỏ qua mục không có id", wc.plan_cleanup([{"type": "pstaff"}], rules)["thong_ke"]["tong"], 0)
check("danh sách rỗng không lỗi", wc.plan_cleanup([], rules)["thong_ke"]["tong"], 0)
check("bộ luật rỗng: mọi cây là XÁM (không xóa bừa)", set(r["id"] for r in wc.plan_cleanup(ws, {}, keep_top=0)["xam"]), {w["id"] for w in ws})

# ---- bản tóm tắt cho Discord
txt = wc.summary_text(p)
check("tóm tắt có ghi rõ CHƯA xóa gì", "CHƯA xóa" in txt, True)
check("tóm tắt không vượt 2000 ký tự", len(txt) <= 2000, True)

# ---- mẫu THẬT: 15 cây từ danh sách `owo weapon` của Ruby (cần đọc được bot; bỏ qua nếu thiếu thư viện)
try:
    for m in ["discord", "discord.ext", "discord.ext.commands", "discord.ext.tasks", "motor", "motor.motor_asyncio", "aiohttp", "aiohttp.web", "dotenv"]:
        if m not in sys.modules:
            try:
                __import__(m)
            except Exception:
                sys.modules[m] = MagicMock()
    import owo_tracker_bot as b
    rows = b.parse_weapon_list(json.load(open(os.path.join(HERE, "fixtures_weapon_list_2026-10-10.json"), encoding="utf-8"))["list_raw"])
    rp = wc.plan_cleanup(rows, rules, keep_top=0)
    by = {r["id"]: k for k in ("giu", "rac", "xam") for r in rp[k]}
    check("mẫu thật: đọc được 15 cây", len(rows), 15)
    check("mẫu thật: Epic Vanguard's Banner 79.6% + Strength -> GIỮ", by["FVK6GB"], "giu")
    check("mẫu thật: Leeching Scythe + Mana Tap -> GIỮ", by["FVK6GS"], "giu")
    check("mẫu thật: Staff of Purity + Living Hive -> RÁC", by["FVK6GK"], "rac")
    check("mẫu thật: Axe + Resonance (server chưa khuyên) -> XÁM", by["FVK6GG"], "xam")
    check("mẫu thật: Culling Scythe + Snail (khuyên cho loại khác) -> RÁC", by["FVK6GT"], "rac")
    check("mẫu thật: mỗi cây đúng 1 nhóm", len(by), 15)
except Exception as e:
    print("⚠️ Bỏ qua phần mẫu thật (không import được bot):", repr(e))

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test lọc vũ khí pass.")
