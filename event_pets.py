"""event_pets.py — pet của sự kiện đang diễn ra (hiện: sự kiện tháng 11/2026). Hàm THUẦN, không đụng DB/Discord để test trực tiếp.

Mỗi tháng OwO ra sự kiện mới: sửa EVENT_TITLE / EVENT_END_EPOCH / EVENT_PETS bên dưới (tên pet lấy từ FAQ sự kiện).
Bot nhận ra pet qua TÊN emoji trong dòng `You found:` của owo hunt và trong bảng owo zoo; so khớp không phân biệt hoa thường,
bỏ dấu gạch dưới, và chấp nhận cả dạng rút gọn (vd `pumpkinpie`) phòng khi emoji không mang tiền tố sự kiện.
"""
import re
from datetime import datetime, timezone

EVENT_TITLE = "November"
EVENT_END_EPOCH = 1795939140          # <t:1795939140:f> trong FAQ = 2026-11-29 07:59 UTC
EVENT_PETS = (
    ("2026november_pumpkinpie", "Pumpkin Pie"),
    ("2026november_autumnHsin", "Autumn Hsin"),
)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def match_event_pet(name):
    """Tên emoji/pet -> khóa pet sự kiện (đúng như trong EVENT_PETS) hoặc None."""
    n = _norm(name)
    if not n:
        return None
    for key, _label in EVENT_PETS:
        if n in (_norm(key), _norm(key.split("_", 1)[-1])):
            return key
    return None


def find_in_animals(animals):
    """Danh sách {name, emoji_id?, emoji_animated?, count?} (từ hunt hoặc zoo) -> các mục là pet sự kiện, kèm `key`.
    Không trùng khóa (giữ mục đầu)."""
    out, seen = [], set()
    for a in animals or []:
        key = match_event_pet((a or {}).get("name"))
        if key and key not in seen:
            seen.add(key)
            out.append({**a, "key": key})
    return out


def _iso_z(value):
    return (str(value).rstrip("Z") + "Z") if value else None


def _age(value, now: datetime):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).rstrip("Z"))
    except ValueError:
        return None
    return max(0, int((now.replace(tzinfo=None) - t).total_seconds()))


def hub_payload(docs: dict, now: datetime):
    """Dữ liệu cho /hub (`event_pets`). docs: khóa pet -> bản ghi đã lưu (có thể thiếu = chưa thấy).
    Sự kiện đã kết thúc mà chưa tìm được con nào thì trả None (app ẩn mục này)."""
    now_epoch = int(now.replace(tzinfo=timezone.utc).timestamp()) if now.tzinfo is None else int(now.timestamp())
    pets = []
    for key, label in EVENT_PETS:
        d = (docs or {}).get(key) or {}
        found = bool(d.get("found"))
        pets.append({
            "key": key, "label": label, "found": found,
            "count": d.get("count"),                       # số đang giữ theo owo zoo (None = chưa thấy trong zoo)
            "times_found": int(d.get("times_found") or 0),  # số lần bot thấy trong tin hunt
            "first_found_at": _iso_z(d.get("first_found_at")) if found else None,
            "last_found_at": _iso_z(d.get("last_found_at")) if found else None,
            "age_seconds": _age(d.get("last_found_at"), now) if found else None,
            "emoji_id": d.get("emoji_id"), "emoji_animated": bool(d.get("emoji_animated")),
        })
    found_count = sum(1 for p in pets if p["found"])
    active = now_epoch < EVENT_END_EPOCH
    if not active and not found_count:
        return None
    return {"title": EVENT_TITLE, "ends_epoch": EVENT_END_EPOCH, "active": active,
            "found_count": found_count, "total": len(pets), "pets": pets}
