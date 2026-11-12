"""tools_api.py — các hàm THUẦN (không đụng DB/Discord) cho các đường API mới của màn "Công cụ" trong app:
GET /teamcheck, GET /zoodiff, GET /unlocked, GET|POST /alt, POST /alt/test, POST /manual/pet|weapontype|passive.
owo_tracker_bot.py lo phần lấy dữ liệu và trả JSON; file này chỉ lo kiểm tra đầu vào và gom/làm sạch chữ,
nên test được trực tiếp (xem test_tools_api.py).
"""
import re

# ID Discord (snowflake) hiện dài 17-20 chữ số; nới 15-25 cho chắc.
ALT_ID_RE = re.compile(r"^\d{15,25}$")

# `,zoodiff d|all` = số đã bắt (owo zoo d) · `,zoodiff now|current` = đang giữ (owo zoo)
ZOODIFF_KINDS = {"d": "all", "all": "all", "now": "current", "current": "current"}

# Emoji tùy chỉnh của Discord: <:tên:123456> hoặc <a:tên:123456> (a = động)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:([A-Za-z0-9_~]+):\d+>")


# Nhập tay: ,petset ,weapontypeset ,passiveset (POST /manual/pet|weapontype|passive)
PET_STAT_KEYS = ("hp", "att", "pr", "wp", "mag", "mr")
PET_STAT_MAX = 100000
MANUAL_NAME_MAX = 60
MANUAL_DESC_MAX = 1000
# Rank chỉ gồm chữ cái (Common, Legendary, Botrank...), tối đa 20 ký tự.
_RANK_RE = re.compile(r"^[A-Za-z]{1,20}$")
# Ký tự điều khiển (xuống dòng, tab...) không được lọt vào tên / mô tả.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _clean_name(raw):
    """Tên pet / loại vũ khí / passive: chuỗi 1-60 ký tự sau khi cắt khoảng trắng 2 đầu, không có ký tự điều khiển.
    Trả tên đã cắt, hoặc None nếu sai."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or len(s) > MANUAL_NAME_MAX or _CONTROL_RE.search(s):
        return None
    return s


def _clean_desc(raw):
    """Mô tả: chuỗi 1-1000 ký tự sau khi cắt khoảng trắng; cho phép xuống dòng, cấm các ký tự điều khiển khác."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or len(s) > MANUAL_DESC_MAX or _CONTROL_RE.search(s.replace("\n", "")):
        return None
    return s


def _stat(raw):
    """Chỉ số pet phải là số nguyên (không nhận bool, số thực, chuỗi) trong khoảng 0..PET_STAT_MAX."""
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw if 0 <= raw <= PET_STAT_MAX else None


def parse_pet_manual(body):
    """Kiểm tra body của POST /manual/pet: {"name", "rank", "hp", "att", "pr", "wp", "mag", "mr"}.
    Trả (ok, dữ liệu): ok True -> {"name", "rank" (viết hoa chữ đầu), "hp"...}; sai bất kỳ trường nào -> (False, tên trường sai)."""
    if not isinstance(body, dict):
        return False, "body"
    name = _clean_name(body.get("name"))
    if name is None:
        return False, "name"
    rank = body.get("rank")
    if not isinstance(rank, str) or not _RANK_RE.match(rank.strip()):
        return False, "rank"
    out = {"name": name, "rank": rank.strip().capitalize()}
    for key in PET_STAT_KEYS:
        v = _stat(body.get(key))
        if v is None:
            return False, key
        out[key] = v
    return True, out


def parse_desc_manual(body):
    """Kiểm tra body của POST /manual/weapontype và /manual/passive: {"name", "desc"}.
    Trả (ok, {"name", "desc"}); sai -> (False, tên trường sai)."""
    if not isinstance(body, dict):
        return False, "body"
    name = _clean_name(body.get("name"))
    if name is None:
        return False, "name"
    desc = _clean_desc(body.get("desc"))
    if desc is None:
        return False, "desc"
    return True, {"name": name, "desc": desc}


def parse_alt_id(raw):
    """Kiểm tra ID acc phụ app gửi lên. Trả (ok, giá trị).
    Chuỗi rỗng (hoặc toàn khoảng trắng) = XÓA acc phụ -> (True, ""). Không phải chuỗi / không phải dãy 15-25 chữ số -> (False, "")."""
    if not isinstance(raw, str):
        return False, ""
    s = raw.strip()
    if s == "":
        return True, ""
    if ALT_ID_RE.match(s):
        return True, s
    return False, ""


def parse_zoodiff_kind(raw):
    """Tham số `kind` của /zoodiff. Trả (ok, kind): rỗng/None -> (True, None) = tự chọn lần ghi gần nhất;
    d/all -> "all"; now/current -> "current"; khác -> (False, None)."""
    if raw is None:
        return True, None
    s = str(raw).strip().lower()
    if not s:
        return True, None
    kind = ZOODIFF_KINDS.get(s)
    return (True, kind) if kind else (False, None)


def plain_text(text):
    """Chữ Discord -> chữ thường cho app: bỏ **đậm**, `mã`, đổi emoji tùy chỉnh <:bee:123> thành tên (bee)."""
    if not text:
        return ""
    out = _CUSTOM_EMOJI_RE.sub(lambda m: m.group(1), str(text))
    return out.replace("**", "").replace("`", "")


def group_unlocked(rows, tier=None):
    """Gom pet đã mở khóa theo tier, giữ thứ tự `rows` (bot đã sắp theo bậc hiếm).
    rows: [{"tier", "name", ...}]. tier: lọc 1 tier (không phân biệt hoa/thường), None/"" = tất cả.
    Trả {"total": n, "tiers": [{"tier", "count", "pets": [tên]}]}, hoặc None nếu `tier` không có trong dữ liệu."""
    by_tier = {}
    for r in rows:
        name = r.get("name")
        if not name:
            continue
        by_tier.setdefault(r.get("tier"), []).append(str(name))
    only = (tier or "").strip().lower() or None
    if only and only not in by_tier:
        return None
    tiers = [{"tier": t, "count": len(names), "pets": names}
             for t, names in by_tier.items() if not only or t == only]
    return {"total": sum(t["count"] for t in tiers), "tiers": tiers}
