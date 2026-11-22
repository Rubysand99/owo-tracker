"""new_pet.py — khi hunt ra pet MỚI (chưa có trong zoo): lệnh `owo dex <tên>` nhờ app gõ + nội dung DM báo tên/emoji. Hàm THUẦN để test."""
import re

import event_pets

MAX_PER_HUNT = 3    # 1 lần hunt tối đa ~3 loài; chặn cứng để dữ liệu lạ không đẻ ra cả loạt lệnh/DM
_DEX_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")   # khớp đúng danh sách cho phép `owo dex ...` của CommandGuard bên app


def dex_command(name):
    """`owo dex <tên>` cho tên emoji của pet; None nếu tên lạ (không an toàn để gõ vào Discord)."""
    n = str(name or "").strip()
    return f"owo dex {n}" if _DEX_NAME_RE.match(n) else None


def emoji_image_url(entry, size=96):
    """Ảnh emoji tuỳ chỉnh (để DM hiện hình chắc chắn, kể cả khi bot không dùng được emoji ngoài); None với emoji thường."""
    eid = str((entry or {}).get("emoji_id") or "")
    if not eid.isdigit():
        return None
    ext = "gif" if entry.get("emoji_animated") else "png"
    return f"https://cdn.discordapp.com/emojis/{eid}.{ext}?size={size}&quality=lossless"


def pick(names, animals):
    """Từ tên pet mới + danh sách thú trong tin hunt -> các mục (name, emoji_id, emoji_animated) theo thứ tự `names`,
    bỏ trùng, tối đa MAX_PER_HUNT."""
    by_name = {str(a.get("name", "")).lower(): a for a in animals or []}
    out, seen = [], set()
    for n in names or []:
        k = str(n).lower()
        if k in seen:
            continue
        seen.add(k)
        a = by_name.get(k, {})
        out.append({"name": a.get("name") or n, "emoji_id": a.get("emoji_id"), "emoji_animated": bool(a.get("emoji_animated"))})
    return out[:MAX_PER_HUNT]


def dm_text(entries, markup, dex_queued):
    """Nội dung DM. markup(entry) -> chuỗi emoji hiển thị; dex_queued: có xếp lệnh owo dex cho app không."""
    lines = []
    for e in entries:
        tag = " 🍂 **PET SỰ KIỆN!**" if event_pets.match_event_pet(e["name"]) else ""
        lines.append(f"{markup(e)} **{e['name']}**{tag}")
    head = "🆕 **Pet mới!**" if len(entries) == 1 else f"🆕 **{len(entries)} pet mới!**"
    text = head + "\n" + "\n".join(lines)
    if dex_queued:
        cmds = ", ".join(f"`{dex_command(e['name'])}`" for e in entries if dex_command(e["name"]))
        if cmds:
            text += f"\nApp sẽ gõ {cmds} để ghi nhận."
    return text
