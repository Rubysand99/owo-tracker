"""Tu duyet vu khi: doc bot NeonUtil + chi so Knowledge roi tu quyet GIU / RAC.

Ham THUAN (khong discord, khong DB) de test o bat ky dau. Nguyen tac an toan: cai gi KHONG doc duoc / khong chac
-> GIU (khong bao gio tu quyet RAC khi thieu du lieu).
"""
import re

import weapon_cleanup

NEON_BOT_ID = 851436490415931422
KNOWLEDGE_KEEP_ABOVE = 14.0          # Knowledge > 14% -> giu bat ke vu khi gi
HIGH_TIERS = ("mythic", "legendary", "fabled")
TIER_ORDER = ("common", "uncommon", "rare", "epic", "mythic", "legendary", "fabled")

_NUM = r"\d+(?:\.\d+)?"
_RANGE_LINE_RE = re.compile(r"Range:\s*(" + _NUM + r")\s*[-–]\s*(" + _NUM + r")(.*)", re.I)
_VALUE_RE = re.compile(r"\*\*\s*\+?(" + _NUM + r")%?\s*\*\*")
_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")


def tier_from_text(s):
    """Chuoi (ten emoji hoac chu) -> ten bac chuan, hoac None neu khong nhan ra. 'mythical' == 'mythic'."""
    t = re.sub(r"[^a-z]", "", (s or "").lower())
    if not t:
        return None
    for name, key in (("uncommon", "uncommon"), ("common", "common"), ("mythical", "mythic"), ("mythic", "mythic"),
                      ("legendary", "legendary"), ("fabled", "fabled"), ("epic", "epic"), ("rare", "rare")):
        if name in t:
            return key
    # ten viet tat kieu OwO: 'ctier','utier'... khong du chac -> None
    return None


def _tier_of_segment(seg):
    for en in _EMOJI_RE.findall(seg):
        t = tier_from_text(en)
        if t:
            return t
    return tier_from_text(_EMOJI_RE.sub(" ", seg))


def parse_neon_breakdown(text):
    """Embed Details/Breakdown cua NeonUtil -> {'id', 'stats': [{value, lo, hi, tier, pct}]} (thu tu: chi so vu khi
    truoc, passive sau). Tra ve None neu khong thay dong 'Range:' nao."""
    stats = []
    for line in (text or "").splitlines():
        m = _RANGE_LINE_RE.search(line)
        if not m:
            continue
        vm = _VALUE_RE.search(line[:m.start()])
        rest = m.group(3)
        pct = re.search(r"(" + _NUM + r")\s*%", rest)
        stats.append({
            "value": float(vm.group(1)) if vm else None,
            "lo": float(m.group(1)), "hi": float(m.group(2)),
            "tier": _tier_of_segment(rest),
            "pct": float(pct.group(1)) if pct else None,
        })
    if not stats:
        return None
    idm = re.search(r"\(\s*`?([A-Za-z0-9]{4,8})`?\s*\)", text or "")
    return {"id": idm.group(1).upper() if idm else None, "stats": stats}


def parse_neon_compact(text):
    """Tin gon cua NeonUtil: '<tier> NN% max | `<wear> <type> w1,w2 <passive> p1,p2`'.
    Tra ve {'n_weapon': so chi so vu khi} hoac None. Chi nhan khi doc duoc ro rang."""
    m = re.search(r"`([^`\n]+)`", text or "")
    if not m:
        return None
    nums = [i for i, tok in enumerate(m.group(1).split()) if re.fullmatch(_NUM + r"(?:," + _NUM + r")*", tok)]
    if not nums:
        return None
    first = m.group(1).split()[nums[0]]
    return {"n_weapon": len(first.split(","))}


def knowledge_value(passive):
    """Gia tri that cua passive Knowledge (%), hoac None neu cay khong co Knowledge / khong doc duoc.
    passive = {'name','desc'} tu parse_weapon_detail."""
    if not passive or "knowledge" not in re.sub(r"[^a-z]", "", (passive.get("name") or "").lower()):
        return None
    m = re.search(r"\+?\s*\*{0,2}\s*(" + _NUM + r")\s*\*{0,2}\s*%", passive.get("desc") or "")
    return float(m.group(1)) if m else None


def weapon_stat_tiers(breakdown, n_weapon):
    """Bac cua tung chi so VU KHI (khong phai passive). None neu khong chac (thieu so luong / lech so luong)."""
    if not breakdown or not n_weapon or n_weapon < 1 or len(breakdown["stats"]) < n_weapon:
        return None
    return [s["tier"] for s in breakdown["stats"][:n_weapon]]


def auto_decide(weapon, detail, breakdown, n_weapon, rules):
    """Tra ve (decision, ly_do): decision 'keep' | 'drop'.
    weapon: muc trong danh sach kho ({id,type,passives,rarity,quality,...}); detail: parse_weapon_detail (hoac None);
    breakdown/n_weapon: tu Neon (hoac None). XAM -> keep. Thieu du lieu -> keep."""
    kv = knowledge_value((detail or {}).get("passive"))
    if kv is not None and kv > KNOWLEDGE_KEEP_ABOVE:
        return "keep", f"knowledge_{kv:g}%"
    bucket, reasons, _ = weapon_cleanup.classify_weapon(weapon, rules)
    if bucket == "giu":
        return "keep", reasons[0]
    if bucket == "xam":
        return "keep", "xam:" + ",".join(reasons)
    # bucket == rac: chi duoc bo khi DA doc chac chi so vu khi tu Neon va khong cai nao Mythic+
    tiers = weapon_stat_tiers(breakdown, n_weapon)
    if tiers is None:
        return "keep", "thieu_du_lieu_neon"
    if any(t is None for t in tiers):
        return "keep", "bac_chi_so_la"
    if any(t in HIGH_TIERS for t in tiers):
        return "keep", "chi_so_vu_khi_" + max(tiers, key=TIER_ORDER.index)
    return "drop", "rac_chi_so_thap"


def needs_neon_check(weapon, detail, rules):
    """Cay chi can mo Details cua Neon khi luat cu xep RAC (cac cay con lai da biet la GIU)."""
    kv = knowledge_value((detail or {}).get("passive"))
    if kv is not None and kv > KNOWLEDGE_KEEP_ABOVE:
        return False
    bucket, _, _ = weapon_cleanup.classify_weapon(weapon, rules)
    return bucket == "rac"
