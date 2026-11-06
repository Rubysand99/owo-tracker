"""Luu moi tin cua bot NeonUtil trong kenh theo doi (de dung chung cho moi du an owo).

Ham THUAN (khong discord, khong DB) de test o bat ky dau. Bot chi DOC tin Neon dang cong khai trong kenh,
khong goi gi rieng toi Neon. Chua biet het dinh dang tin Neon nen luu NGUYEN VAN + phan loai so bo + cac dong "Nhan: gia tri"
tach san; khi da thay mau that thi viet parser rieng cho tung loai (xem `kind`).
"""
import re

RAW_MAX = 6000                      # toi da ky tu nguyen van luu moi tin
FIELDS_MAX = 40                     # toi da so cap "Nhan: gia tri" tach ra

_MD_RE = re.compile(r"[*_`~>#|]+")
_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
_MENTION_RE = re.compile(r"<@[!&]?\d+>|<#\d+>")
_ID_PAREN_RE = re.compile(r"\(\s*[A-Za-z0-9]{3,10}\s*\)")
_NUM_RE = re.compile(r"[\d.,%]+")
_KV_RE = re.compile(r"^[\s>*_`~#|-]*([A-Za-zÀ-ỹ][^:\n]{0,38}?)\s*:\s*\**\s*(.+?)\s*$")


def slug(s: str, words: int = 3, maxlen: int = 32) -> str:
    """'## Ruby's Bow ( ABCD1 )' -> 'ruby-s-bow'. Bo emoji, mention, ma ID trong ngoac, so, dau markdown."""
    t = _EMOJI_RE.sub(" ", s or "")
    t = _MENTION_RE.sub(" ", t)
    t = _ID_PAREN_RE.sub(" ", t)
    t = _NUM_RE.sub(" ", t)
    t = _MD_RE.sub(" ", t).lower()
    parts = re.findall(r"[a-zà-ỹ]+", t)[:words]
    return ("-".join(parts))[:maxlen]


def first_line(text: str) -> str:
    for ln in (text or "").splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def classify(text: str, known: str = "") -> str:
    """`known` = loai da nhan ra bang parser chuyen dung (vd 'weapon_breakdown'); khong thi doan theo dong dau tin."""
    if known:
        return known
    s = slug(first_line(text))
    return f"other:{s}" if s else "other"


def extract_fields(text: str) -> dict:
    """Cac dong 'Nhan: gia tri' (ke ca '**Nhan:** gia tri') -> dict. Nhan trung thi giu gia tri dau."""
    out = {}
    for ln in (text or "").splitlines():
        m = _KV_RE.match(ln)
        if not m:
            continue
        key = _MD_RE.sub("", m.group(1)).strip()
        val = _MD_RE.sub("", m.group(2)).strip()
        if key and val and key not in out:
            out[key] = val[:200]
            if len(out) >= FIELDS_MAX:
                break
    return out


def belongs_to_other(message, tracked_id) -> bool:
    """True = tin Neon nay la tra loi / ket qua lenh cua NGUOI KHAC (khong luu du lieu cua nguoi khac).
    Khong xac dinh duoc thi False (luu)."""
    if not tracked_id:
        return False
    tid = str(tracked_id)
    ref = getattr(message, "reference", None)
    resolved = getattr(ref, "resolved", None) if ref else None
    author = getattr(resolved, "author", None)
    if author is not None and str(getattr(author, "id", "")) != tid:
        return True
    for attr in ("interaction_metadata", "interaction"):
        meta = getattr(message, attr, None)
        user = getattr(meta, "user", None) if meta is not None else None
        if user is not None and getattr(user, "id", None) is not None:
            return str(user.id) != tid
    return False


def build_doc(text: str, *, kind: str, message_id, channel_id, command: str, at_iso: str, edited: bool = False) -> dict:
    body = text or ""
    return {
        "kind": kind,
        "title": first_line(body)[:120],
        "fields": extract_fields(body),
        "raw": body[:RAW_MAX],
        "raw_truncated": len(body) > RAW_MAX,
        "message_id": str(message_id),
        "channel_id": str(channel_id),
        "command": command or "",
        "edited": bool(edited),
        "at": at_iso,
    }


def summary_text(rows, total: int) -> str:
    """rows = [{'_id': kind, 'n': so tin, 'last': iso}] -> 1 doan chat de gui Discord."""
    if not rows:
        return "Chưa lưu tin NeonUtil nào. Gõ 1 lệnh Neon trong kênh farm rồi thử lại."
    lines = [f"**NeonUtil — đã lưu {total} tin, {len(rows)} loại**"]
    for r in rows[:25]:
        lines.append(f"• `{r['_id']}` ×{r['n']} (mới nhất {str(r.get('last') or '')[:16].replace('T', ' ')} UTC)")
    if len(rows) > 25:
        lines.append(f"… và {len(rows) - 25} loại nữa (dùng `,neon export`)")
    lines.append("`,neon show <loại>` xem mẫu · `,neon export [loại]` tải file · `,neon on|off` · `,neon clear`")
    return "\n".join(lines)
