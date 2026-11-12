"""test_tools_api.py — hàm thuần của tools_api.py (không cần discord / motor / mongomock).
Chạy: python test_tools_api.py"""
import sys
import tools_api as t

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# ----- parse_alt_id -----
check("alt: ID Discord thật -> nhận", t.parse_alt_id("1238687916176183409"), (True, "1238687916176183409"))
check("alt: cắt khoảng trắng 2 đầu", t.parse_alt_id("  123456789012345678 \n"), (True, "123456789012345678"))
check("alt: rỗng = xóa acc phụ", t.parse_alt_id(""), (True, ""))
check("alt: toàn khoảng trắng = xóa", t.parse_alt_id("   "), (True, ""))
check("alt: 15 chữ số vẫn nhận", t.parse_alt_id("1" * 15), (True, "1" * 15))
check("alt: 25 chữ số vẫn nhận", t.parse_alt_id("1" * 25), (True, "1" * 25))
check("alt: 14 chữ số -> sai", t.parse_alt_id("1" * 14), (False, ""))
check("alt: 26 chữ số -> sai", t.parse_alt_id("1" * 26), (False, ""))
check("alt: lẫn chữ -> sai", t.parse_alt_id("12345678901234567x"), (False, ""))
check("alt: có dấu cách giữa -> sai", t.parse_alt_id("12345678 9012345678"), (False, ""))
check("alt: số nguyên (không phải chuỗi) -> sai", t.parse_alt_id(123456789012345678), (False, ""))
check("alt: None (thiếu khóa) -> sai", t.parse_alt_id(None), (False, ""))
check("alt: <@mention> -> sai", t.parse_alt_id("<@123456789012345678>"), (False, ""))

# ----- parse_zoodiff_kind -----
check("zoodiff: None = tự chọn", t.parse_zoodiff_kind(None), (True, None))
check("zoodiff: rỗng = tự chọn", t.parse_zoodiff_kind(""), (True, None))
check("zoodiff: d = số đã bắt", t.parse_zoodiff_kind("d"), (True, "all"))
check("zoodiff: ALL (hoa) = số đã bắt", t.parse_zoodiff_kind("ALL"), (True, "all"))
check("zoodiff: ' Now ' = đang giữ", t.parse_zoodiff_kind(" Now "), (True, "current"))
check("zoodiff: current = đang giữ", t.parse_zoodiff_kind("current"), (True, "current"))
check("zoodiff: lạ -> sai", t.parse_zoodiff_kind("linhtinh"), (False, None))

# ----- plain_text -----
check("plain: bỏ **đậm** và `mã`", t.plain_text("**Chấm đội hình** — gõ `owo team`"), "Chấm đội hình — gõ owo team")
check("plain: emoji tùy chỉnh -> tên", t.plain_text("<:bee:123456> <a:slothbot:711772997320441897> x"), "bee slothbot x")
check("plain: emoji Unicode giữ nguyên", t.plain_text("🐝 bee: 5 → 9 (+4)"), "🐝 bee: 5 → 9 (+4)")
check("plain: <@mention> không bị đụng", t.plain_text("<@123> ơi"), "<@123> ơi")
check("plain: None / rỗng -> rỗng", (t.plain_text(None), t.plain_text("")), ("", ""))

# ----- group_unlocked -----
rows = [
    {"tier": "common", "name": "bee"}, {"tier": "common", "name": "cat"},
    {"tier": "rare", "name": "wolf"}, {"tier": "epic", "name": "dragon"},
    {"tier": "epic", "name": ""}, {"tier": "epic"},   # dòng hỏng (thiếu tên) bị bỏ qua
]
g = t.group_unlocked(rows)
check("unlocked: gom theo tier, giữ thứ tự, bỏ dòng thiếu tên",
      g, {"total": 4, "tiers": [
          {"tier": "common", "count": 2, "pets": ["bee", "cat"]},
          {"tier": "rare", "count": 1, "pets": ["wolf"]},
          {"tier": "epic", "count": 1, "pets": ["dragon"]}]})
check("unlocked: lọc 1 tier không phân biệt hoa/thường", t.group_unlocked(rows, "RARE"),
      {"total": 1, "tiers": [{"tier": "rare", "count": 1, "pets": ["wolf"]}]})
check("unlocked: tier rỗng/None = tất cả", (t.group_unlocked(rows, "") == g, t.group_unlocked(rows, None) == g), (True, True))
check("unlocked: tier không có -> None", t.group_unlocked(rows, "fabled"), None)
check("unlocked: chưa có dữ liệu -> 0 con", t.group_unlocked([]), {"total": 0, "tiers": []})
check("unlocked: chưa có dữ liệu + lọc tier -> None", t.group_unlocked([], "rare"), None)

# ----- parse_pet_manual -----
PET = {"name": " gowl ", "rank": "legendary", "hp": 10, "att": 1, "pr": 3, "wp": 1, "mag": 2, "mr": 3}
check("pet: hợp lệ -> cắt tên, rank viết hoa chữ đầu",
      t.parse_pet_manual(PET),
      (True, {"name": "gowl", "rank": "Legendary", "hp": 10, "att": 1, "pr": 3, "wp": 1, "mag": 2, "mr": 3}))
check("pet: chỉ số 0 và tối đa đều nhận",
      t.parse_pet_manual({**PET, "hp": 0, "mr": 100000})[0], True)
check("pet: không phải dict -> body", t.parse_pet_manual(None), (False, "body"))
check("pet: thiếu tên -> name", t.parse_pet_manual({**PET, "name": "  "}), (False, "name"))
check("pet: tên có xuống dòng -> name", t.parse_pet_manual({**PET, "name": "a\nb"}), (False, "name"))
check("pet: tên quá 60 ký tự -> name", t.parse_pet_manual({**PET, "name": "x" * 61}), (False, "name"))
check("pet: rank có số -> rank", t.parse_pet_manual({**PET, "rank": "rare2"}), (False, "rank"))
check("pet: rank thiếu -> rank", t.parse_pet_manual({k: v for k, v in PET.items() if k != "rank"}), (False, "rank"))
check("pet: chỉ số âm -> đúng trường", t.parse_pet_manual({**PET, "att": -1}), (False, "att"))
check("pet: chỉ số quá lớn -> đúng trường", t.parse_pet_manual({**PET, "pr": 100001}), (False, "pr"))
check("pet: chỉ số dạng chuỗi -> đúng trường", t.parse_pet_manual({**PET, "wp": "5"}), (False, "wp"))
check("pet: chỉ số số thực -> đúng trường", t.parse_pet_manual({**PET, "mag": 1.5}), (False, "mag"))
check("pet: chỉ số bool -> đúng trường", t.parse_pet_manual({**PET, "mr": True}), (False, "mr"))
check("pet: thiếu chỉ số -> đúng trường", t.parse_pet_manual({k: v for k, v in PET.items() if k != "hp"}), (False, "hp"))

# ----- parse_desc_manual -----
check("desc: hợp lệ có khoảng trắng trong tên", t.parse_desc_manual({"name": " poison dagger ", "desc": " Gây Poison \n xuyên giáp "}),
      (True, {"name": "poison dagger", "desc": "Gây Poison \n xuyên giáp"}))
check("desc: không phải dict -> body", t.parse_desc_manual([]), (False, "body"))
check("desc: thiếu tên -> name", t.parse_desc_manual({"desc": "x"}), (False, "name"))
check("desc: mô tả rỗng -> desc", t.parse_desc_manual({"name": "a", "desc": "   "}), (False, "desc"))
check("desc: mô tả quá 1000 ký tự -> desc", t.parse_desc_manual({"name": "a", "desc": "x" * 1001}), (False, "desc"))
check("desc: đúng 1000 ký tự vẫn nhận", t.parse_desc_manual({"name": "a", "desc": "x" * 1000})[0], True)
check("desc: ký tự điều khiển -> desc", t.parse_desc_manual({"name": "a", "desc": "x\x00y"}), (False, "desc"))
check("desc: mô tả không phải chuỗi -> desc", t.parse_desc_manual({"name": "a", "desc": 5}), (False, "desc"))

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test tools_api pass.")
