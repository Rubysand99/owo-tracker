"""Nhap file `weapons.json` (lenh `,w inv export` cua NeonUtil, chu bot cho phep) -> lap danh sach GIU / BO.

Ham THUAN (khong discord, khong DB). KHONG xoa gi, khong goi bot nao; chi doc file Ruby tu xuat ra.

Dinh dang 1 cay (theo giai thich cua chu NeonUtil):
  t  = loai vu khi (id trong bang WEAPON_STATS)      q = chat luong TONG (trung binh cac chi so + passive)
  p  = [{t: id passive, r: bac chat luong passive 0..6}]   id = ma cay
  l  = true: da khoa (yeu thich/dang dung)   w = do mon   k = co kill / chi co TT
  bp = chuoi bac TUNG chi so, chi co o cay da `owo w <ID>`:  "[fine|decent] <loai> a,b,c <passive> NN ..."
       a,b = chi so chinh theo thu tu, SO CUOI = chi phi WP; roi toi passive.  Passive thieu so = 100.

LUAT (v1.33, Ruby chon):
  - Loai dac biet (Rune of Celebration / Luck)  -> GIU (luat cu: khong bao gio ra)
  - Da khoa                                    -> GIU
  - Co kill (k = true)                         -> GIU (khong bo cay da co kill)
  - TOP 6 Knowledge cao nhat                   -> GIU (bot luu 6 cay; co cay cao hon thi thay vao, cay bi day ra xet nhu cay thuong)
  - Co bp doc duoc: >= 2 chi so >= 80%       -> GIU   (Mythic tro len; TINH CA chi phi WP, KHONG tinh passive); doc du ma khong du -> BO (chac chan)
  - Co bp doc duoc nhung < 2 chi so >= 80%     -> BO    (passive khac khong cuu duoc nua)
  - Khong co bp (chua `owo w <ID>`): khong biet co phai Knowledge khong
        passive hang >= 5 -> GIU; q >= 75 -> GIU; con lai KHONG Bo (chua chac) -> GIU + danh dau "Chua ro"
  - bp co nhung la / khong doc duoc            -> GIU (thieu du lieu thi khong bao gio Bo)
"""
import json
import re

# id loai -> so khoang trong bang dump (= so chi so chinh + 1 chi phi WP; Orb = 0, Rune of the Forgotten = 1)
WEAPON_STATS = {1: 2, 2: 2, 3: 2, 4: 1, 5: 2, 6: 0, 7: 2, 8: 3, 9: 3, 10: 4, 11: 2, 12: 3, 13: 2, 14: 2, 15: 2,
                16: 4, 17: 3, 18: 3, 19: 3, 20: 5, 21: 3, 22: 6, 23: 3, 24: 3, 25: 4, 26: 3, 27: 3, 28: 4, 29: 3}

NEVER_DROP_TYPES = {18, 22}   # Rune of Celebration, Rune of Luck (weapon_rules.json: never_dismantle 118 / 122)
STAT_KEEP_COUNT = 2      # can it nhat 2 chi so dat STAT_KEEP_MIN moi giu
STAT_KEEP_MIN = 80        # moi chi so (ke ca chi phi WP) >= 80% (Mythic tro len)
KNOWLEDGE_TOP_N = 6       # luu / giu 6 cay co Knowledge cao nhat
UNVERIFIED_PASSIVE_RANK = 5   # cay CHUA co bp: passive hang >= 5 (~93%+) -> chua biet co phai Knowledge cao -> khong Bo
NO_BP_KEEP_Q = 75.0       # cay khong co bp: chat luong tong
_WEAR = ("fine", "decent", "pristine", "worn")
_KNOWLEDGE_NAMES = ("kno", "knowledge")


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


def all_stat_qualities(w):
    """Chat luong (0-100) TAT CA chi so tu bp, KE CA chi phi WP (so cuoi). None = khong co bp / khong doc duoc.
    Orb (khong co chi so nao) tra ve []."""
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
    return nums


def main_stat_qualities(w):
    """Chat luong (0-100) cac chi so CHINH tu bp (khong tinh chi phi WP). None = khong co bp / khong doc duoc."""
    nums = all_stat_qualities(w)
    return None if nums is None else nums[:-1]


def knowledge_quality(w):
    """Chat luong (0-100) cua passive Knowledge doc tu bp (vd `... kno 95`; passive thieu so = 100).
    None = khong co bp / cay khong co Knowledge. Chat luong cang cao thi % Knowledge cang cao."""
    s = w.get("bp")
    n = WEAPON_STATS.get(w.get("t"))
    if not s or n is None:
        return None
    toks = str(s).split()
    if toks and toks[0] in _WEAR:
        toks = toks[1:]
    rest = toks[2:] if n > 0 else toks[1:]       # bo ten loai va (neu co) cum chi so
    i = 0
    while i < len(rest):
        if not rest[i].isalpha():
            i += 1
            continue
        has_num = i + 1 < len(rest) and rest[i + 1].isdigit()
        if rest[i].lower() in _KNOWLEDGE_NAMES:
            return int(rest[i + 1]) if has_num else 100
        i += 2 if has_num else 1
    return None


def knowledge_top(weapons, stored=None, k=KNOWLEDGE_TOP_N):
    """K cay Knowledge cao nhat: gop file moi voi danh sach da luu (chi giu cay con trong kho; file moi ghi de gia tri cu).
    Co cay cao hon thi tu thay vao. -> [{'id', 'v'}] giam dan theo v (hoa thi q cao hon, roi theo ID)."""
    present = {str(w["id"]): w for w in weapons}
    cand = {}
    for e in stored or []:
        if isinstance(e, dict) and str(e.get("id")) in present and isinstance(e.get("v"), (int, float)):
            cand[str(e["id"])] = e["v"]
    for wid, w in present.items():
        v = knowledge_quality(w)
        if v is not None:
            cand[wid] = v
    order = sorted(cand, key=lambda i: (-cand[i], -(present[i].get("q") or 0), i))
    return [{"id": i, "v": cand[i]} for i in order[:k]]


_ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"))
_NUMCSV = re.compile(r"\d+(?:\.\d+)?(?:,\d+(?:\.\d+)?)*")


def neon_bp(text, rules):
    """Doc dong gon NeonUtil tu dong tra loi `owo w <ID>` (vd '... `sstaff 100,91,68 knowledge 98`') -> {'t': id loai, 'bp': chuoi}
    hoac None neu khong doc ro. Doan bp nam trong dau ` hoac giua 2 ky tu word-joiner (app doc man hinh thay U+2060)."""
    text = (text or "").translate(_ZW)
    spans = re.findall(r"`([^`\n]+)`", text) + re.findall(r"\u2060([^\u2060\n]+)\u2060", text)
    keymap = {}
    for tid, info in ((rules or {}).get("types") or {}).items():
        try:
            t = int(tid) - 100
        except ValueError:
            continue
        for k in (info.get("key"), info.get("tag")):
            if k:
                keymap[str(k).lower()] = t
    for sp in spans:
        toks = sp.split()
        if toks and toks[0] in _WEAR:
            toks = toks[1:]
        if len(toks) < 1 or toks[0].lower() not in keymap:
            continue
        t = keymap[toks[0].lower()]
        if WEAPON_STATS.get(t) == 0 or (len(toks) > 1 and _NUMCSV.fullmatch(toks[1])):
            return {"t": t, "bp": " ".join(toks)}
    return None


def top_passive_rank(w) -> int:
    ranks = [p.get("r") for p in (w.get("p") or []) if isinstance(p.get("r"), int)]
    return max(ranks) if ranks else -1


def decide(w, kno_top=()):
    """-> (decision 'keep'|'drop', ly do ngan). Xem LUAT o dau file.
    kno_top = tap ID nam trong TOP Knowledge (do build_plan tinh bang knowledge_top)."""
    if w.get("t") in NEVER_DROP_TYPES:
        return "keep", "loai_dac_biet"
    if w.get("l"):
        return "keep", "khoa"
    if w.get("k") is True:
        return "keep", "co_kill"
    if str(w.get("id")) in kno_top:
        return "keep", "knowledge_top"
    if w.get("bp"):
        stats = all_stat_qualities(w)
        if stats is None:
            return "keep", "bp_la"
        if 0 < len(stats) < STAT_KEEP_COUNT:
            return "keep", "bp_la"     # loai chi co 1 chi so: luat "2 chi so" khong ap dung duoc -> khong tu Bo
        if sum(1 for v in stats if v >= STAT_KEEP_MIN) >= STAT_KEEP_COUNT:
            return "keep", "chi_so_cao"
        return "drop", "chi_so_thap"
    # Chua co bp: khong biet cay co Knowledge cao hay khong -> passive hang cao thi khong Bo (Bo la khong quay lai duoc)
    if top_passive_rank(w) >= UNVERIFIED_PASSIVE_RANK:
        return "keep", "chua_xem_passive_cao"
    if w["q"] >= NO_BP_KEEP_Q:
        return "keep", "q_cao"
    # Khong co bp thi KHONG biet tung chi so -> khong du can cu Bo (chi Bo khi chac 100%): dua vao "Khong xac dinh"
    return "keep", "q_thap_chua_chac"


REASON_TEXT = {
    "loai_dac_biet": "loại đặc biệt (Rune of Celebration/Luck)",
    "co_kill": "đã có kill",
    "khoa": "đã khóa",
    "knowledge_top": f"nằm trong top {KNOWLEDGE_TOP_N} Knowledge cao nhất",
    "chi_so_cao": f"có ≥ {STAT_KEEP_COUNT} chỉ số (gồm chi phí WP) ≥ {STAT_KEEP_MIN}%",
    "chua_xem_passive_cao": "chưa xem chi tiết (`owo w <ID>`) và có passive hạng ≥ 5 — chưa rõ có phải Knowledge cao",
    "bp_la": "bp lạ/không đọc được (giữ cho an toàn)",
    "q_cao": f"không có bp, chất lượng tổng ≥ {NO_BP_KEEP_Q:g}",
    "chi_so_thap": f"đã đọc đủ chỉ số, chưa có {STAT_KEEP_COUNT} chỉ số nào ≥ {STAT_KEEP_MIN}% (chắc chắn không đạt)",
    "q_thap_chua_chac": f"không có bp, chất lượng tổng < {NO_BP_KEEP_Q:g} — chưa xem chỉ số nên chưa chắc, để 'Chưa rõ'",
    "q_thap": f"không có bp, chất lượng tổng < {NO_BP_KEEP_Q:g}",
}
KEEP_REASONS = ("loai_dac_biet", "khoa", "co_kill", "knowledge_top", "chi_so_cao", "chua_xem_passive_cao", "bp_la", "q_cao", "q_thap_chua_chac")
# Cay bot GIU vi chua chac (khong phai vi dat luat): hien o danh sach "Khong xac dinh" cho Ruby tu check tay
UNSURE_REASONS = ("chua_xem_passive_cao", "bp_la", "q_thap_chua_chac")
DROP_REASONS = ("chi_so_thap",)


def build_plan(weapons: list, knowledge_stored=None) -> dict:
    """-> {'keep': {id: reason}, 'drop': {id: reason}, 'reasons': {reason: n}, 'total': n, 'knowledge_top': [{'id','v'}]}
    knowledge_stored = danh sach top Knowledge da luu o lan nhap truoc (bot luu lai plan['knowledge_top'])."""
    top = knowledge_top(weapons, knowledge_stored)
    top_ids = {e["id"] for e in top}
    keep, drop, reasons = {}, {}, {}
    for w in weapons:
        d, why = decide(w, top_ids)
        (keep if d == "keep" else drop)[str(w["id"])] = why
        reasons[why] = reasons.get(why, 0) + 1
    return {"keep": keep, "drop": drop, "reasons": reasons, "total": len(weapons), "knowledge_top": top}


def summary_text(plan: dict) -> str:
    lines = [f"**Nhập file kho vũ khí: {plan['total']} cây**",
             f"✅ Giữ **{len(plan['keep'])}** · 🗑️ Bỏ **{len(plan['drop'])}** (CHƯA xóa gì)"]
    for why in KEEP_REASONS + DROP_REASONS:
        n = plan["reasons"].get(why)
        if n:
            lines.append(f"• {'Giữ' if why in KEEP_REASONS else 'Bỏ'}: {REASON_TEXT[why]} — {n}")
    top = plan.get("knowledge_top") or []
    if top:
        lines.append(f"🧠 Top {KNOWLEDGE_TOP_N} Knowledge: " + " · ".join(f"`{e['id']}` {e['v']:g}" for e in top))
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


# ---------------- Don kho theo "cach lai" ----------------
# OwO bo qua cay DA SAO khi ra theo bac -> sao cay GIU o cac bac thap, ra theo bac cho phan do; dai cao ra theo ID.
RARE_MIN_Q = 40.0           # Rare tu ~40% (doi chieu: tin OwO "71 Rare" = 73 cay q 40..60.6 tru 2 cay da khoa)
RARE_MAX_KNOWN_Q = 60.6     # cay Rare cao nhat da thay (anh OwO)
EPIC_MIN_KNOWN_Q = 61.2     # cay bac tren thap nhat trong kho luc doi chieu
SPLIT_Q = 61.0              # < SPLIT: nhom "ra theo bac" (common/uncommon/rare); >= SPLIT: ra theo ID


def cleanup_stages(docs, extra_drop=()) -> dict:
    """docs = [{'_id','decision','reason','q'}] (cac cay ,weaponimport da ghi). Cay da khoa / khong co q bi bo qua.
    -> star_ids (GIU, chua khoa, q < SPLIT: phai SAO truoc khi ra theo bac), low_drop (BO, q < RARE_MIN: common+uncommon),
       rare_drop (BO, RARE_MIN <= q < SPLIT), id_drop (BO, q >= SPLIT: ra theo ID), unsure (q nam giua cay Rare cao nhat va
       cay bac tren thap nhat da biet -> chua chac thuoc bac nao), missing_q (so cay thieu q: can nhap lai file)."""
    out = {"star_ids": [], "low_drop": [], "rare_drop": [], "id_drop": [], "unsure": [], "missing_q": 0}
    extra = {str(i).upper() for i in (extra_drop or ())}
    for d in docs:
        q = d.get("q")
        if q is None:
            out["missing_q"] += 1
            continue
        wid = str(d["_id"])
        if wid.upper() in extra and d.get("reason") != "khoa":
            # Ruby them tay vao danh sach ra: luon ra THEO ID (an toan voi moi bac, ke ca cay o vung chua ro bac)
            out["id_drop"].append(wid)
            continue
        if RARE_MAX_KNOWN_Q < q < EPIC_MIN_KNOWN_Q:
            out["unsure"].append(wid)
        if d.get("decision") in ("keep", "unknown"):   # "khong xac dinh" = chua chac -> phai SAO nhu GIU (OwO khong ra cay da sao)
            if d.get("reason") != "khoa" and q < SPLIT_Q:
                out["star_ids"].append(wid)
        elif d.get("decision") == "drop":
            if q < RARE_MIN_Q:
                out["low_drop"].append(wid)
            elif q < SPLIT_Q:
                out["rare_drop"].append(wid)
            else:
                out["id_drop"].append(wid)
    for k in ("star_ids", "low_drop", "rare_drop", "id_drop", "unsure"):
        out[k].sort()
    return out


def cleanup_text(st: dict) -> str:
    if st["missing_q"]:
        return (f"⚠️ {st['missing_q']} cây trong danh sách chưa có chất lượng (nhập từ bản cũ). "
                "Gõ lại `,weaponimport` kèm file `weapons.json` mới rồi chạy `,cleanplan` lại.")
    n_low, n_rare, n_id = len(st["low_drop"]), len(st["rare_drop"]), len(st["id_drop"])
    lines = ["**Kế hoạch dọn kho (cách lai) — bạn tự làm từng bước, bot không tự gõ/bấm**",
             f"**Bước 1 — Đánh sao {len(st['star_ids'])} cây GIỮ** ở chất lượng < {SPLIT_Q:g} (OwO bỏ qua cây đã sao khi rã theo bậc). "
             "Danh sách: `,starlist` (mỗi cây: `owo w <ID>` rồi chạm nút sao).",
             f"**Bước 2 — Rã theo bậc**: `owo dismantle common`, `owo dismantle uncommon` rồi `owo dismantle rare`. "
             f"Common + Uncommon cộng lại phải đúng **{n_low}** cây, Rare phải đúng **{n_rare}** cây. Lệch số là bấm **Cancel** và báo lại.",
             f"**Bước 3 — Rã theo ID {n_id} cây** (chất lượng ≥ {SPLIT_Q:g}): `,dismantlelist`, dán từng dòng rồi tự bấm Dismantle.",
             "**Bước 4**: gõ `nw inv export`, rồi `,weaponimport` để cập nhật và kiểm tra lại."]
    if st["unsure"]:
        lines.append(f"⚠️ {len(st['unsure'])} cây có chất lượng ở vùng chưa rõ bậc ({RARE_MAX_KNOWN_Q:g}–{EPIC_MIN_KNOWN_Q:g}): "
                     + " ".join(f"`{i}`" for i in st["unsure"][:10]) + " — bạn kiểm tra tay trước khi rã.")
    return "\n".join(lines)


def cleanup_empty_reason(st: dict) -> str:
    """Vi sao cleanup_steps(st) rong (app hien cho Ruby biet, khong phai doan). Chuoi rong = khong co ly do (co the co buoc)."""
    if st.get("missing_q"):
        return f"{st['missing_q']} cây chưa có chất lượng — gõ lại `,weaponimport` kèm file `weapons.json` mới"
    if st.get("unsure"):
        ids = ", ".join(st["unsure"][:5]) + (" …" if len(st["unsure"]) > 5 else "")
        return (f"{len(st['unsure'])} cây có chất lượng ở vùng chưa rõ bậc ({ids}) — bạn kiểm tra tay bậc của các cây này "
                "(vd `owo w <ID>`), rồi xuất lại `nw inv export`")
    return "kho không có cây nào cần dọn tự động"


def cleanup_steps(st: dict, with_export: bool = False) -> list:
    """Cac buoc DON KHO cho app tu lam (thu tu: sao -> ra theo bac -> ra theo ID). Moi buoc = {action, params} gui qua
    queue_automacro_command. App chi bam Dismantle khi so cay / ID tren man hinh khop `expect` (xem CleanupRunner).
    Rong neu thieu q hoac con cay o vung chua ro bac (khong du chac de tu dong)."""
    if st.get("missing_q") or st.get("unsure"):
        return []
    steps = []
    for wid in st["star_ids"]:
        steps.append({"action": "clean_star", "params": {"command_text": f"owo w {wid}", "clean_mode": "star"}})
    n_low, n_rare = len(st["low_drop"]), len(st["rare_drop"])
    if n_low:   # common + uncommon cong lai dung n_low; moi lenh <= n_low, khong co cay nao thi bo qua (optional)
        for tier in ("common", "uncommon"):
            steps.append({"action": "clean_tier", "params": {
                "command_text": f"owo dismantle {tier}", "clean_mode": "tier", "expect_max": str(n_low), "optional": "1"}})
    if n_rare:
        steps.append({"action": "clean_tier", "params": {
            "command_text": "owo dismantle rare", "clean_mode": "tier", "expect": str(n_rare)}})
    for wid in st["id_drop"]:
        steps.append({"action": "clean_id", "params": {
            "command_text": f"owo dismantle {wid}", "clean_mode": "id", "expect_id": str(wid), "optional": "1"}})
    if steps and with_export:   # cuoi phien: app go `nw inv export` de Tom nhan file moi, kiem tra con gi can don
        steps.append({"action": "clean_export", "params": {"command_text": "nw inv export", "clean_mode": "export"}})
    return steps


_WID_RE = re.compile(r"^[A-Za-z0-9]{3,12}$")


def parse_weapon_ids(text: str):
    """Chuoi Ruby go (cach nhau bang dau cach / phay / xuong dong) -> (ids viet hoa khong trung, cac muc khong hop le)."""
    ids, bad = [], []
    for tok in re.split(r"[\s,;]+", text or ""):
        if not tok:
            continue
        if _WID_RE.match(tok):
            if tok.upper() not in ids:
                ids.append(tok.upper())
        else:
            bad.append(tok)
    return ids, bad
