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
    "gems": {"equipped": [{"slot": "1", "type_name": "Hunting", "tier": "legendary", "current": 40, "max": 100, "percent": 40}],
             "spare": [{"count": 3}, {"count": 2}]},
    "zoo": {"zoo_points": 99000, "total_pets": 500, "caught_total": 12000, "unlocked_total": 80, "sacrificed_pets": [{}, {}],
            "by_tier": {"common": {"species": 5, "total": 300}, "rare": {"species": 2, "total": 9}}},
    "pet_dex": {"total_known": 40, "total_owned": 33},
    "inventory": {"kinds": 9, "total_items": 321},
    "weapons": {"count": 14},
    "team": {"members": [{"hp": 100, "att": 10, "pr": 5, "wp": 20, "mag": 7, "mr": 3}, {"hp": 50, "att": None}]},
    "battle": {"result": "win", "turns": 6, "xp": 120, "streak": 4, "best_streak": 9, "last_lost_streak": 2},
    "event": {"counters": [{"kind": "hunt", "current": 4, "max": 10}], "recent": [{}, {}]},
    "event_pets": {"found_count": 1, "total": 2},
    "new_pets": {"pets": [{}]}, "slowdown": {"count_30m": 2}, "captcha": {"active": False},
    "checklists": {"daily": {"progress": "3/5"}, "weekly": {"progress": {"a": 1}}},
}
g = ov.build_groups(hub)
by = {x["key"]: dict(x["lines"]) for x in g}
check("cowoncy có dấu phẩy ngăn cách", by["cowoncy"]["Cowoncy"], "1,234,567")
check("daily: còn lại dạng 1h05m", by["daily"]["Nhận lại sau"], "1h05m")
check("huntbot: tiến độ + còn lại", (by["huntbot"]["Tiến độ"], by["huntbot"]["Còn lại"], by["huntbot"]["Đang hunt"]), ("42%", "2h05m", "Có"))
check("quest: số quest, kế tiếp", (by["quest"]["Số quest"], by["quest"]["Quest kế tiếp"]), ("3", "10m"))
check("gem: slot + dự phòng", (by["gems"]["Slot Hunting (legendary)"], by["gems"]["Gem dự phòng (số viên)"], by["gems"]["Gem dự phòng (số loại)"], by["gems"]["Gem đang dùng"]),
      ("40/100 (40%)", "5", "2", "1"))
check("zoo: theo bậc + đã hiến tế", (by["zoo"]["Theo bậc"], by["zoo"]["Loài đã hiến tế hết"]), ("common 5 loài/300 con · rare 2 loài/9 con", "2"))
check("đội hình: tổng bỏ qua giá trị thiếu", (by["team"]["Số pet trong đội"], by["team"]["Tổng HP"], by["team"]["Tổng ATT"], by["team"]["Tổng MR"]), ("2", "150", "10", "3"))
check("battle", (by["battle"]["Kết quả"], by["battle"]["Chuỗi thắng cao nhất"]), ("win", "9"))
check("sự kiện: bộ đếm + pet sự kiện", (by["event"]["Bộ đếm hunt"], by["event"]["Pet sự kiện đã tìm"], by["event"]["Nhật ký sự kiện gần đây"]), ("4/10", "1/2", "2"))
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
