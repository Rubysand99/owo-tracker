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
check("bp dagger: tat ca chi so KE CA chi phi WP", wi.all_stat_qualities(W(bp="dagger 98,31,65 kkaze 83")), [98, 31, 65])
check("bp Orb (t=6): khong co chi so -> []", wi.all_stat_qualities(W(t=6, bp="orb sac 98,56 gslay")), [])
check("khong co bp -> None (all_stat_qualities)", wi.all_stat_qualities(W()), None)
check("TAT CA chi so (gom WP) >= 80 -> giu", wi.decide(W(bp="dagger 90,85,80 att 20")), ("keep", "chi_so_cao"))
check("moi chi so deu 100 -> giu", wi.decide(W(bp="dagger 100,100,100")), ("keep", "chi_so_cao"))
check("loai chi co 1 chi so -> khong tu Bo", wi.decide(W(t=4, bp="rune 90")), ("keep", "bp_la"))
check("luat moi: 2 chi so >= 80 la du giu (chi phi WP 79 khong keo xuong)", wi.decide(W(bp="dagger 90,90,79 att 20")), ("keep", "chi_so_cao"))
check("chi phi WP la 1 chi so: 90,10,85 -> giu", wi.decide(W(bp="dagger 90,10,85 att 20")), ("keep", "chi_so_cao"))
check("dung 80 tinh dat: 80,80,10 -> giu", wi.decide(W(bp="dagger 80,80,10")), ("keep", "chi_so_cao"))
check("79,80,10 chi 1 chi so dat -> bo (da doc du chi so)", wi.decide(W(bp="dagger 79,80,10")), ("drop", "chi_so_thap"))
check("chi 1 chi so cao (80,10,10) khong con du de giu -> bo", wi.decide(W(bp="dagger 80,10,10 att 20")), ("drop", "chi_so_thap"))
check("chi so chinh cao nhung WP 100 khong cuu cay yeu", wi.decide(W(bp="dagger 10,10,100 att 20")), ("drop", "chi_so_thap"))
check("Bow (t=3): 2 chi so 94,81 -> giu", wi.decide(W(t=3, bp="bow 94,81 snail 81")), ("keep", "chi_so_cao"))
check("Orb khong co chi so de xet -> bo (chi giu qua Knowledge top)", wi.decide(W(t=6, bp="orb sac 98,56 gslay")), ("drop", "chi_so_thap"))
check("passive hang 5 KHONG con cuu cay co bp yeu", wi.decide(W(p=[{"t": 21, "r": 5}], bp="dagger 1,1,1 att 95")), ("drop", "chi_so_thap"))
check("chua co bp + passive hang 5 -> giu (chua biet co phai Knowledge cao)", wi.decide(W(q=10.0, p=[{"t": 21, "r": 5}])), ("keep", "chua_xem_passive_cao"))
check("chua co bp + q thap -> KHONG bo (chua chac), de Chua ro", wi.decide(W(q=10.0, p=[{"t": 21, "r": 4}])), ("keep", "q_thap_chua_chac"))

# --- Knowledge: doc tu bp, giu TOP 6
check("kno 95", wi.knowledge_quality(W(bp="dagger 1,1,1 kno 95")), 95)
check("bp co tien to do mon + passive khac truoc kno", wi.knowledge_quality(W(bp="fine dagger 1,1,1 att 5 kno 88")), 88)
check("ten day du knowledge", wi.knowledge_quality(W(bp="dagger 1,1,1 knowledge 77")), 77)
check("kno thieu so = 100", wi.knowledge_quality(W(bp="dagger 1,1,1 kno")), 100)
check("cay khong co Knowledge -> None", wi.knowledge_quality(W(bp="dagger 98,31,65 kkaze 83")), None)
check("khong co bp -> None (knowledge)", wi.knowledge_quality(W()), None)
check("Orb + passive kno doc duoc", wi.knowledge_quality(W(t=6, bp="orb kno 90")), 90)

def K(i, v, q=50.0, **kw):
    return W(id=i, q=q, bp=f"dagger 1,1,1 kno {v}", **kw)
ws8 = [K("A", 50), K("B", 99), K("C", 70), K("D", 85), K("E", 60), K("F", 92), K("G", 40), K("H", 75), W(id="Z", bp="dagger 1,1,1 att 5")]
top = wi.knowledge_top(ws8)
check("top 6 giam dan, dung 6 cay", [(e["id"], e["v"]) for e in top], [("B", 99), ("F", 92), ("D", 85), ("H", 75), ("C", 70), ("E", 60)])
check("hoa Knowledge: cay q cao hon xep truoc", [e["id"] for e in wi.knowledge_top([K("X1", 80, 40.0), K("X2", 80, 60.0)])], ["X2", "X1"])
# cay moi cao hon thi thay vao, cay thap nhat bi day ra
top2 = wi.knowledge_top(ws8 + [K("N", 97)], top)
check("cay Knowledge cao hon thay vao, cay thap nhat (E) bi day ra", [e["id"] for e in top2], ["B", "N", "F", "D", "H", "C"])
# danh sach da luu: cay con trong kho nhung export moi khong con bp -> giu gia tri da luu; cay da het trong kho -> bo
now = [W(id="B"), W(id="F"), K("D", 85)]
top3 = wi.knowledge_top(now, [{"id": "B", "v": 99}, {"id": "F", "v": 92}, {"id": "GONE", "v": 100}, {"bad": 1}, {"id": "D", "v": 10}])
check("luu lai: giu gia tri cu neu khong con bp, bo cay khong con, file moi ghi de", [(e["id"], e["v"]) for e in top3], [("B", 99), ("F", 92), ("D", 85)])
check("danh sach luu hong -> bo qua, khong loi", wi.knowledge_top([K("A", 5)], "oops"), [{"id": "A", "v": 5}])
# decide voi top Knowledge
check("cay trong top Knowledge -> giu du chi so thap", wi.decide(K("B", 99), {"B"}), ("keep", "knowledge_top"))
check("cay co Knowledge nhung khong vao top, chi so thap -> bo", wi.decide(K("G", 40), {"B"}), ("drop", "chi_so_thap"))
check("cay Knowledge vao top van sau khoa/kill (thu tu uu tien)", wi.decide(K("B", 99, l=True), {"B"}), ("keep", "khoa"))
check("cay Knowledge ngoai top nhung chi so deu >= 80 -> van giu theo chi so", wi.decide(W(id="G", bp="dagger 90,90,90 kno 40"), {"B"}), ("keep", "chi_so_cao"))
check("khong bp, q 75 -> giu", wi.decide(W(q=75.0)), ("keep", "q_cao"))
check("khong bp, q 74.9 -> khong bo, de Chua ro", wi.decide(W(q=74.9)), ("keep", "q_thap_chua_chac"))
check("bp la -> giu (thieu du lieu khong bao gio bo)", wi.decide(W(bp="dagger abc")), ("keep", "bp_la"))
check("bp la voi cay yeu van giu", wi.decide(W(q=5, bp="dagger 98,31")), ("keep", "bp_la"))

# --- bao ve them
check("Rune of Luck (t=22) khong bao gio Bo", wi.decide(W(t=22, q=1, bp="x 1,1,1,1,1,1,1")), ("keep", "loai_dac_biet"))
check("Rune of Celebration (t=18) khong bao gio Bo", wi.decide(W(t=18, q=1)), ("keep", "loai_dac_biet"))
check("cay da co kill (k=true) -> giu", wi.decide(W(k=True, q=1)), ("keep", "co_kill"))
check("k=false (chi co TT) van xet theo luat", wi.decide(W(k=False, q=1)), ("keep", "q_thap_chua_chac"))

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

# --- don kho cach lai
def D(i, dec, q, why="x"): return {"_id": i, "decision": dec, "reason": why, "q": q}
st = wi.cleanup_stages([
    D("K_khoa", "keep", 30, "khoa"),          # da khoa -> khong can sao
    D("K_thap", "keep", 50),                  # giu, q thap -> phai sao
    D("K_cao", "keep", 85),                   # giu, q cao -> khong sao
    D("B_low", "drop", 20), D("B_rare", "drop", 40.0), D("B_rare2", "drop", 60.6),
    D("B_epic", "drop", 61.2), D("B_cao", "drop", 75),
    D("U", "drop", 60.9),                     # vung chua ro bac
])
check("sao: chi cay GIU chua khoa q thap", st["star_ids"], ["K_thap"])
check("bo common+uncommon (q < 40)", st["low_drop"], ["B_low"])
check("bo Rare (40 <= q < 61)", st["rare_drop"], ["B_rare", "B_rare2", "U"])
check("bo ra theo ID (q >= 61)", st["id_drop"], ["B_cao", "B_epic"])
check("canh bao vung chua ro bac", st["unsure"], ["U"])
check("thieu q -> yeu cau nhap lai", wi.cleanup_stages([{"_id": "A", "decision": "drop"}])["missing_q"], 1)
txt = wi.cleanup_text(st)
check("ke hoach co so cay de doi chieu", ("Đánh sao 1 cây" in txt and "đúng **1** cây" in txt and "đúng **3** cây" in txt and "Rã theo ID 2 cây" in txt), True)
check("ke hoach canh bao vung chua ro", "`U`" in txt, True)
check("thieu q -> chi thong bao nhap lai", "weaponimport" in wi.cleanup_text(wi.cleanup_stages([{"_id": "A", "decision": "drop"}])), True)

# --- ke hoach + tom tat
plan = wi.build_plan([W(id="A", l=True), W(id="B", q=80.0), W(id="C", q=10.0), W(id="D", bp="dagger 1,1,1 att 1")])
check("ke hoach dem dung", (sorted(plan["keep"]), sorted(plan["drop"]), plan["total"]), (["A", "B", "C"], ["D"], 4))
check("ly do dem dung", plan["reasons"], {"khoa": 1, "q_cao": 1, "q_thap_chua_chac": 1, "chi_so_thap": 1})
txt = wi.summary_text(plan)
check("tom tat noi ro chua xoa gi", ("CHƯA xóa" in txt and "Giữ **3**" in txt and "Bỏ **1**" in txt), True)
check("ke hoach khong co Knowledge -> top rong, tom tat khong in dong Top", (plan["knowledge_top"], "Top 6 Knowledge" in txt), ([], False))

# --- ke hoach co Knowledge top 6
plan2 = wi.build_plan(ws8 + [W(id="Y", bp="dagger 90,90,90 att 20"), W(id="L", l=True)])
check("ke hoach: 6 cay Knowledge top duoc giu", sorted(i for i, why in plan2["keep"].items() if why == "knowledge_top"), ["B", "C", "D", "E", "F", "H"])
check("ke hoach: cay Knowledge ngoai top (A, G) bi bo", sorted(i for i, why in plan2["drop"].items() if why == "chi_so_thap" and i in ("A", "G")), ["A", "G"])
check("ke hoach: ly do dem dung", plan2["reasons"], {"knowledge_top": 6, "chi_so_thap": 3, "chi_so_cao": 1, "khoa": 1})
check("ke hoach: luu lai top de lan nhap sau", [e["id"] for e in plan2["knowledge_top"]], ["B", "F", "D", "H", "C", "E"])
txt2 = wi.summary_text(plan2)
check("tom tat in top Knowledge", ("Top 6 Knowledge" in txt2 and "`B` 99" in txt2), True)
plan3 = wi.build_plan([K("B", 99), K("NEW", 100)], plan2["knowledge_top"])
check("lan nhap sau: cay B con kho nen van nam trong top, cay moi cao hon len dau", [e["id"] for e in plan3["knowledge_top"]], ["NEW", "B"])

# --- doc file
check("parse bo bom UTF-8", len(wi.parse_export("﻿" + json.dumps([W()]))), 1)
for label, bad in (("JSON hong", "{"), ("rong", "[]"), ("khong dung dinh dang", '[{"x":1}]'), ("khong phai danh sach", '{"a":1}')):
    try:
        wi.parse_export(bad); check(f"parse loi: {label}", "khong loi", "ValueError")
    except ValueError:
        check(f"parse loi: {label}", "ValueError", "ValueError")
check("parse bo cay thieu truong", len(wi.parse_export(json.dumps([W(), {"id": "Z"}, W(id="B")]))), 2)

def test_cleanup_steps_order_and_gates():
    import weapon_import as wi
    st = {"star_ids": ["A1", "B2"], "low_drop": ["L1", "L2", "L3"], "rare_drop": ["R1", "R2"], "id_drop": ["X9"],
          "unsure": [], "missing_q": 0}
    steps = wi.cleanup_steps(st)
    assert [s["action"] for s in steps] == ["clean_star", "clean_star", "clean_tier", "clean_tier", "clean_tier", "clean_id"]
    assert steps[0]["params"]["command_text"] == "owo w A1"
    assert steps[2]["params"]["expect_max"] == "3" and steps[2]["params"]["command_text"] == "owo dismantle common"
    assert steps[4]["params"]["expect"] == "2" and steps[4]["params"]["command_text"] == "owo dismantle rare"
    assert steps[5]["params"]["expect_id"] == "X9"
    ex = wi.cleanup_steps(st, with_export=True)
    assert ex[-1]["action"] == "clean_export" and ex[-1]["params"]["command_text"] == "nw inv export" and len(ex) == len(steps) + 1
    assert wi.cleanup_steps(dict(st, star_ids=[], low_drop=[], rare_drop=[], id_drop=[]), with_export=True) == []
    assert wi.cleanup_steps(dict(st, unsure=["Z"])) == []
    assert wi.cleanup_steps(dict(st, missing_q=1)) == []
test_cleanup_steps_order_and_gates()
print("✅ cleanup_steps")

def test_extra_drop_and_parse_ids():
    import weapon_import as wi
    docs = [D("U1", "keep", 60.9), D("U2", "drop", 61.0), D("K1", "keep", 50.0), D("LK", "keep", 90.0, "khoa"), D("L1", "drop", 10.0)]
    base = wi.cleanup_stages(docs)
    assert base["unsure"] == ["U1", "U2"] and base["star_ids"] == ["K1", "U1"] and wi.cleanup_steps(base) == []
    st = wi.cleanup_stages(docs, ["u1", "K1", "LK", "u2"])   # chu thuong van khop; cay KHOA khong bi dong vao
    assert st["unsure"] == [] and st["id_drop"] == ["K1", "U1", "U2"] and st["star_ids"] == [] and st["low_drop"] == ["L1"]
    ids = [x["params"]["expect_id"] for x in wi.cleanup_steps(st) if x["action"] == "clean_id"]
    assert ids == ["K1", "U1", "U2"]
    assert wi.cleanup_stages(docs, ()) == base
    assert wi.parse_weapon_ids("c06p72, F40IBT\nc06p72 !!bad ab") == (["C06P72", "F40IBT"], ["!!bad", "ab"])
    assert wi.parse_weapon_ids("") == ([], [])
test_extra_drop_and_parse_ids()
print("✅ extra_drop")

def test_unknown_is_starred():
    docs = [{"_id": "U1", "decision": "unknown", "reason": "bp_la", "q": 30.0},
            {"_id": "U2", "decision": "unknown", "reason": "khoa", "q": 30.0}]
    st = wi.cleanup_stages(docs, ())
    assert st["star_ids"] == ["U1"] and st["low_drop"] == []
test_unknown_is_starred()
print("✅ unknown được sao như Giữ")

import json as _j
_r = _j.load(open("weapon_rules.json", encoding="utf-8"))
check("neon_bp: dong gon Neon (word-joiner tu man hinh)", wi.neon_bp("mythic 89.8% max\uff5cmsstaff \u200b\u2060sstaff 100,91,68 knowledge 98\u2060\u200b", _r), {"t": 12, "bp": "sstaff 100,91,68 knowledge 98"})
check("neon_bp: khong co bp -> None", wi.neon_bp("hello world", _r), None)
print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
