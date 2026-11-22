"""stat_info.py — 6 chỉ số chiến đấu của OwO mà dự án theo dõi (pet / đội hình / vũ khí). Hàm THUẦN để test.

Khóa trong DB (hp, att, pr, wp, mag, mr) KHÔNG đổi: dùng ở owot_pet_species, owot_team_slots, /hub...
`label` là nhãn hiển thị trong bot; OwO gọi ATT là STR (xem _STAT_LABELS trong owo_parsers.py).
"""
STATS = (
    ("hp",  "HP",         "Máu",                   "Máu của pet; về 0 là bị hạ."),
    ("att", "ATT (STR)",  "Sát thương vật lý",     "Sức mạnh đòn đánh vật lý (OwO ghi là STR)."),
    ("pr",  "PR",         "Kháng vật lý",          "Giảm sát thương vật lý nhận vào."),
    ("wp",  "WP",         "Weapon Points",         "Điểm dùng kỹ năng của vũ khí (như mana)."),
    ("mag", "MAG",        "Sát thương phép",       "Sức mạnh đòn phép."),
    ("mr",  "MR",         "Kháng phép",            "Giảm sát thương phép nhận vào."),
)
STAT_KEYS = tuple(s[0] for s in STATS)


def team_totals(rows):
    """Tổng từng chỉ số của đội hình (bỏ qua giá trị thiếu / không phải số). Trả về (tổng, số_pet_có_đủ_dữ_liệu_ít_nhất_1_chỉ_số)."""
    totals = {k: 0 for k in STAT_KEYS}
    seen = 0
    for r in rows or []:
        got = False
        for k in STAT_KEYS:
            v = (r or {}).get(k)
            if isinstance(v, int) and not isinstance(v, bool):
                totals[k] += v
                got = True
        seen += 1 if got else 0
    return totals, seen


def embed_fields(rows):
    """[(tên, nội dung, inline)] cho embed `,stats`: 6 chỉ số + tổng đội hình (nếu bot đã đọc được đội hình)."""
    fields = [(f"{label} — {vi}", note, True) for _k, label, vi, note in STATS]
    totals, n = team_totals(rows)
    if n:
        line = " · ".join(f"{label.split()[0]} **{totals[k]:,}**" for k, label, _vi, _n in STATS)
        fields.append((f"Tổng đội hình hiện tại ({n} pet)", line, False))
    else:
        fields.append(("Tổng đội hình hiện tại", "Chưa có dữ liệu đội hình — gõ `owo team` trong kênh có bot.", False))
    fields.append(("Xem chỉ số ở đâu", "`,pet <tên>` chỉ số 1 loài · `,team` đội hình · `,petset` nhập tay chỉ số pet", False))
    return fields
