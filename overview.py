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
    "gems": ["Gem đang dùng", "Gem dự phòng (số viên)", "Gem dự phòng (số loại)", "Gem thấp nhất (%)",
             "Gem cao nhất (%)", "Gem dưới 20%"],
    "zoo": ["Zoo Points", "Pet đang giữ", "Tổng đã bắt", "Loài đã mở khóa", "Loài đã hiến tế hết",
            "Loài đang có (theo bậc)", "Con đã hiến tế (theo bậc)", "Bậc nhiều pet nhất"],
    "dex": ["Loài đã tra owo dex", "Trong đó đang có", "Loài chưa có", "Tỉ lệ đang có", "Theo rank"],
    "inventory": ["Số loại đồ", "Tổng số món", "Số gem trong kho", "Món nhiều nhất"],
    "weapons": ["Vũ khí đã ghi nhận", "Vũ khí đã quét danh sách", "Đang đeo", "Đã gắn sao", "Có passive",
                "Chất lượng TB", "Chất lượng cao nhất", "Chất lượng thấp nhất", "Theo độ hiếm", "Theo loại"],
    "review": ["Đang duyệt", "Đã giữ", "Đã bỏ", "Còn lại", "Chưa rõ", "Chưa thấy"],
    "team": ["Số pet trong đội", "Tổng HP", "Tổng ATT", "Tổng PR", "Tổng WP", "Tổng MAG", "Tổng MR",
             "Level TB", "Level cao nhất", "Pet đang cầm vũ khí", "Chất lượng vũ khí TB"],
    "battle": ["Kết quả", "Số lượt", "XP", "Chuỗi thắng", "Chuỗi thắng cao nhất", "Chuỗi thua gần nhất"],
    "event": ["Pet sự kiện đã tìm", "Kết thúc", "Tiến độ săn sự kiện", "Tin sự kiện đã ghi"],
    "misc": ["Pet mới chưa vào zoo", "Lần bị OwO báo quá nhanh (30 phút)", "Captcha"],
    "checklist": ["Checklist Daily", "Checklist Weekly"],
    "knowledge": ["Loài pet đã biết", "Pet đã mở khóa (lưu vĩnh viễn)", "Loại vũ khí đã biết", "Passive đã biết",
                  "Emoji đã đăng ký", "Lần quan sát zoo", "Ghi chú", "Lệnh đang chờ app", "Pet sự kiện đã lưu"],
    "config": ["Hub (app)", "Tự kiểm tra", "Cảnh báo HuntBot", "Tự động HuntBot", "Chế độ Event", "Phiên bản bot"],
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


def _ints(values):
    return [v for v in values if isinstance(v, int) and not isinstance(v, bool)]


def _nums(values):
    return [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _top(counter_like, limit=6):
    """{"a": 3, "b": 1} -> "a ×3 · b ×1" (giảm dần theo số lượng)."""
    items = sorted(((k, v) for k, v in counter_like.items() if k), key=lambda kv: (-kv[1], str(kv[0])))
    if not items:
        return "—"
    shown = " · ".join(f"{k} ×{num(v)}" for k, v in items[:limit])
    return shown + (f" · +{len(items) - limit} loại khác" if len(items) > limit else "")


def summarize_weapon_rows(rows):
    """Tóm tắt kho vũ khí đã quét (COL_WEAPON_LIST). Hàm thuần; rows = list dict. Trả None nếu chưa quét."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return None
    q = _nums([r.get("quality") for r in rows])
    rar, typ = {}, {}
    for r in rows:
        if r.get("rarity"):
            rar[str(r["rarity"])] = rar.get(str(r["rarity"]), 0) + 1
        if r.get("type"):
            typ[str(r["type"])] = typ.get(str(r["type"]), 0) + 1
    return {"total": len(rows), "starred": sum(1 for r in rows if r.get("starred")),
            "equipped": sum(1 for r in rows if r.get("equipped")),
            "with_passive": sum(1 for r in rows if r.get("passives")),
            "q_avg": round(sum(q) / len(q), 1) if q else None, "q_max": max(q) if q else None,
            "q_min": min(q) if q else None, "by_rarity": rar, "by_type": typ}


def build_groups(hub, extras=None):
    """extras (tuỳ chọn, do bot gom từ DB): {"weapon_list": summarize_weapon_rows(...), "counts": {...}, "config": {...}}."""
    hub = hub or {}
    extras = extras or {}
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
    if gm:
        eq = _g(gm, "equipped") or []
        spare = _g(gm, "spare") or []
        pcts = _nums([e.get("percent") for e in eq if isinstance(e, dict)])
        gem_lines = [("Gem đang dùng", num(len(eq)))]
        for e in eq:
            gem_lines.append((f"Slot {e.get('type_name') or e.get('slot')} ({e.get('tier') or '?'})",
                              f"{num(e.get('current'))}/{num(e.get('max'))} ({e.get('percent', 0)}%)"))
        gem_lines += [
            ("Gem dự phòng (số viên)", num(sum((s_.get("count") or 0) for s_ in spare))),
            ("Gem dự phòng (số loại)", num(len(spare))),
            ("Gem thấp nhất (%)", f"{min(pcts)}%" if pcts else "—"),
            ("Gem cao nhất (%)", f"{max(pcts)}%" if pcts else "—"),
            ("Gem dưới 20%", num(sum(1 for x in pcts if x < 20)) if pcts else "—"),
        ]
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
    bt = _g(z, "by_tier") if z else None
    bt = bt if isinstance(bt, dict) else {}
    sp = _ints([v.get("species") for v in bt.values() if isinstance(v, dict)])
    sac = _ints([v.get("sacrificed") for v in bt.values() if isinstance(v, dict)])
    tot = {t: v.get("total") for t, v in bt.items() if isinstance(v, dict) and isinstance(v.get("total"), int)}
    top_t = max(tot, key=lambda t: tot[t]) if tot else None
    zoo_lines += [
        ("Loài đang có (theo bậc)", (num(sum(sp)) if sp else "—") if z else NO_DATA),
        ("Con đã hiến tế (theo bậc)", (num(sum(sac)) if sac else "—") if z else NO_DATA),
        ("Bậc nhiều pet nhất", (f"{top_t} ({num(tot[top_t])} con)" if top_t else "—") if z else NO_DATA),
    ]
    if z and _g(z, "by_tier"):
        tiers = " · ".join(f"{t} {num(v.get('species'))} loài/{num(v.get('total'))} con"
                           for t, v in z["by_tier"].items())
        zoo_lines.append(("Theo bậc", tiers))
    out.append(_group("zoo", "🐾 Zoo", z, zoo_lines))

    dx = hub.get("pet_dex")
    _dex_known, _dex_owned = _g(dx, "total_known"), _g(dx, "total_owned")
    _dex_known = _dex_known if isinstance(_dex_known, int) else None
    _dex_owned = _dex_owned if isinstance(_dex_owned, int) else None
    _dex_rank = {}
    for sp_ in (_g(dx, "species") or []):
        if isinstance(sp_, dict) and sp_.get("rank") and sp_.get("owned"):
            _dex_rank[str(sp_["rank"])] = _dex_rank.get(str(sp_["rank"]), 0) + 1
    out.append(_group("dex", "📖 Pet dex", dx, [
        ("Loài đã tra owo dex", num(_g(dx, "total_known")) if dx else NO_DATA),
        ("Trong đó đang có", num(_g(dx, "total_owned")) if dx else NO_DATA),
        ("Loài chưa có", (num(_dex_known - _dex_owned) if _dex_known is not None and _dex_owned is not None else "—") if dx else NO_DATA),
        ("Tỉ lệ đang có", (f"{round(100 * _dex_owned / _dex_known, 1)}%" if _dex_known and _dex_owned is not None else "—") if dx else NO_DATA),
        ("Theo rank", (_top(_dex_rank, 8) if _dex_rank else "—") if dx else NO_DATA),
    ]))

    inv = hub.get("inventory")
    _inv_items = [i for i in (_g(inv, "items") or []) if isinstance(i, dict) and isinstance(i.get("count"), int)]
    _inv_gems = sum(i["count"] for i in _inv_items if i.get("is_gem"))
    _inv_top = max(_inv_items, key=lambda i: i["count"]) if _inv_items else None
    out.append(_group("inventory", "🎒 Kho đồ", inv, [
        ("Số loại đồ", num(_g(inv, "kinds")) if inv else NO_DATA),
        ("Tổng số món", num(_g(inv, "total_items")) if inv else NO_DATA),
        ("Số gem trong kho", (num(_inv_gems) if _inv_items else "—") if inv else NO_DATA),
        ("Món nhiều nhất", (f"{_inv_top.get('name') or _inv_top.get('code')} ×{num(_inv_top.get('count'))}" if _inv_top else "—") if inv else NO_DATA),
    ]))

    w = hub.get("weapons")
    wl = extras.get("weapon_list")
    def _wl(key, fmt=num):
        return fmt(wl[key]) if wl and wl.get(key) is not None else ("—" if wl else NO_DATA)
    out.append(_group("weapons", "⚔️ Vũ khí", w, [
        ("Vũ khí đã ghi nhận", num(_g(w, "count")) if w else NO_DATA),
        ("Vũ khí đã quét danh sách", _wl("total")), ("Đang đeo", _wl("equipped")), ("Đã gắn sao", _wl("starred")),
        ("Có passive", _wl("with_passive")),
        ("Chất lượng TB", _wl("q_avg", lambda v: f"{v}%")), ("Chất lượng cao nhất", _wl("q_max", lambda v: f"{v}%")),
        ("Chất lượng thấp nhất", _wl("q_min", lambda v: f"{v}%")),
        ("Theo độ hiếm", _top(wl["by_rarity"]) if wl else NO_DATA), ("Theo loại", _top(wl["by_type"]) if wl else NO_DATA),
    ]))

    rv = hub.get("weapon_review")
    out.append(_group("review", "🗂️ Duyệt vũ khí (Giữ/Bỏ)", None, [
        ("Đang duyệt", yes_no(_g(rv, "active")) if rv else NO_DATA),
        ("Đã giữ", num(_g(rv, "kept")) if rv else NO_DATA), ("Đã bỏ", num(_g(rv, "dropped")) if rv else NO_DATA),
        ("Còn lại", num(_g(rv, "remaining")) if rv else NO_DATA),
        ("Chưa rõ", num(_g(rv, "unknown")) if rv else NO_DATA), ("Chưa thấy", num(_g(rv, "unseen")) if rv else NO_DATA),
    ]))

    t = hub.get("team")
    members = _g(t, "members") or []
    sums = {k: 0 for k in ("hp", "att", "pr", "wp", "mag", "mr")}
    for m in members:
        for k in sums:
            v = (m or {}).get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                sums[k] += v
    lv = _nums([(m or {}).get("level") for m in members])
    wq = _nums([(m or {}).get("quality") for m in members])
    armed = sum(1 for m in members if (m or {}).get("weaponId"))
    out.append(_group("team", "🛡️ Đội hình", t,
                      [("Số pet trong đội", num(len(members)) if t else NO_DATA)] +
                      [(f"Tổng {k.upper()}", num(v) if t else NO_DATA) for k, v in sums.items()] +
                      [("Level TB", (str(round(sum(lv) / len(lv), 1)) if lv else "—") if t else NO_DATA),
                       ("Level cao nhất", (num(max(lv)) if lv else "—") if t else NO_DATA),
                       ("Pet đang cầm vũ khí", num(armed) if t else NO_DATA),
                       ("Chất lượng vũ khí TB", (f"{round(sum(wq) / len(wq), 1)}%" if wq else "—") if t else NO_DATA)]))

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
    ev_lines = [("Pet sự kiện đã tìm", f"{_g(ep, 'found_count', 0)}/{_g(ep, 'total', 0)}" if ep else NO_DATA)]
    for p_ in (_g(ep, "pets") or []):
        if not isinstance(p_, dict):
            continue
        if p_.get("found"):
            when = ago(p_.get("age_seconds"))
            ev_lines.append((f"✅ {p_.get('label') or p_.get('key')}", f"đã tìm thấy" + (f" · lần cuối {when}" if when else "")))
        else:
            ev_lines.append((f"⬜ {p_.get('label') or p_.get('key')}", "chưa tìm thấy"))
    end = _g(ep, "ends_epoch")
    ev_lines.append(("Kết thúc", (f"<t:{end}:R>" if isinstance(end, int) else "—") if ep else NO_DATA))
    cs = [c for c in (_g(ev, "counters") or []) if isinstance(c, dict)]
    c0 = cs[0] if cs else None   # bản ghi mới nhất (hub đã sắp mới -> cũ); chỉ hiện 1 bộ đếm x/y
    ev_lines.append(("Tiến độ săn sự kiện", (f"{num(c0.get('current'))}/{num(c0.get('max'))}" if c0 else "—") if ev else NO_DATA))
    ev_lines.append(("Tin sự kiện đã ghi", num(len(_g(ev, "recent") or [])) if ev else NO_DATA))
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

    c = extras.get("counts") or {}
    def _c(key):
        return num(c[key]) if isinstance(c.get(key), int) else NO_DATA
    out.append({"key": "knowledge", "title": "🧠 Dữ liệu bot đã học", "age_seconds": None, "lines": [
        ("Loài pet đã biết", _c("species")), ("Pet đã mở khóa (lưu vĩnh viễn)", _c("unlocked")),
        ("Loại vũ khí đã biết", _c("weapon_types")), ("Passive đã biết", _c("passives")),
        ("Emoji đã đăng ký", _c("emoji")), ("Lần quan sát zoo", _c("zoo_history")), ("Ghi chú", _c("notes")),
        ("Lệnh đang chờ app", _c("pending_commands")), ("Pet sự kiện đã lưu", _c("event_pets"))]})

    cf = extras.get("config") or {}
    def _onoff(key):
        v = cf.get(key)
        return NO_DATA if v is None else ("BẬT" if v else "tắt")
    hub_on = None if cf.get("app_off") is None else (not cf.get("app_off"))
    out.append({"key": "config", "title": "⚙️ Cài đặt bot", "age_seconds": None, "lines": [
        ("Hub (app)", NO_DATA if hub_on is None else ("BẬT" if hub_on else "tắt (bot không giao việc)")),
        ("Tự kiểm tra", _onoff("auto_check")), ("Cảnh báo HuntBot", _onoff("hb_alert")),
        ("Tự động HuntBot", _onoff("hb_auto")),
        ("Chế độ Event", yes_no(hub.get("event_mode")) if hub.get("event_mode") is not None else NO_DATA),
        ("Phiên bản bot", str(hub.get("bot_version") or NO_DATA))]})
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
