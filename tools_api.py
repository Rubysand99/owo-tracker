"""tools_api.py — các hàm THUẦN (không đụng DB/Discord) cho các đường API mới của màn "Công cụ" trong app:
GET /teamcheck, GET /zoodiff, GET /unlocked, GET|POST /alt, POST /alt/test.
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
