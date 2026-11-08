"""Nhap file `weapons.json` (lenh `,w inv export` cua NeonUtil, chu bot cho phep) -> lap danh sach GIU / BO.

Ham THUAN (khong discord, khong DB). KHONG xoa gi, khong goi bot nao; chi doc file Ruby tu xuat ra.

Dinh dang 1 cay (theo giai thich cua chu NeonUtil):
  t  = loai vu khi (id trong bang WEAPON_STATS)      q = chat luong TONG (trung binh cac chi so + passive)
  p  = [{t: id passive, r: bac chat luong passive 0..6}]   id = ma cay
  l  = true: da khoa (yeu thich/dang dung)   w = do mon   k = co kill / chi co TT
  bp = chuoi bac TUNG chi so, chi co o cay da `owo w <ID>`:  "[fine|decent] <loai> a,b,c <passive> NN ..."
       a,b = chi so chinh theo thu tu, SO CUOI = chi phi WP; roi toi passive.  Passive thieu so = 100.

LUAT (Ruby chon, "luat cu"):
  - Loai dac biet (Rune of Celebration / Luck)  -> GIU (luat cu: khong bao gio ra)
  - Da khoa                                    -> GIU
  - Co kill (k = true)                         -> GIU (khong bo cay da co kill)
  - Co bp doc duoc: chi so chinh >= 80%        -> GIU   (Mythic tro len; khong tinh chi phi WP va passive)
  - Passive hang >= 5 (gom Knowledge > 14%)    -> GIU
  - Khong co bp: q >= 75                       -> GIU
  - bp co nhung la / khong doc duoc            -> GIU (thieu du lieu thi khong bao gio Bo)
  - Con lai                                    -> BO
"""
import json

# id loai -> so khoang trong bang dump (= so chi so chinh + 1 chi phi WP; Orb = 0, Rune of the Forgotten = 1)
WEAPON_STATS = {1: 2, 2: 2, 3: 2, 4: 1, 5: 2, 6: 0, 7: 2, 8: 3, 9: 3, 10: 4, 11: 2, 12: 3, 13: 2, 14: 2, 15: 2,
                16: 4, 17: 3, 18: 3, 19: 3, 20: 5, 21: 3, 22: 6, 23: 3, 24: 3, 25: 4, 26: 3, 27: 3, 28: 4, 29: 3}

NEVER_DROP_TYPES = {18, 22}   # Rune of Celebration, Rune of Luck (weapon_rules.json: never_dismantle 118 / 122)
STAT_KEEP_MIN = 80        # chi so chinh >= 80% (Mythic tro len)
PASSIVE_KEEP_RANK = 5     # passive hang >= 5 (~93%+): Legendary tro len, gom Knowledge > 14%
NO_BP_KEEP_Q = 75.0       # cay khong co bp: chat luong tong
_WEAR = ("fine", "decent", "pristine", "worn")


def parse_export(data) -> list:
    """bytes/str JSON -> list cay hop le. Loi dinh dang -> ValueError (de bao Ruby)."""
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8-sig")
    data = data.lstrip("\ufeff")
    try:
        arr = json.loads(data)
    except ValueError as e:
        raise ValueError(f"không phải file JSON hợp lệ ({e})")
    if not isinstance(arr, list) or not arr:
        raise ValueError("file rỗng hoặc không phải danh sách vũ khí")
    out = []
    for w in arr:
        if isinstance(w, dict) and w.get("id") and isinstance(w.get("t"), int) and isinstance(w.get("q"), (int, float)):
            out.append(w)
    if not out:
        raise ValueError("không thấy cây nào đúng định dạng (cần id, t, q) — có phải file `,w inv export` không?")
    return out


def main_stat_qualities(w):
    """Chat luong (0-100) cac chi so CHINH tu bp (khong tinh chi phi WP). None = khong co bp / khong doc duoc."""
    s = w.get("bp")
    if not s:
        return None
    n = WEAPON_STATS.get(w.get("t"))
    if n is None:
        return None
    if n == 0:
        return []
    toks = str(s).split()
    if toks and toks[0] in _WEAR:
        toks = toks[1:]
    if len(toks) < 2:
        return None
    try:
        nums = [int(v) for v in toks[1].split(",")]
    except ValueError:
        return None
    if len(nums) != n:
        return None
    return nums[:-1]


def top_passive_rank(w) -> int:
    ranks = [p.get("r") for p in (w.get("p") or []) if isinstance(p.get("r"), int)]
    return max(ranks) if ranks else -1


def decide(w):
    """-> (decision 'keep'|'drop', ly do ngan). Xem LUAT o dau file."""
    if w.get("t") in NEVER_DROP_TYPES:
        return "keep", "loai_dac_biet"
    if w.get("l"):
        return "keep", "khoa"
    if w.get("k") is True:
        return "keep", "co_kill"
    if top_passive_rank(w) >= PASSIVE_KEEP_RANK:
        return "keep", "passive_cao"
    if w.get("bp"):
        stats = main_stat_qualities(w)
        if stats is None:
            return "keep", "bp_la"
        if any(v >= STAT_KEEP_MIN for v in stats):
            return "keep", "chi_so_cao"
        return "drop", "chi_so_thap"
    if w["q"] >= NO_BP_KEEP_Q:
        return "keep", "q_cao"
    return "drop", "q_thap"


REASON_TEXT = {
    "loai_dac_biet": "loại đặc biệt (Rune of Celebration/Luck)",
    "co_kill": "đã có kill",
    "khoa": "đã khóa",
    "passive_cao": "passive hạng ≥ 5 (gồm Knowledge > 14%)",
    "chi_so_cao": f"có chỉ số chính ≥ {STAT_KEEP_MIN}%",
    "bp_la": "bp lạ/không đọc được (giữ cho an toàn)",
    "q_cao": f"không có bp, chất lượng tổng ≥ {NO_BP_KEEP_Q:g}",
    "chi_so_thap": "có bp nhưng chỉ số chính đều < 80%",
    "q_thap": f"không có bp, chất lượng tổng < {NO_BP_KEEP_Q:g}",
}


def build_plan(weapons: list) -> dict:
    """-> {'keep': {id: reason}, 'drop': {id: reason}, 'reasons': {reason: n}, 'total': n}"""
    keep, drop, reasons = {}, {}, {}
    for w in weapons:
        d, why = decide(w)
        (keep if d == "keep" else drop)[str(w["id"])] = why
        reasons[why] = reasons.get(why, 0) + 1
    return {"keep": keep, "drop": drop, "reasons": reasons, "total": len(weapons)}


def summary_text(plan: dict) -> str:
    lines = [f"**Nhập file kho vũ khí: {plan['total']} cây**",
             f"✅ Giữ **{len(plan['keep'])}** · 🗑️ Bỏ **{len(plan['drop'])}** (CHƯA xóa gì)"]
    for why in ("loai_dac_biet", "khoa", "co_kill", "passive_cao", "chi_so_cao", "bp_la", "q_cao", "chi_so_thap", "q_thap"):
        n = plan["reasons"].get(why)
        if n:
            lines.append(f"• {'Giữ' if why in ('loai_dac_biet','khoa','co_kill','passive_cao','chi_so_cao','bp_la','q_cao') else 'Bỏ'}: {REASON_TEXT[why]} — {n}")
    return "\n".join(lines)


def dismantle_commands(drop_ids, per_cmd: int = 1, page: int = 1, page_size: int = 15):
    """Chia danh sach ID BO thanh cac dong `owo dismantle <id> [<id>...]` de Ruby TU DAN tay.
    -> (cac dong cua trang, tong so lenh, tong so trang). Sap xep co dinh theo ID de cac trang on dinh."""
    ids = sorted(str(i) for i in drop_ids)
    per_cmd = max(1, min(int(per_cmd or 1), 10))
    cmds = ["owo dismantle " + " ".join(ids[i:i + per_cmd]) for i in range(0, len(ids), per_cmd)]
    pages = max(1, -(-len(cmds) // page_size))
    page = max(1, min(int(page or 1), pages))
    return cmds[(page - 1) * page_size: page * page_size], len(cmds), pages


def star_lines(keep_ids, template: str = "", page: int = 1, page_size: int = 20):
    """Danh sach cay GIU chua khoa/chua sao -> cac dong de Ruby TU DANH SAO tay.
    template = phan lenh dat truoc ID (vd 'owo star'); rong thi chi liet ke ID. -> (dong cua trang, tong, so trang)."""
    ids = sorted(str(i) for i in keep_ids)
    tpl = (template or "").strip()
    lines = [f"{tpl} {i}" if tpl else i for i in ids]
    pages = max(1, -(-len(lines) // page_size))
    page = max(1, min(int(page or 1), pages))
    return lines[(page - 1) * page_size: page * page_size], len(lines), pages
