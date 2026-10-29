"""Loc vu khi de dismantle: chia moi cay thanh GIU / RAC / XAM.

CHI LAP KE HOACH - khong xoa gi ca. Ham thuan (khong dung discord, khong dung DB) de test duoc o bat ky dau.
Nguyen tac: khong chac thi XAM (= giu, cho Ruby quyet). Chi cay NAO chac chan khong hop moi bi xep RAC.

Dau vao: danh sach cay (moi muc nhu bang owot_weapon_list):
    {id, rarity, type, passives, name, quality, starred, equipped, equipped_by}
va bo luat weapon_rules.json (loi khuyen ?tag cua server + y rieng cua Ruby).
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone

# Do hiem (ten emoji o dau moi dong danh sach). Tu "mythic" tro len khong bao gio tu xep RAC.
HIGH_RARITIES = ("mythic", "legendary", "fabled")
KNOWN_RARITIES = ("common", "uncommon", "rare", "epic") + HIGH_RARITIES

KEEP_TOP_PER_TYPE = 2          # giu N cay chat luong cao nhat moi loai (du phong)

GOOD_VERDICTS = ("ok", "ruby", "ruby_wp", "cond_ok")

# Giong _KNOWN_PASSIVES trong bot (phong khi bo luat chua liet ke het)
_FALLBACK_KNOWN = {"hgen", "kaze", "thorns", "sprout", "farmor", "sacrifice", "wgen", "mtap", "crit", "mag",
                   "gslayer", "sguard", "lifesteal", "str", "discharge", "snail", "pr", "swarm", "dstrike",
                   "absolute", "enrage", "lhive"}

VERDICT_TEXT = {
    "ok": "server khuyên",
    "ruby": "bạn chọn",
    "ruby_wp": "passive hồi WP",
    "cond_ok": "có điều kiện (đủ)",
    "cond": "chỉ hợp có điều kiện",
    "unlisted": "server chưa có lời khuyên",
    "unknown": "chưa biết passive này",
    "no": "không nằm trong khuyên",
}


def _server_any(rules):
    """Moi passive ma server tung khuyen cho BAT KY loai nao (ke ca co dieu kien)."""
    out = set()
    for t in rules.get("types", {}).values():
        out |= set(t.get("recommended", []))
        for r in t.get("roles", []):
            out |= set(r.get("passives", []))
        for c in t.get("conditional", []):
            out |= set(c.get("passives", []))
    return out


def passive_verdict(pbase, rule, rules, server_any=None):
    """Cham 1 passive tren 1 loai vu khi. Tra ve (verdict, khoa_loi_khuyen).
    Cung luat voi evaluate_team_member (,teamcheck) de 2 noi khong lech nhau."""
    alias = rules.get("passive_alias", {})
    ruby = rules.get("ruby", {})
    pkey = alias.get(pbase, pbase)
    rec = set(rule.get("recommended", []))
    for r in rule.get("roles", []):
        rec |= set(r.get("passives", []))
    conds = {}
    for c in rule.get("conditional", []):
        for ps in c.get("passives", []):
            conds[ps] = c.get("dieu_kien", "")
    ruby_picks = set(rule.get("ruby_them", []))
    if pkey == "sacrifice" and rule.get("key") in set(ruby.get("sacrifice_hop_voi", [])):
        ruby_picks.add("sacrifice")
    hoi_wp = set(ruby.get("passive_hoi_wp", []))
    known = set(rules.get("known_passives", [])) | set(rules.get("passives", {}).keys()) | _FALLBACK_KNOWN
    if server_any is None:
        server_any = _server_any(rules)
    if pkey in rec:
        return "ok", pkey
    if pkey in ruby_picks:
        return "ruby", pkey
    if pkey in hoi_wp:
        return "ruby_wp", pkey
    if pkey in conds:
        return "cond", pkey          # khong biet doi hinh -> khong coi la du dieu kien (than trong)
    if pkey not in known and pbase not in known:
        return "unknown", pkey
    if pkey not in server_any:
        return "unlisted", pkey
    return "no", pkey


def _passive_name(pbase, rules):
    info = rules.get("passives", {}).get(pbase) or {}
    return info.get("ten") or pbase


def classify_weapon(w, rules, top_ids=frozenset(), server_any=None):
    """Tra ve (bucket, ly_do[list ma], chi_tiet_passive[list]). bucket: 'giu' | 'rac' | 'xam'."""
    types = rules.get("types", {})
    e2c = rules.get("emoji_to_code", {})
    never = set(rules.get("never_dismantle", []))
    code = e2c.get(w.get("type"))
    rule = types.get(code) if code else None

    # --- 1) giu cung: yeu thich, dang trang bi, loai khong bao gio xoa (Rune)
    hard = []
    if w.get("starred"):
        hard.append("yeu_thich")
    if w.get("equipped"):
        hard.append("dang_trang_bi")
    if code in never:
        hard.append("loai_khong_xoa")
    # --- 2) cham tung passive
    details = []
    if rule:
        for pb in w.get("passives") or []:
            v, pkey = passive_verdict(pb, rule, rules, server_any)
            details.append({"passive": pb, "ten": _passive_name(pb, rules), "khoa": pkey, "danh_gia": v})
    if hard:
        return "giu", hard, details
    if any(d["danh_gia"] in GOOD_VERDICTS for d in details):
        return "giu", ["passive_tot"], details
    # --- 3) du phong: top chat luong moi loai
    if w.get("id") in top_ids:
        return "giu", ["top_chat_luong"], details
    # --- 4) khong du du lieu / khong chac -> XAM
    xam = []
    if rule is None:
        xam.append("loai_chua_co_loi_khuyen")
    elif rule.get("tbd"):
        xam.append("loai_loi_khuyen_chua_day_du")
    if w.get("quality") is None:
        xam.append("thieu_chat_luong")
    for d in details:
        if d["danh_gia"] == "cond":
            xam.append("passive_co_dieu_kien")
        elif d["danh_gia"] == "unlisted":
            xam.append("passive_server_chua_khuyen")
        elif d["danh_gia"] == "unknown":
            xam.append("passive_la")
    rar = w.get("rarity")
    if rar in HIGH_RARITIES:
        xam.append("do_hiem_cao")
    elif rar not in KNOWN_RARITIES:
        xam.append("do_hiem_la")
    if xam:
        return "xam", sorted(set(xam)), details
    # --- 5) chac chan khong hop
    if not details:
        return "rac", ["khong_co_passive"], details
    return "rac", ["passive_khong_hop"], details


def _top_ids_per_type(weapons, k):
    by_type = defaultdict(list)
    for w in weapons:
        by_type[w.get("type")].append(w)
    top = set()
    for lst in by_type.values():
        lst.sort(key=lambda x: (-(x.get("quality") or -1), str(x.get("id"))))
        top |= {x["id"] for x in lst[:k]}
    return top


def _row(w, reasons, details):
    return {"id": w.get("id"), "type": w.get("type"), "name": w.get("name"), "rarity": w.get("rarity"),
            "quality": w.get("quality"), "passives": w.get("passives") or [], "ly_do": reasons,
            "passive_danh_gia": [f"{d['ten']}: {VERDICT_TEXT.get(d['danh_gia'], d['danh_gia'])}" for d in details]}


def plan_cleanup(weapons, rules, keep_top=KEEP_TOP_PER_TYPE):
    """Lap ke hoach. KHONG xoa gi. Tra ve dict co 3 danh sach (giu / rac / xam) + thong ke."""
    weapons = [w for w in weapons if w.get("id")]
    server_any = _server_any(rules)
    top_ids = _top_ids_per_type(weapons, keep_top)
    out = {"giu": [], "rac": [], "xam": []}
    xam_passive = Counter()
    for w in weapons:
        bucket, reasons, details = classify_weapon(w, rules, top_ids, server_any)
        out[bucket].append(_row(w, reasons, details))
        if bucket == "xam":
            for d in details:
                if d["danh_gia"] in ("unlisted", "unknown", "cond"):
                    xam_passive[f"{d['ten']} ({VERDICT_TEXT[d['danh_gia']]})"] += 1
    for k in ("giu", "xam"):
        out[k].sort(key=lambda r: (str(r["type"]), -(r["quality"] or 0)))
    out["rac"].sort(key=lambda r: (str(r["type"]), r["quality"] or 0))
    stats = {
        "tong": len(weapons),
        "giu": len(out["giu"]), "rac": len(out["rac"]), "xam": len(out["xam"]),
        "giu_theo_ly_do": dict(Counter(x for r in out["giu"] for x in r["ly_do"][:1])),
        "rac_theo_do_hiem": dict(Counter(r["rarity"] for r in out["rac"])),
        "rac_theo_loai": dict(Counter(r["type"] for r in out["rac"]).most_common()),
        "xam_theo_ly_do": dict(Counter(x for r in out["xam"] for x in r["ly_do"])),
        "xam_passive": dict(xam_passive.most_common()),
    }
    return {"tao_luc": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "tham_so": {"giu_top_moi_loai": keep_top, "do_hiem_khong_tu_xoa": list(HIGH_RARITIES),
                        "passive_hoi_wp": rules.get("ruby", {}).get("passive_hoi_wp", []),
                        "loai_khong_xoa": rules.get("never_dismantle", [])},
            "thong_ke": stats, **out}


def summary_text(plan, max_chars=1800):
    """Ban tom tat ngan cho Discord (gioi han 2000 ky tu)."""
    s = plan["thong_ke"]
    lines = [f"🧹 **Kế hoạch dọn vũ khí** — {s['tong']} cây (CHƯA xóa gì)",
             f"🟢 Giữ: **{s['giu']}** · 🔴 Rác: **{s['rac']}** · ⚪ Xám (bạn quyết): **{s['xam']}**"]
    if s["giu_theo_ly_do"]:
        names = {"yeu_thich": "⭐", "dang_trang_bi": "đang cầm", "loai_khong_xoa": "Rune", "passive_tot": "passive tốt",
                 "top_chat_luong": "top chất lượng"}
        lines.append("Giữ vì: " + ", ".join(f"{names.get(k, k)} {v}" for k, v in s["giu_theo_ly_do"].items()))
    if s["rac"]:
        lines.append("Rác theo độ hiếm: " + ", ".join(f"{k} {v}" for k, v in s["rac_theo_do_hiem"].items()))
    if s["xam_passive"]:
        lines.append("Passive làm cây rơi vào xám (bạn cho biết cái nào tốt/xấu):")
        for k, v in list(s["xam_passive"].items())[:8]:
            lines.append(f"• {k}: {v} cây")
    text = "\n".join(lines)
    return text if len(text) <= max_chars else text[:max_chars - 1] + "…"
