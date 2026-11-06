"""test_weapon_auto.py — doc NeonUtil + tu quyet Giu/Rac. Chay: python3 -W ignore test_weapon_auto.py (khong can Mongo)."""
import sys, json, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import weapon_auto as wa

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong doi:", want); print("   thuc te :", got); fails.append(label)

rules = json.load(open(os.path.join(HERE, "weapon_rules.json"), encoding="utf-8"))
def W(id, type, passives, quality=45.0, rarity="rare"):
    return {"id": id, "type": type, "passives": passives, "quality": quality, "rarity": rarity,
            "name": type, "starred": False, "equipped": False}

# --- bac
check("tier mythical == mythic", wa.tier_from_text("mythical"), "mythic")
check("tier uncommon khong bi nhan thanh common", wa.tier_from_text("uncommon"), "uncommon")
check("tier la -> None", wa.tier_from_text("xyz"), None)

# --- breakdown
BD = ("## Ruby's Bow ( ABCD1 )\n"
      "<:att:1> **120** (Range: 100-150 — <:mythic:2> 80%)\n"
      "<:wp:3> **30** (Range: 20-40 — <:rare:4> 50%)\n"
      "<:know:5> **9.2%** (Range: 5-15 — <:epic:6> 42%)\n")
b = wa.parse_neon_breakdown(BD)
check("breakdown: 3 dong", len(b["stats"]), 3)
check("breakdown: id", b["id"], "ABCD1")
check("breakdown: bac dong 1", (b["stats"][0]["value"], b["stats"][0]["lo"], b["stats"][0]["hi"], b["stats"][0]["tier"], b["stats"][0]["pct"]), (120.0, 100.0, 150.0, "mythic", 80.0))
check("breakdown rong -> None", wa.parse_neon_breakdown("khong co gi"), None)
check("compact: 2 chi so vu khi", wa.parse_neon_compact("<:rare:1> 45% max | `Worn Bow 80,50 know 42`"), {"n_weapon": 2})
check("compact: khong doc duoc -> None", wa.parse_neon_compact("hello"), None)

# --- knowledge
check("knowledge 9.2%", wa.knowledge_value({"name": "Knowledge", "desc": "Gain +**9.2%** more XP"}), 9.2)
check("knowledge 15.5% lon hon 14", wa.knowledge_value({"name": "Knowledge", "desc": "+**15.5%** xp"}), 15.5)
check("passive khac -> None", wa.knowledge_value({"name": "Thorns", "desc": "+**9%**"}), None)

# --- quyet dinh
rac = W("R1", "pstaff", ["swarm"])
check("rac + khong co du lieu neon -> giu", wa.auto_decide(rac, None, None, None, rules), ("keep", "thieu_du_lieu_neon"))
low = {"stats": [{"tier": "common"}, {"tier": "uncommon"}, {"tier": "epic"}]}
check("rac + chi so vu khi thap -> bo", wa.auto_decide(rac, None, low, 2, rules)[0], "drop")
hi = {"stats": [{"tier": "common"}, {"tier": "mythic"}, {"tier": "common"}]}
check("rac + 1 chi so vu khi Mythic -> giu", wa.auto_decide(rac, None, hi, 2, rules), ("keep", "chi_so_vu_khi_mythic"))
passive_hi = {"stats": [{"tier": "common"}, {"tier": "common"}, {"tier": "fabled"}]}
check("Fabled o passive (khong phai chi so vu khi) khong ep giu", wa.auto_decide(rac, None, passive_hi, 2, rules)[0], "drop")
unk = {"stats": [{"tier": None}, {"tier": "common"}]}
check("bac la -> giu", wa.auto_decide(rac, None, unk, 2, rules), ("keep", "bac_chi_so_la"))
check("lech so luong -> giu", wa.auto_decide(rac, None, {"stats": [{"tier": "common"}]}, 2, rules)[0], "keep")
know = {"passive": {"name": "Knowledge", "desc": "+**15%** xp"}}
check("Knowledge > 14 -> giu bat ke", wa.auto_decide(rac, know, None, None, rules)[0], "keep")
check("Knowledge 14 khong qua nguong -> theo luat thuong", wa.auto_decide(rac, {"passive": {"name": "Knowledge", "desc": "+**14%**"}}, low, 2, rules)[0], "drop")
check("cay tot theo luat cu -> giu, khong can neon", wa.needs_neon_check(W("G1", "vban", ["att"], 79.6, "epic"), None, rules), False)
check("cay rac theo luat cu -> can neon", wa.needs_neon_check(rac, None, rules), True)
check("cay Knowledge cao khong can neon", wa.needs_neon_check(rac, know, rules), False)
check("cay sao -> giu", wa.auto_decide({**rac, "starred": True}, None, low, 2, rules)[0], "keep")

print("\nLOI:", fails if fails else "khong")
sys.exit(1 if fails else 0)
