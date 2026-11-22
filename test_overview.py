"""test_overview.py — gom số liệu thống kê cho ,thongke. Chạy: python test_overview.py"""
import sys
import overview as ov

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# --- bot chưa thấy gì ---
g = ov.build_groups({})
total, filled = ov.count_metrics(g)
by = {x["key"]: x for x in g}
check("mọi nhóm có dòng cố định đúng nhãn (không sót/thừa)", {k: [l for l, _ in by[k]["lines"]] for k in ov.FIXED_LABELS}, ov.FIXED_LABELS)
check("tổng số dòng khi chưa có dữ liệu = số thông số cố định", total, ov.FIXED_COUNT)
check("chưa có dữ liệu: chỉ 'quá nhanh = 0' là có giá trị", filled, 1)
check("hub=None không lỗi", ov.count_metrics(ov.build_groups(None)), (ov.FIXED_COUNT, 1))
print(f"   (số thông số cố định: {ov.FIXED_COUNT}, trong {len(ov.FIXED_LABELS)} nhóm)")

# --- có dữ liệu ---
hub = {
    "cowoncy": {"amount": 1234567, "age_seconds": 30}, "weapon_shards": {"amount": 88},
    "daily": {"state": "ready", "streak": 12, "last_reward": 500, "seconds_left": 3900, "age_seconds": 100},
    "huntbot": {"hunting": True, "progress_pct": 42, "animals_captured": 7, "essence": 1500, "seconds_left": 7500, "age_seconds": 4000},
    "quest": {"seals": 3, "all_done": False, "next_quest_seconds": 600, "quests": [{}, {}, {}], "age_seconds": 90000},
    "gems": {"equipped": [{"slot": "1", "type_name": "Hunting", "tier": "legendary", "current": 40, "max": 100, "percent": 40},
                          {"slot": "2", "type_name": "Empowering", "tier": "epic", "current": 5, "max": 50, "percent": 10}],
             "spare": [{"count": 3}, {"count": 2}]},
    "zoo": {"zoo_points": 99000, "total_pets": 500, "caught_total": 12000, "unlocked_total": 80, "sacrificed_pets": [{}, {}],
            "by_tier": {"common": {"species": 5, "total": 300, "sacrificed": 4}, "rare": {"species": 2, "total": 9, "sacrificed": 1}}},
    "pet_dex": {"total_known": 40, "total_owned": 30, "species": [{"rank": "common", "owned": True}, {"rank": "common", "owned": True},
                                                               {"rank": "rare", "owned": True}, {"rank": "rare", "owned": False}]},
    "inventory": {"kinds": 9, "total_items": 321, "items": [{"code": "1", "name": "Lootbox", "count": 200, "is_gem": False},
                                                            {"code": "2", "name": "Gem", "count": 7, "is_gem": True}]},
    "weapon_review": {"active": True, "kept": 5, "dropped": 3, "remaining": 2, "unknown": 1, "unseen": 0},
    "event_mode": True, "bot_version": "v1.58",
    "weapons": {"count": 14},
    "team": {"members": [{"hp": 100, "att": 10, "pr": 5, "wp": 20, "mag": 7, "mr": 3, "level": 30, "weaponId": "ab", "quality": 80},
                         {"hp": 50, "att": None, "level": 20, "weaponId": None, "quality": None}]},
    "battle": {"result": "win", "turns": 6, "xp": 120, "streak": 4, "best_streak": 9, "last_lost_streak": 2},
    "event": {"counters": [{"kind": "hunt", "current": 4, "max": 10}], "recent": [{}, {}]},
    "event_pets": {"found_count": 1, "total": 2, "ends_epoch": 1795939140,
                   "pets": [{"label": "Pumpkin Pie", "found": True, "age_seconds": 7300}, {"label": "Autumn Hsin", "found": False}]},
    "new_pets": {"pets": [{}]}, "slowdown": {"count_30m": 2}, "captcha": {"active": False},
    "checklists": {"daily": {"progress": "3/5"}, "weekly": {"progress": {"a": 1}}},
}
rows = [{"rarity": "epic", "type": "sword", "quality": 80.0, "passives": ["a"], "starred": True, "equipped": True},
        {"rarity": "epic", "type": "bow", "quality": 60.0, "passives": [], "starred": False, "equipped": False},
        {"rarity": "rare", "type": "sword", "quality": None, "passives": [], "starred": False, "equipped": False}]
wl = ov.summarize_weapon_rows(rows)
check("tóm tắt kho vũ khí", (wl["total"], wl["starred"], wl["equipped"], wl["with_passive"], wl["q_avg"], wl["q_max"], wl["q_min"],
      wl["by_rarity"], wl["by_type"]), (3, 1, 1, 1, 70.0, 80.0, 60.0, {"epic": 2, "rare": 1}, {"sword": 2, "bow": 1}))
check("chưa quét vũ khí -> None", (ov.summarize_weapon_rows([]), ov.summarize_weapon_rows(None)), (None, None))
extras = {"weapon_list": wl,
          "counts": {"species": 120, "unlocked": 80, "weapon_types": 9, "passives": 14, "emoji": 300, "zoo_history": 25,
                     "notes": 3, "pending_commands": 0, "event_pets": 1},
          "config": {"app_off": False, "auto_check": True, "hb_alert": False, "hb_auto": True}}
g = ov.build_groups(hub, extras)
by = {x["key"]: dict(x["lines"]) for x in g}
check("gem: thấp/cao nhất và số viên dưới 20%", (by["gems"]["Gem thấp nhất (%)"], by["gems"]["Gem cao nhất (%)"], by["gems"]["Gem dưới 20%"]), ("10%", "40%", "1"))
check("zoo: loài đang có, hiến tế, bậc nhiều nhất", (by["zoo"]["Loài đang có (theo bậc)"], by["zoo"]["Con đã hiến tế (theo bậc)"], by["zoo"]["Bậc nhiều pet nhất"]), ("7", "5", "common (300 con)"))
check("dex: chưa có, tỉ lệ, rank", (by["dex"]["Loài chưa có"], by["dex"]["Tỉ lệ đang có"], by["dex"]["Theo rank"]), ("10", "75.0%", "common ×2 · rare ×1"))
check("kho: gem và món nhiều nhất", (by["inventory"]["Số gem trong kho"], by["inventory"]["Món nhiều nhất"]), ("7", "Lootbox ×200"))
check("vũ khí đã quét", (by["weapons"]["Vũ khí đã quét danh sách"], by["weapons"]["Chất lượng TB"], by["weapons"]["Theo độ hiếm"], by["weapons"]["Theo loại"]),
      ("3", "70.0%", "epic ×2 · rare ×1", "sword ×2 · bow ×1"))
check("duyệt vũ khí", (by["review"]["Đang duyệt"], by["review"]["Đã giữ"], by["review"]["Còn lại"]), ("Có", "5", "2"))
check("đội hình: level, vũ khí", (by["team"]["Level TB"], by["team"]["Level cao nhất"], by["team"]["Pet đang cầm vũ khí"], by["team"]["Chất lượng vũ khí TB"]), ("25.0", "30", "1", "80.0%"))
check("dữ liệu đã học + cài đặt", (by["knowledge"]["Loài pet đã biết"], by["knowledge"]["Lệnh đang chờ app"], by["config"]["Hub (app)"], by["config"]["Tự kiểm tra"],
      by["config"]["Cảnh báo HuntBot"], by["config"]["Chế độ Event"], by["config"]["Phiên bản bot"]), ("120", "0", "BẬT", "BẬT", "tắt", "Có", "v1.58"))
check("Hub tắt thì ghi rõ", dict(ov.build_groups({}, {"config": {"app_off": True}})[-1]["lines"])["Hub (app)"], "tắt (bot không giao việc)")
check("cowoncy có dấu phẩy ngăn cách", by["cowoncy"]["Cowoncy"], "1,234,567")
check("daily: còn lại dạng 1h05m", by["daily"]["Nhận lại sau"], "1h05m")
check("huntbot: tiến độ + còn lại", (by["huntbot"]["Tiến độ"], by["huntbot"]["Còn lại"], by["huntbot"]["Đang hunt"]), ("42%", "2h05m", "Có"))
check("quest: số quest, kế tiếp", (by["quest"]["Số quest"], by["quest"]["Quest kế tiếp"]), ("3", "10m"))
check("gem: slot + dự phòng", (by["gems"]["Slot Hunting (legendary)"], by["gems"]["Gem dự phòng (số viên)"], by["gems"]["Gem dự phòng (số loại)"], by["gems"]["Gem đang dùng"]),
      ("40/100 (40%)", "5", "2", "2"))
check("zoo: theo bậc + đã hiến tế", (by["zoo"]["Theo bậc"], by["zoo"]["Loài đã hiến tế hết"]), ("common 5 loài/300 con · rare 2 loài/9 con", "2"))
check("đội hình: tổng bỏ qua giá trị thiếu", (by["team"]["Số pet trong đội"], by["team"]["Tổng HP"], by["team"]["Tổng ATT"], by["team"]["Tổng MR"]), ("2", "150", "10", "3"))
check("battle", (by["battle"]["Kết quả"], by["battle"]["Chuỗi thắng cao nhất"]), ("win", "9"))
check("sự kiện: tiến độ, pet, kết thúc, tin đã ghi", (by["event"]["Tiến độ săn (hunt)"], by["event"]["Pet sự kiện đã tìm"], by["event"]["Tin sự kiện đã ghi"], by["event"]["Kết thúc"]),
      ("4/10", "1/2", "2", "<t:1795939140:R>"))
check("sự kiện: từng pet rõ tìm/chưa", (by["event"]["✅ Pumpkin Pie"], by["event"]["⬜ Autumn Hsin"]), ("đã tìm thấy · lần cuối 2 giờ trước", "chưa tìm thấy"))
check("khác: pet mới, quá nhanh, captcha", (by["misc"]["Pet mới chưa vào zoo"], by["misc"]["Lần bị OwO báo quá nhanh (30 phút)"], by["misc"]["Captcha"]), ("1", "2", "không"))
check("checklist: số thì in, dạng lạ thì 'đã ghi nhận'", (by["checklist"]["Checklist Daily"], by["checklist"]["Checklist Weekly"]), ("3/5", "đã ghi nhận"))
total, filled = ov.count_metrics(g)
check("đủ dữ liệu: mọi dòng đều có giá trị", filled, total)

# --- embed ---
f = ov.embed_fields(g)
check("tiêu đề mục kèm tuổi dữ liệu", f[0][0], "💰 Tiền & vật phẩm hiếm · vừa xong")
check("tuổi dạng phút/giờ/ngày", (ov.ago(120), ov.ago(7200), ov.ago(200000), ov.ago(None)), ("2 phút trước", "2 giờ trước", "2 ngày trước", ""))
check("chưa có dữ liệu thì in nghiêng", ov.embed_fields(ov.build_groups({}))[0][1], "Cowoncy: _chưa có dữ liệu_\nWeapon shards: _chưa có dữ liệu_")
check("mỗi mục ≤ 1000 ký tự", all(len(v) <= ov.FIELD_MAX and len(n) <= 256 for n, v in ov.embed_fields(ov.build_groups({"zoo": {"by_tier": {f"t{i}": {"species": 1, "total": 1} for i in range(200)}}}))), True)
chunks = ov.chunk_fields(f)
check("gói embed: ≤25 mục và ≤ ngân sách ký tự mỗi embed", all(len(c) <= 25 and sum(len(n) + len(v) for n, v in c) <= ov.EMBED_CHAR_BUDGET for c in chunks), True)
big = [("t" * 100, "v" * 900)] * 10
check("nhiều mục dài thì tách thành nhiều embed", (len(ov.chunk_fields(big)) > 1, sum(len(c) for c in ov.chunk_fields(big))), (True, 10))
print("\nTất cả pass" if not fails else f"\n{len(fails)} lỗi: {fails}")
sys.exit(1 if fails else 0)
