"""overview.py — gom MỌI số liệu thống kê bot đang theo dõi thành các mục cho 1 lệnh `,thongke` (embed). Hàm THUẦN, test trực tiếp.

Đầu vào là dict của `build_hub()` (cùng dữ liệu app Hub đang dùng): mục nào bot chưa từng thấy = None -> hiện "chưa có dữ liệu".
Mỗi mục: {"title", "age_seconds", "lines": [(nhãn, giá trị)]}. Các dòng CỐ ĐỊNH (luôn có nhãn) được liệt kê ở FIXED_LABELS;
một số mục có thêm dòng THAY ĐỔI theo dữ liệu (từng slot gem, từng bậc zoo, từng bộ đếm sự kiện).
"""
NO_DATA = "chưa có dữ liệu"
EMBED_CHAR_BUDGET = 5500       # Discord giới hạn 6000 ký tự / embed: chừa chỗ cho tiêu đề + chân trang
EMBED_MAX_FIELDS = 25
FIELD_MAX = 1000               # Discord: 1024 ký tự / mục

# Nhãn dòng cố định theo mục (dùng để đếm "có bao nhiêu thông số" và để test không bỏ sót)
FIXED_LABELS = {
    "cowoncy": ["Cowoncy", "Weapon shards"],
    "daily": ["Trạng thái", "Chuỗi ngày", "Thưởng gần nhất", "Nhận lại sau"],
    "huntbot": ["Đang hunt", "Tiến độ", "Pet đã bắt", "Essence", "Còn lại"],
    "quest": ["Seals", "Xong hết hôm nay", "Quest kế tiếp", "Số quest"],
    "gems": ["Gem đang dùng", "Gem dự phòng (số viên)", "Gem dự phòng (số loại)"],
    "zoo": ["Zoo Points", "Pet đang giữ", "Tổng đã bắt", "Loài đã mở khóa", "Loài đã hiến tế hết"],
    "dex": ["Loài đã tra owo dex", "Trong đó đang có"],
    "inventory": ["Số loại đồ", "Tổng số món"],
    "weapons": ["Vũ khí đã ghi nhận"],
    "team": ["Số pet trong đội", "Tổng HP", "Tổng ATT", "Tổng PR", "Tổng WP", "Tổng MAG", "Tổng MR"],
    "battle": ["Kết quả", "Số lượt", "XP", "Chuỗi thắng", "Chuỗi thắng cao nhất", "Chuỗi thua gần nhất"],
    "event": ["Pet sự kiện đã tìm", "Nhật ký sự kiện gần đây"],
    "misc": ["Pet mới chưa vào zoo", "Lần bị OwO báo quá nhanh (30 phút)", "Captcha"],
    "checklist": ["Checklist Daily", "Checklist Weekly"],
}
FIXED_COUNT = sum(len(v) for v in FIXED_LABELS.values())


def num(v):
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else (str(v) if v is not None else "—")


def yes_no(v):
    return "—" if v is None else ("Có" if v else "Không")


def ago(sec):
    if sec is None:
        return ""
    s = int(sec)
    if s < 60:
        return "vừa xong"
    if s < 3600:
        return f"{s // 60} phút trước"
    if s < 86400:
        return f"{s // 3600} giờ trước"
    return f"{s // 86400} ngày trước"


def left(sec):
    """Thời gian còn lại dạng 1h05m / 12m / 30s."""
    if sec is None:
        return "—"
    s = max(0, int(sec))
    h, rem = divmod(s, 3600)
    m, sc = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m" if m else f"{sc}s"


def _g(d, key, default=None):
    return d.get(key, default) if isinstance(d, dict) else default


def _group(key, title, section, lines):
    age = _g(section, "age_seconds")
    return {"key": key, "title": title, "age_seconds": age, "lines": lines}


def build_groups(hub):
    hub = hub or {}
    out = []

    cw, ws = hub.get("cowoncy"), hub.get("weapon_shards")
    out.append(_group("cowoncy", "💰 Tiền & vật phẩm hiếm", cw,
                      [("Cowoncy", num(_g(cw, "amount")) if cw else NO_DATA),
                       ("Weapon shards", num(_g(ws, "amount")) if ws else NO_DATA)]))

    d = hub.get("daily")
    out.append(_group("daily", "📅 Daily", d, [
        ("Trạng thái", str(_g(d, "state") or "—") if d else NO_DATA),
        ("Chuỗi ngày", num(_g(d, "streak")) if d else NO_DATA),
        ("Thưởng gần nhất", num(_g(d, "last_reward")) if d else NO_DATA),
        ("Nhận lại sau", left(_g(d, "seconds_left")) if d and _g(d, "seconds_left") is not None else "—"),
    ]))

    h = hub.get("huntbot")
    out.append(_group("huntbot", "🤖 HuntBot", h, [
        ("Đang hunt", yes_no(_g(h, "hunting")) if h else NO_DATA),
        ("Tiến độ", f"{_g(h, 'progress_pct')}%" if h and _g(h, "progress_pct") is not None else "—"),
        ("Pet đã bắt", num(_g(h, "animals_captured")) if h else NO_DATA),
        ("Essence", num(_g(h, "essence")) if h else NO_DATA),
        ("Còn lại", (left(_g(h, "seconds_left")) if _g(h, "seconds_left") is not None else str(_g(h, "time_remaining_text") or "—")) if h else NO_DATA),
    ]))

    q = hub.get("quest")
    next_q = (left(_g(q, "next_quest_seconds")) if _g(q, "next_quest_seconds") is not None else str(_g(q, "next_quest") or "—")) if q else NO_DATA
    out.append(_group("quest", "📜 Quest", q, [
        ("Seals", num(_g(q, "seals")) if q else NO_DATA),
        ("Xong hết hôm nay", yes_no(_g(q, "all_done")) if q else NO_DATA),
        ("Quest kế tiếp", next_q),
        ("Số quest", num(len(_g(q, "quests") or [])) if q else NO_DATA),
    ]))

    gm = hub.get("gems")
    gem_lines = []
    if gm:
        for e in _g(gm, "equipped") or []:
            gem_lines.append((f"Slot {e.get('type_name') or e.get('slot')} ({e.get('tier') or '?'})",
                              f"{num(e.get('current'))}/{num(e.get('max'))} ({e.get('percent', 0)}%)"))
        spare = _g(gm, "spare") or []
        gem_lines.append(("Gem dự phòng (số viên)", num(sum((s.get("count") or 0) for s in spare))))
        gem_lines.append(("Gem dự phòng (số loại)", num(len(spare))))
        gem_lines.insert(0, ("Gem đang dùng", num(len(_g(gm, "equipped") or []))))
    else:
        gem_lines = [(lbl, NO_DATA) for lbl in FIXED_LABELS["gems"]]
    out.append(_group("gems", "💎 Gem", gm, gem_lines))

    z = hub.get("zoo")
    zoo_lines = [
        ("Zoo Points", num(_g(z, "zoo_points")) if z else NO_DATA),
        ("Pet đang giữ", num(_g(z, "total_pets")) if z else NO_DATA),
        ("Tổng đã bắt", num(_g(z, "caught_total")) if z else NO_DATA),
        ("Loài đã mở khóa", num(_g(z, "unlocked_total")) if z else NO_DATA),
        ("Loài đã hiến tế hết", num(len(_g(z, "sacrificed_pets") or [])) if z else NO_DATA),
    ]
    if z and _g(z, "by_tier"):
        tiers = " · ".join(f"{t} {num(v.get('species'))} loài/{num(v.get('total'))} con"
                           for t, v in z["by_tier"].items())
        zoo_lines.append(("Theo bậc", tiers))
    out.append(_group("zoo", "🐾 Zoo", z, zoo_lines))

    dx = hub.get("pet_dex")
    out.append(_group("dex", "📖 Pet dex", dx, [
        ("Loài đã tra owo dex", num(_g(dx, "total_known")) if dx else NO_DATA),
        ("Trong đó đang có", num(_g(dx, "total_owned")) if dx else NO_DATA),
    ]))

    inv = hub.get("inventory")
    out.append(_group("inventory", "🎒 Kho đồ", inv, [
        ("Số loại đồ", num(_g(inv, "kinds")) if inv else NO_DATA),
        ("Tổng số món", num(_g(inv, "total_items")) if inv else NO_DATA),
    ]))

    w = hub.get("weapons")
    out.append(_group("weapons", "⚔️ Vũ khí", w, [("Vũ khí đã ghi nhận", num(_g(w, "count")) if w else NO_DATA)]))

    t = hub.get("team")
    members = _g(t, "members") or []
    sums = {k: 0 for k in ("hp", "att", "pr", "wp", "mag", "mr")}
    for m in members:
        for k in sums:
            v = (m or {}).get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                sums[k] += v
    out.append(_group("team", "🛡️ Đội hình", t,
                      [("Số pet trong đội", num(len(members)) if t else NO_DATA)] +
                      [(f"Tổng {k.upper()}", num(v) if t else NO_DATA) for k, v in sums.items()]))

    b = hub.get("battle")
    out.append(_group("battle", "🥊 Battle gần nhất", b, [
        ("Kết quả", str(_g(b, "result") or "—") if b else NO_DATA),
        ("Số lượt", num(_g(b, "turns")) if b else NO_DATA),
        ("XP", num(_g(b, "xp")) if b else NO_DATA),
        ("Chuỗi thắng", num(_g(b, "streak")) if b else NO_DATA),
        ("Chuỗi thắng cao nhất", num(_g(b, "best_streak")) if b else NO_DATA),
        ("Chuỗi thua gần nhất", num(_g(b, "last_lost_streak")) if b else NO_DATA),
    ]))

    ev, ep = hub.get("event"), hub.get("event_pets")
    ev_lines = []
    for c in _g(ev, "counters") or []:
        ev_lines.append((f"Bộ đếm {c.get('kind') or '?'}", f"{num(c.get('current'))}/{num(c.get('max'))}"))
    ev_lines.append(("Pet sự kiện đã tìm", f"{_g(ep, 'found_count', 0)}/{_g(ep, 'total', 0)}" if ep else NO_DATA))
    ev_lines.append(("Nhật ký sự kiện gần đây", num(len(_g(ev, "recent") or [])) if ev else NO_DATA))
    out.append(_group("event", "🍂 Sự kiện", ev, ev_lines))

    npets = _g(hub.get("new_pets"), "pets")
    sd = hub.get("slowdown")
    cap = hub.get("captcha")
    out.append({"key": "misc", "title": "📡 Khác", "age_seconds": None, "lines": [
        ("Pet mới chưa vào zoo", num(len(npets)) if npets is not None else NO_DATA),
        ("Lần bị OwO báo quá nhanh (30 phút)", num(_g(sd, "count_30m")) if sd else "0"),
        ("Captcha", ("ĐANG CHỜ giải" if _g(cap, "active") else "không") if cap else NO_DATA),
    ]})

    cl = hub.get("checklists") or {}
    def _cl(kind):
        c = cl.get(kind)
        if not c:
            return NO_DATA
        p = c.get("progress")
        return str(p) if isinstance(p, (str, int)) and not isinstance(p, bool) else "đã ghi nhận"
    out.append({"key": "checklist", "title": "✅ Checklist Quest Log", "age_seconds": None, "lines": [
        ("Checklist Daily", _cl("daily")), ("Checklist Weekly", _cl("weekly"))]})
    return out


def count_metrics(groups):
    """(tổng số dòng, số dòng đã có dữ liệu thật — "chưa có dữ liệu" và "—" không tính)."""
    total = sum(len(g["lines"]) for g in groups)
    filled = sum(1 for g in groups for _l, v in g["lines"] if v not in (NO_DATA, "—"))
    return total, filled


def embed_fields(groups):
    """[(tên mục, nội dung)] — mỗi nhóm 1 mục; nội dung cắt ≤ FIELD_MAX ký tự."""
    fields = []
    for g in groups:
        title = g["title"] + (f" · {ago(g['age_seconds'])}" if g.get("age_seconds") is not None else "")
        body = "\n".join(f"{label}: **{val}**" if val != NO_DATA else f"{label}: _{val}_" for label, val in g["lines"])
        if len(body) > FIELD_MAX:
            body = body[:FIELD_MAX - 1] + "…"
        fields.append((title[:256], body))
    return fields


def chunk_fields(fields):
    """Chia mục thành nhiều embed để không vượt 25 mục / ~5500 ký tự mỗi embed."""
    chunks, cur, size = [], [], 0
    for name, value in fields:
        add = len(name) + len(value)
        if cur and (len(cur) >= EMBED_MAX_FIELDS or size + add > EMBED_CHAR_BUDGET):
            chunks.append(cur)
            cur, size = [], 0
        cur.append((name, value))
        size += add
    if cur:
        chunks.append(cur)
    return chunks
