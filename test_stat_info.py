"""test_stat_info.py — 6 chỉ số + embed ,stats. Chạy: python test_stat_info.py"""
import sys
import stat_info as si

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

check("đúng 6 chỉ số, khóa DB không đổi", si.STAT_KEYS, ("hp", "att", "pr", "wp", "mag", "mr"))
check("mỗi chỉ số có nhãn, nghĩa, ghi chú", all(len(s) == 4 and all(s) for s in si.STATS), True)
rows = [{"hp": 100, "att": 10, "pr": 5, "wp": 20, "mag": 7, "mr": 3}, {"hp": 50, "att": None, "pr": "x", "wp": 1}, {}, None]
tot, n = si.team_totals(rows)
check("tổng đội hình bỏ qua giá trị thiếu/lạ", (tot, n), ({"hp": 150, "att": 10, "pr": 5, "wp": 21, "mag": 7, "mr": 3}, 2))
check("bool không bị tính là số", si.team_totals([{"hp": True}]), ({k: 0 for k in si.STAT_KEYS}, 0))
f = si.embed_fields(rows)
check("embed: 6 chỉ số + tổng đội + hướng dẫn = 8 mục", len(f), 8)
check("tên mục 1", f[0][0], "HP — Máu")
check("dòng tổng đội", f[6], ("Tổng đội hình hiện tại (2 pet)", "HP **150** · ATT **10** · PR **5** · WP **21** · MAG **7** · MR **3**", False))
check("chưa có đội hình: báo rõ", si.embed_fields([])[6][0], "Tổng đội hình hiện tại")
check("giới hạn Discord: tên ≤256, nội dung ≤1024, ≤25 mục", all(len(a) <= 256 and len(b) <= 1024 for a, b, _ in f) and len(f) <= 25, True)
print("\nTất cả pass" if not fails else f"\n{len(fails)} lỗi: {fails}")
sys.exit(1 if fails else 0)
