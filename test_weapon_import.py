"""test_weapon_import.py — nhap file `,w inv export` cua NeonUtil -> Giu/Bo. Chay: python3 -W ignore test_weapon_import.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weapon_import as wi

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong doi:", want); print("   thuc te :", got); fails.append(label)

def W(**k):
    base = {"t": 8, "q": 50.0, "p": [{"t": 3, "r": 2}], "id": "AAAAA1"}
    base.update(k); return base

# --- doc chuoi bp: Poison Dagger (t=8) = 2 chi so chinh + chi phi WP (so cuoi)
check("bp dagger: bo chi phi WP", wi.main_stat_qualities(W(bp="dagger 98,31,65 kkaze 83")), [98, 31])
check("bp co tien to do mon (fine)", wi.main_stat_qualities(W(bp="fine dagger 88,76,90 absolve 37")), [88, 76])
check("bp Bow (t=3) 1 chi so + WP", wi.main_stat_qualities(W(t=3, bp="bow 94,51 snail 81")), [94])
check("bp Orb (t=6) khong co chi so", wi.main_stat_qualities(W(t=6, bp="orb sac 98,56 gslay")), [])
check("khong co bp -> None", wi.main_stat_qualities(W()), None)
check("bp sai so luong chi so -> None", wi.main_stat_qualities(W(bp="dagger 98,31 att 5")), None)
check("bp loai la (t khong co trong bang) -> None", wi.main_stat_qualities(W(t=99, bp="x 1,2 att 5")), None)

# --- luat quyet dinh
check("khoa -> giu", wi.decide(W(l=True, q=5, bp="dagger 1,1,1 att 1")), ("keep", "khoa"))
check("passive hang 5 -> giu", wi.decide(W(p=[{"t": 21, "r": 5}], bp="dagger 1,1,1 knowledge 95")), ("keep", "passive_cao"))
check("co chi so chinh >= 80 -> giu", wi.decide(W(bp="dagger 80,10,10 att 20")), ("keep", "chi_so_cao"))
check("chi so chinh 79 -> bo (chi phi WP cao khong tinh)", wi.decide(W(bp="dagger 79,10,100 att 20")), ("drop", "chi_so_thap"))
check("chi phi WP 100 khong cuu cay yeu", wi.decide(W(bp="dagger 10,10,100 att 20")), ("drop", "chi_so_thap"))
check("khong bp, q 75 -> giu", wi.decide(W(q=75.0)), ("keep", "q_cao"))
check("khong bp, q 74.9 -> bo", wi.decide(W(q=74.9)), ("drop", "q_thap"))
check("bp la -> giu (thieu du lieu khong bao gio bo)", wi.decide(W(bp="dagger abc")), ("keep", "bp_la"))
check("bp la voi cay yeu van giu", wi.decide(W(q=5, bp="dagger 98,31")), ("keep", "bp_la"))

# --- bao ve them
check("Rune of Luck (t=22) khong bao gio Bo", wi.decide(W(t=22, q=1, bp="x 1,1,1,1,1,1,1")), ("keep", "loai_dac_biet"))
check("Rune of Celebration (t=18) khong bao gio Bo", wi.decide(W(t=18, q=1)), ("keep", "loai_dac_biet"))
check("cay da co kill (k=true) -> giu", wi.decide(W(k=True, q=1)), ("keep", "co_kill"))
check("k=false (chi co TT) van xet theo luat", wi.decide(W(k=False, q=1)), ("drop", "q_thap"))

# --- tao dong lenh de Ruby tu dan
ids = [f"ID{n:03d}" for n in range(1, 38)]
l1, tot, pages = wi.dismantle_commands(ids)
check("1 ID/lenh: 37 lenh, 3 trang, trang 1 co 15 dong", (len(l1), tot, pages), (15, 37, 3))
check("dong lenh dung cu phap", l1[0], "owo dismantle ID001")
l3, _, _ = wi.dismantle_commands(ids, page=3)
check("trang cuoi con du 7 dong", (len(l3), l3[-1]), (7, "owo dismantle ID037"))
l5, tot5, _ = wi.dismantle_commands(ids, per_cmd=5)
check("5 ID/lenh", (tot5, l5[0]), (8, "owo dismantle ID001 ID002 ID003 ID004 ID005"))
check("per_cmd bi chan o 10", wi.dismantle_commands(ids, per_cmd=99)[0][0].count("ID"), 10)
check("trang ngoai pham vi -> ve trang cuoi", wi.dismantle_commands(ids, page=99)[0][-1], "owo dismantle ID037")
check("khong lap / sap xep co dinh", wi.dismantle_commands(["B", "A"])[0], ["owo dismantle A", "owo dismantle B"])

# --- danh sach cay can danh sao
sl, st, sp = wi.star_lines(["B", "A", "C"])
check("starlist chi liet ke ID, sap xep", (sl, st, sp), (["A", "B", "C"], 3, 1))
check("starlist them tien to lenh", wi.star_lines(["A"], "  owo star ")[0], ["owo star A"])
big = [f"I{n:03d}" for n in range(45)]
check("starlist chia trang 20", (len(wi.star_lines(big, page=3)[0]), wi.star_lines(big)[2]), (5, 3))

# --- ke hoach + tom tat
plan = wi.build_plan([W(id="A", l=True), W(id="B", q=80.0), W(id="C", q=10.0), W(id="D", bp="dagger 1,1,1 att 1")])
check("ke hoach dem dung", (sorted(plan["keep"]), sorted(plan["drop"]), plan["total"]), (["A", "B"], ["C", "D"], 4))
check("ly do dem dung", plan["reasons"], {"khoa": 1, "q_cao": 1, "q_thap": 1, "chi_so_thap": 1})
txt = wi.summary_text(plan)
check("tom tat noi ro chua xoa gi", ("CHƯA xóa" in txt and "Giữ **2**" in txt and "Bỏ **2**" in txt), True)

# --- doc file
check("parse bo bom UTF-8", len(wi.parse_export("﻿" + json.dumps([W()]))), 1)
for label, bad in (("JSON hong", "{"), ("rong", "[]"), ("khong dung dinh dang", '[{"x":1}]'), ("khong phai danh sach", '{"a":1}')):
    try:
        wi.parse_export(bad); check(f"parse loi: {label}", "khong loi", "ValueError")
    except ValueError:
        check(f"parse loi: {label}", "ValueError", "ValueError")
check("parse bo cay thieu truong", len(wi.parse_export(json.dumps([W(), {"id": "Z"}, W(id="B")]))), 2)

print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
