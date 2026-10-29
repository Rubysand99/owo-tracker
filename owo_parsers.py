"""owo_parsers.py — các hàm đọc/phân tích tin nhắn OwO (thuần, không đụng DB hay Discord).

Tách ra từ owo_tracker_bot.py để dễ test và dễ sửa. owo_tracker_bot.py import lại
toàn bộ tên ở đây nên code cũ và test cũ (b.parse_xxx) vẫn chạy như trước.
"""
import os
import re
import json
from datetime import datetime


# ----------------------------------------------------------------------
# PARSE — hàm thuần (không đụng DB/Discord), test độc lập qua
# test_parsers.py. Regex viết dựa theo ảnh chụp màn hình bạn từng gửi —
# đã test khớp mẫu thật, nhưng vẫn nên tự kiểm chứng bằng ,debugnext
# trước khi tin tưởng hoàn toàn (xem README).
# ----------------------------------------------------------------------
RANK_VI = {
    "common": "Phổ thông", "uncommon": "Không phổ biến", "rare": "Hiếm",
    "epic": "Sử thi", "mythical": "Thần thoại", "legendary": "Huyền thoại",
    "special": "Đặc biệt", "patreon": "Patreon", "gem": "Đá quý",
    "fabled": "Huyền tích", "bot": "Robot", "distorted": "Dị biến", "hidden": "Ẩn giấu",
}


def parse_owodex(text: str):
    count_m = re.search(r"\*\*Count:\*\*\s*(\S+)", text)
    rank_m = re.search(r"\*\*Rank:\*\*\s*([a-zA-Z ]+)", text)
    alias_m = re.search(r"\*\*Alias:\*\*\s*([^\n]+)", text)
    rarity_m = re.search(r"\*\*Rarity:\*\*\s*([\d,]+)\s*total caught", text)
    points_m = re.search(r"\*\*Points:\*\*\s*(\d+)", text)
    sell_m = re.search(r"\*\*Sell:\*\*\s*(\d+)\s*Cowoncy\s*\|\s*(\d+)\s*sold", text)
    sac_m = re.search(r"\*\*Sacrifice:\*\*\s*(\d+)\s*Essence\s*\|\s*(\d+)\s*killed", text)
    # Flavor text: dòng in nghiêng (*...*) ở đầu tin nhắn, trước **Count:**
    flavor_m = re.search(r"^\*([^*]+)\*", text.strip())

    nums = re.findall(r"`(\d+)`", text)
    if len(nums) < 6 or not alias_m:
        return None
    aliases = [a.strip() for a in alias_m.group(1).split(",") if a.strip()]
    name = aliases[0] if aliases else ""
    if not name:
        return None

    rank_raw = rank_m.group(1).strip().lower() if rank_m else ""
    return {
        "name": name,
        "aliases": aliases,
        "rank": rank_raw.capitalize(),
        "rank_vi": RANK_VI.get(rank_raw),
        "stats": [int(n) for n in nums[:6]],
        "count": count_m.group(1) if count_m else "",
        "flavor_text": flavor_m.group(1).strip() if flavor_m else None,
        "rarity_caught": rarity_m.group(1) if rarity_m else None,
        "points": int(points_m.group(1)) if points_m else None,
        # None khi pet không bán/hy sinh được (OwO hiện "???" thay vì số)
        "sell_cowoncy": int(sell_m.group(1)) if sell_m else None,
        "sell_sold_count": int(sell_m.group(2)) if sell_m else None,
        "sacrifice_essence": int(sac_m.group(1)) if sac_m else None,
        "sacrifice_killed_count": int(sac_m.group(2)) if sac_m else None,
    }


def clean_owner_name(raw):
    """Bo emoji (<:x:123>, :x:) khoi ten chu vu khi, chi giu ten nguoi choi."""
    cleaned = re.sub(r"<a?:\w+:\d+>|:\w+:", "", raw or "")
    return cleaned.strip()


def parse_weapon_detail(text: str):
    """Trả về dict gồm: loại vũ khí, ID, quality, mô tả chính, các hiệu
    ứng cố định thuộc về loại vũ khí (vd Mortality/Taunt), và passive
    roll THẬT.

    QUAN TRỌNG: 1 tin nhắn owo weapon có thể chứa NHIỀU khối dạng
    "__Tên__ - mô tả" — vừa hiệu ứng cố định của vũ khí (vd Mortality
    trên mọi cây Culling Scythe), vừa passive ngẫu nhiên roll được (vd
    Giant Slayer). Đã kiểm chứng với mẫu thật: passive roll LUÔN là
    khối CUỐI CÙNG xuất hiện trong tin nhắn — các khối trước đó thuộc
    về chính loại vũ khí, không phải passive ngẫu nhiên."""
    name_m = re.search(r"##.*?'s\s+(.+)", text)
    owner_m = re.search(r"##\s*(.*?)'s\s+", text)
    id_m = re.search(r"\*\*ID:\*\*\s*`([A-Z0-9]+)`", text)
    quality_m = re.search(r"\*\*Quality:\*\*.*?(\d+(?:\.\d+)?)%", text)
    main_desc_m = re.search(r"((?:Deals?\s+[\d.]+%|At the start of the turn,)[^\n]+)", text)

    if not (name_m and id_m):
        return None

    # Bỏ hậu tố số lần kill OwO gắn thêm vào tên (vd "Culling Scythe [2]")
    # — nếu không, cùng 1 loại vũ khí sẽ bị lưu thành nhiều bản ghi khác
    # nhau chỉ vì số kill khác nhau.
    type_name = re.sub(r"\s*\[\d+\]\s*$", "", name_m.group(1).strip())

    blocks = re.findall(r"__([A-Za-z ]+)__\*{0,2}\s*-\s*([^\n]+)", text)
    roll_passive = None
    inherent_effects = []
    if blocks:
        roll_passive = {"name": blocks[-1][0].strip(), "desc": blocks[-1][1].strip()}
        inherent_effects = [{"name": n.strip(), "desc": d.strip()} for n, d in blocks[:-1]]

    effects = []
    for em in re.finditer(r"<a?:(\w+):\d+>\s*\*\*__([^_*\n]+?)__\*\*\s*-\s*([^\n]+)", text):
        ebase, ename, edesc = em.group(1), em.group(2).strip(), em.group(3).strip()
        norm = re.sub(r"[^a-z]", "", ename.lower())
        key = ebase if _is_subsequence(ebase.lower(), norm) else strip_rarity(ebase)   # 'flame' giu nguyen, 'lmanatap' -> 'manatap'
        effects.append({"emoji": ebase, "key": key, "name": ename, "desc": edesc})
    cost_m = re.search(r"\*\*Weapon Cost:\*\*\s*(\d+)", text)
    sell_m = re.search(r"\*\*Sell Value:\*\*\s*<[^>]+>\s*([\d,]+)\s*/\s*<[^>]+>\s*([\d,]+)", text)
    rar_m = re.search(r"\*\*Quality:\*\*\s*<a?:(\w+):\d+>", text)
    wear_m = re.search(r"\*\*Wear:\*\*\s*`?(\w+)`?", text)
    return {
        "effects": effects,
        "wp_cost": int(cost_m.group(1)) if cost_m else None,
        "sell_cowoncy": int(sell_m.group(1).replace(",", "")) if sell_m else None,
        "sell_ws": int(sell_m.group(2).replace(",", "")) if sell_m else None,   # so ws nhan duoc khi dismantle
        "rarity": rar_m.group(1) if rar_m else None,
        "wear": wear_m.group(1) if wear_m else None,
        "type_name": type_name,
        # Chu so huu ghi o tieu de ("## Ruby's Culling Scythe") — bo emoji/ky hieu, chi lay ten
        "owner": clean_owner_name(owner_m.group(1)) if owner_m else None,
        "id": id_m.group(1).strip(),
        "quality": float(quality_m.group(1)) if quality_m else None,
        "main_desc": main_desc_m.group(1).strip() if main_desc_m else None,
        "inherent_effects": inherent_effects,
        "passive": roll_passive,
    }


def emoji_to_name(raw):
    """Chuoi emoji cua Discord -> ten that. "<a:slothbot:711772997320441897>" -> "slothbot";
    ":dragon:" -> "dragon". Khong co emoji thi giu nguyen chu."""
    raw = (raw or "").strip()
    m = re.search(r"<a?:([A-Za-z0-9_]+):\d+>", raw)
    if m:
        return m.group(1)
    m = re.search(r":([A-Za-z0-9_]+):", raw)
    if m:
        return m.group(1)
    return raw


def parse_team(text: str):
    blocks = re.split(r"\[\d+\]\s*", text)[1:]
    result = []
    for i, block in enumerate(blocks, start=1):
        name_m = re.match(r"\s*([^\n]+)", block)
        lvl_m = re.search(r"Lvl\s*(\d+)", block)
        weapon_m = re.search(r"`([A-Z0-9]{6})`", block)
        quality_m = re.search(r"`[A-Z0-9]{6}`.*?(\d+(?:\.\d+)?)%", block)
        if not name_m:
            continue
        # Cô lập vùng chứa 6 số liệu — bỏ dòng Lvl+thanh XP ở đầu, bỏ
        # mọi thứ từ weapon ID trở đi ở cuối (tránh nhầm số trong ID
        # hoặc decimal của % quality với HP/WP/ATT/MAG/PR/MR).
        # BỎ CẢ emoji tuỳ chỉnh (<a:slothbot:711772997320441897>): ID emoji là
        # dãy số ~18 chữ số, nếu để lọt vào sẽ bị đọc nhầm thành HP.
        stat_zone = re.sub(r"<a?:\w+:\d+>", "", block)
        stat_zone = re.sub(r"Lvl\s*\d+\s*\[[\d,/]+\]", "", stat_zone)
        stat_zone = re.sub(r"`[A-Z0-9]{6}`.*", "", stat_zone, flags=re.S)
        nums = re.findall(r"(\d+)%?", stat_zone)
        pet_id, pet_animated = None, False
        emoji_m = re.match(r"\s*<(a)?:(\w+):(\d+)>", block)
        if emoji_m:
            pet_animated, pet_id = bool(emoji_m.group(1)), emoji_m.group(3)
        # dong vu khi: `ID` <:epic:..> <:eshield:..> <:rsac:..> 71.5% -> do hiem, loai (chu cai do hiem + ten loai), passive
        wline = re.search(r"`[A-Z0-9]{6}`([^\n]*)", block)
        wemojis = re.findall(r"<a?:(\w+):\d+>", wline.group(1)) if wline else []
        entry_weapon = {
            "weapon_rarity": wemojis[0] if len(wemojis) >= 1 else None,
            "weapon_emoji": wemojis[1] if len(wemojis) >= 2 else None,
            "passive_emojis": wemojis[2:],
        }
        entry = {
            **entry_weapon,
            "pos": i, "name": emoji_to_name(name_m.group(1)),
            "emoji_id": pet_id, "emoji_animated": pet_animated,
            "level": int(lvl_m.group(1)) if lvl_m else None,
            "weaponId": weapon_m.group(1) if weapon_m else None,
            "quality": float(quality_m.group(1)) if quality_m else None,
        }
        # Dinh dang HIEN TAI cua OwO: <:hp:ID> `1130` <:wp:ID> `1060` ... — moi so dung ngay sau
        # emoji ten chi so. Doc theo NHAN nen khong bao gio lech (so cu tung doc nham Lvl thanh HP).
        labeled = {}
        for lm in re.finditer(r"<a?:(hp|wp|att|mag|pr|mr):\d+>\s*`?([\d,]+)%?`?", block):
            labeled.setdefault(lm.group(1), int(lm.group(2).replace(",", "")))
        if len(labeled) == 6:
            entry.update(labeled)
        elif len(nums) >= 6:  # dinh dang cu (khong co emoji nhan): so xep theo thu tu
            entry.update({"hp": int(nums[0]), "wp": int(nums[1]), "att": int(nums[2]),
                          "mag": int(nums[3]), "pr": int(nums[4]), "mr": int(nums[5])})
        result.append(entry)
    return result


def parse_huntbot_status(text: str):
    up = text.upper()
    # OwO tra 2 tin cho `owo hb`: trang thong tin (co chu HUNTBOT) va tin trang thai
    # ("I AM STILL HUNTING... BACK IN 19H 41M") KHONG co chu HUNTBOT -> truoc day tin trang thai bi bo sot.
    # Tin nhan ve ("I AM BACK WITH ...") cung la tin trang thai.
    if not ("HUNTBOT" in up or "STILL HUNTING" in up or "I WILL BE BACK IN" in up
            or "ANIMALS CAPTURED" in up or "I AM BACK WITH" in up):
        return None
    # Bo emoji tuy chinh (<:ten:ID>) truoc khi tim so: ID emoji la 1 day so dai
    # ~19 chu so, neu de lot vao se bi doc nham thanh so essence.
    essence_line = next((ln for ln in text.split("\n") if "Animal Essence" in ln), "")
    essence_line = re.sub(r"<a?:\w+:\d+>", "", essence_line)
    essence_m = re.search(r"Animal Essence\D*?(\d[\d,]*)", essence_line)
    hunting = "STILL HUNTING" in text.upper() or "currently hunting" in text.lower()
    progress_m = re.search(r"([\d.]+)%\s*DONE", text.upper())
    animals_m = re.search(r"([\d,]+)\s*ANIMALS CAPTURED", text.upper())
    time_m = re.search(r"BACK IN\s*([0-9HMhm ]+)", text.upper())
    # Trang thong tin huntbot co cac chi so nang cap, moi dong dang:
    #   **⏱️ Efficiency - `218/H`:** `Lvl 193 [17866/99787]`
    traits = {}
    for name, lvl in re.findall(
            r"\*\*[^*\n]*?\b(Efficiency|Duration|Cost|Gain|Experience|Radar)\b[^*\n]*\*\*\s*`?\s*Lvl\s*(\d+)",
            text, re.I):
        traits[name.lower()] = int(lvl)
    # v29: OwO nay gop thong tin + trang thai vao 1 tin. Co chu trang thai thi "status_seen" = True
    status_seen = any(k in up for k in ("STILL HUNTING", "I WILL BE BACK IN", "ANIMALS CAPTURED",
                                        "I AM BACK WITH", "CURRENTLY HUNTING"))
    return {
        "traits": traits or None,
        "essence": int(essence_m.group(1).replace(",", "")) if essence_m else None,
        "status_seen": status_seen,
        "hunting": hunting,
        "progress_pct": float(progress_m.group(1)) if progress_m else None,
        "animals_captured": int(animals_m.group(1).replace(",", "")) if animals_m else None,
        "time_remaining": time_m.group(1).strip() if time_m else None,
    }


def parse_quest_items(text: str):
    """Doc tung quest trong Quest Log. Moi quest (mau that lay tu log Railway):

        <:blank_box:...> **1. <:common:...> ⚔️ Battle**
        > Battle 10 times!
        > Reward: <:cowoncy:...> +120  •  <:seal:...> +12
        ▰▱▱▱▱▱▱▱▱▱ `1/10`

    Dong "-# ..." (chan trang, vd Next quest) la het danh sach quest.
    Xong 1 quest = tien do dat toi da (khong dua vao icon o vuong vi chua biet
    icon 'da xong' trong nhu the nao)."""
    quests = []
    cur = None
    for line in text.split("\n"):
        head = re.search(r"\*\*(\d+)\.\s*(.+?)\*\*", line)
        if head:
            if cur:
                quests.append(cur)
            raw_title = head.group(2)
            rarity_m = re.search(r"<a?:(\w+):\d+>", raw_title)
            title = re.sub(r"<a?:\w+:\d+>", "", raw_title)
            title = re.sub(r"^[^\w]+", "", title).strip()  # bo emoji dung dau ten
            cur = {"index": int(head.group(1)), "title": title,
                   "rarity": rarity_m.group(1) if rarity_m else None,
                   "description": None, "rewards": [], "current": None, "max": None}
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if stripped.startswith("-#"):
            quests.append(cur)
            cur = None
            continue
        if stripped.startswith(">"):
            body = stripped.lstrip("> ").strip()
            if re.match(r"reward:", body, re.I):
                for part in body.split("•"):
                    amt = re.search(r"\+\s*([\d,]+)", part)
                    if not amt:
                        continue
                    name_m = re.search(r"<a?:(\w+):\d+>", part)
                    leftover = re.sub(r"reward:|\+\s*[\d,]+|<a?:\w+:\d+>", "", part, flags=re.I).strip()
                    cur["rewards"].append({"item": name_m.group(1) if name_m else (leftover or "?"),
                                           "amount": int(amt.group(1).replace(",", ""))})
            else:
                cur["description"] = body if cur["description"] is None else cur["description"] + " " + body
            continue
        prog = re.search(r"`\s*([\d,]+)\s*/\s*([\d,]+)\s*`", stripped)
        if prog:
            cur["current"] = int(prog.group(1).replace(",", ""))
            cur["max"] = int(prog.group(2).replace(",", ""))
    if cur:
        quests.append(cur)
    for q in quests:
        q["done"] = q["current"] is not None and q["max"] is not None and q["current"] >= q["max"]
    return quests


def parse_quest_status(text: str):
    if "Quest Log" not in text and "Quest Seals" not in text:
        return None
    seals_m = re.search(r"Balance:\s*\**\s*(\d+)", text)
    all_done = "finished all" in text.lower() or "come back tomorrow" in text.lower()
    next_m = re.search(r"Next quest:\s*([^\n]+)", text)
    result = {
        "seals": int(seals_m.group(1)) if seals_m else None,
        "all_done": all_done,
        "next_quest": next_m.group(1).strip() if next_m else None,
    }
    # Discord hien "3 gio toi" la do CLIENT doi moc thoi gian <t:1234567890:R>
    # thanh chu — tin nhan that ma bot doc duoc chua moc do, khong phai chu.
    ts_m = re.search(r"<t:(\d+)(?::[A-Za-z])?>", next_m.group(1)) if next_m else None
    if ts_m:
        result["next_quest_epoch"] = int(ts_m.group(1))
    quests = parse_quest_items(text)
    if quests:
        result["quests"] = quests
    return result


# --- Checklist Daily / Weekly (tab trong Quest Log) -------------------------
_CHECK_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


_CHECK_ITEM_RE = re.compile(r"^(.*?)\s*`?\s*(\d+)\s*/\s*(\d+)\s*`?\s*$")


def parse_checklist(text: str):
    """Tab Daily/Weekly cua owo quest. Moi viec 1 dong, vd: `✅ 📦 Find 3 Lootboxes `3/3``, cuoi co dong
    `Daily Progress `4/6``. Chi dua vao cum so cur/max cuoi dong nen khong phu thuoc kieu o tick."""
    low = (text or "").lower()
    if "daily checklist" in low:
        kind = "daily"
    elif "weekly checklist" in low:
        kind = "weekly"
    else:
        return None
    items, progress = [], None
    for raw_line in (text or "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if "progress" in line.lower():
            pm = re.search(r"(\d+)\s*/\s*(\d+)", line)
            if pm:
                progress = {"cur": int(pm.group(1)), "max": int(pm.group(2))}
            continue
        if "resets" in line.lower() or "balance" in line.lower():
            continue
        m = _CHECK_ITEM_RE.match(line)
        if not m:
            continue
        name = _CHECK_EMOJI_RE.sub("", m.group(1))
        name = re.sub(r"[`*_]", "", name)
        name = re.sub(r"^[^\w]+", "", name).strip()      # bo o tick / emoji dau dong
        if not name:
            continue
        cur, mx = int(m.group(2)), int(m.group(3))
        items.append({"name": name, "cur": cur, "max": mx, "done": cur >= mx})
    if not items:
        return None
    result = {"kind": kind, "items": items, "progress": progress}
    reset_m = re.search(r"resets[^\n]*?<t:(\d+)(?::[A-Za-z])?>", text or "", re.I)
    if reset_m:
        result["resets_at_epoch"] = int(reset_m.group(1))
    return result


# --- Daily + Cowoncy ------------------------------------------------------
# Tin nhan OwO hay in dam (**) va gach chan (__) — bo het truoc khi so khop.
def _plain(text: str) -> str:
    return text.replace("*", "").replace("_", "")


# "3H 11M 28S" — chi cho phep dau cach/tab GIUA cac cum, khong cho xuong dong,
# de khong an nham so o dong ke tiep.
_DURATION_PATTERN = r"((?:\d+[ \t]*[DHMS][ \t]*)+)"


def parse_daily(text: str, command: str = ""):
    """owo daily — 2 dang tin nhan:
      1. Da nhan: "Here is your daily <emoji> 5000 Cowoncy!", "You're on a 337
         daily streak!", "Your next daily is in: 23H 29M 17S".
      2. Chua toi gio: "Nu! Ruby! You need to wait 3H 11M 28S" — dang nay KHONG
         co chu "daily", nen chi nhan khi lenh ban vua go la lenh daily.
    """
    plain = _plain(text)
    if re.search(r"here is your daily", plain, re.I):
        reward_m = re.search(r"here is your daily.*?([\d,]+)\s*cowoncy", plain, re.I)
        streak_m = re.search(r"([\d,]+)\s*daily streak", plain, re.I)
        next_m = re.search(r"next daily is in:?\s*" + _DURATION_PATTERN, plain, re.I)
        return {
            "state": "claimed",
            "reward": int(reward_m.group(1).replace(",", "")) if reward_m else None,
            "streak": int(streak_m.group(1).replace(",", "")) if streak_m else None,
            "seconds_until_next": duration_to_seconds(next_m.group(1)) if next_m else None,
        }
    wait_m = re.search(r"need to wait\s*" + _DURATION_PATTERN, plain, re.I)
    if wait_m and "daily" in (command or "").lower():
        return {
            "state": "waiting", "reward": None, "streak": None,
            "seconds_until_next": duration_to_seconds(wait_m.group(1)),
        }
    return None


def parse_cowoncy(text: str):
    """owo money / owo cash — "Ruby, you currently have 2,061,145 cowoncy!" """
    m = re.search(r"you currently have\s*([\d,]+)\s*cowoncy", _plain(text), re.I)
    if not m:
        return None
    return {"amount": int(m.group(1).replace(",", ""))}


def parse_weapon_shards(text: str):
    """owo ws — mau that: \"weaponshard | Ruby, you currently have 1,174 Weapon Shards!\" """
    m = re.search(r"you currently have\s*([\d,]+)\s*weapon\s*shards?", _plain(text), re.I)
    if not m:
        return None
    return {"amount": int(m.group(1).replace(",", ""))}


# --- Loi khuyen vu khi: app go `?tag <vu khi>` trong server OwO roi gui NGUYEN CHU tren man hinh len day.
# Tin tra loi dang: "`105`<:105shield:..> — Defender's Aegis (Shield)\nLook for stats close to:\nWP Cost: 150-160 ...
# Recommended Passives: <:PShgen:..><:PSkaze:..> (<:PSsacrifice:..> only with <:114rstaff:..>)\nIdeal pets: ..."
# Tren man hinh ten emoji passive hien dang `PShgen`, cac emoji sat nhau co the dinh lien: "PShgenPSkazePSthorns".
_KNOWN_PASSIVES = {"hgen", "kaze", "thorns", "sprout", "farmor", "sacrifice", "wgen", "mtap", "crit", "mag",
                   "gslayer", "sguard", "lifesteal", "str", "discharge", "snail", "pr", "swarm", "dstrike",
                   "absolute", "enrage", "lhive"}


def _split_passive_token(tok: str):
    """'sacrificeonly' -> ('sacrifice', 'only') neu bat dau bang 1 passive da biet; khong thi giu nguyen."""
    if tok in _KNOWN_PASSIVES:
        return tok, ""
    best = ""
    for k in _KNOWN_PASSIVES:
        if tok.startswith(k) and len(k) > len(best):
            best = k
    return (best, tok[len(best):]) if best else (tok, "")


def _passives_before_condition(text: str):
    """'PSsacrificePSkaze not with PShgen, and only work with rstaff' -> ['sacrifice','kaze'] (passive sau 'not with' chi la ghi chu)."""
    left = re.split(r"\b(?:not with|only)\b", text or "", maxsplit=1)[0]
    return _passives_in(left)


def _passives_in(text: str):
    out = []
    for m in re.finditer(r"PS([a-z0-9]+)", text or ""):
        key, _rest = _split_passive_token(m.group(1))
        if key and key not in out:
            out.append(key)
    return out


_STAT_LABELS = {"stat5pa": "STR", "stat2mag": "MAG", "stat6hp": "HP", "stat3wp": "WP", "stat4pr": "PR", "stat1mr": "MR"}


_STAT_TOKEN_RE = re.compile(r"\b(stat\d[a-z]+)\b")


_ABILITY_NOISE_RE = re.compile(r"\bAB[A-Za-z]+\b")


def _clean_advice_line(ln: str) -> str:
    ln = _STAT_TOKEN_RE.sub(lambda m: _STAT_LABELS.get(m.group(1), ""), ln)
    return re.sub(r"\s+", " ", _ABILITY_NOISE_RE.sub("", ln)).strip()


def parse_weapon_advice(reply: str):
    """Rut ra tu tin tra loi `?tag <vu khi>`: ma + ten, cac dong CHI SO (Look for stats close to), passive khuyen dung
    (recommended), passive co dieu kien (trong ngoac), passive theo VAI TRO (STR Attacker / HP Tank...), pet ly tuong,
    canh bao. KHONG doan: thieu thi de None / rong; nguyen van luon nam o raw_reply."""
    lines = [ln.strip() for ln in (reply or "").split("\n")]
    code = name = None
    for ln in lines:
        if re.search(r"[—–]", ln) and re.search(r"1\d\d", ln):
            code = re.search(r"1\d\d", ln).group(0)
            name = re.split(r"[—–]", ln, maxsplit=1)[1].strip()
            break
    flat = re.sub(r"\s+", " ", " ".join(lines))

    # --- chi so can nham toi: tu "Look for stats" den "Recommended passives"
    stats, in_stats = [], False
    for ln in lines:
        if re.search(r"look for stats", ln, re.I):
            in_stats = True
            continue
        if re.search(r"recommended passives?", ln, re.I):
            break
        if in_stats and ln:
            c = _clean_advice_line(ln)
            if c:
                stats.append(c)
    wp = None
    for x in stats:
        if x.lower().startswith("wp cost"):
            m = re.search(r"\d[\d\-– ]*", x)
            wp = m.group(0).strip() if m else None

    # --- passive
    idx = next((i for i, ln in enumerate(lines) if re.search(r"recommended passives?", ln, re.I)), None)
    sec_lines = []
    if idx is not None:
        for j, ln in enumerate(lines[idx:]):
            if re.match(r"ideal pets", ln, re.I) or ln.startswith("⚠"):
                break
            if j == 0:
                ln = re.sub(r"^.*?recommended passives?:?\s*", "", ln, flags=re.I)
            if ln:
                sec_lines.append(ln)
    sec = " ".join(sec_lines)
    recommended, conditional, roles = [], [], []
    for g in re.finditer(r"\(([^)]*)\)", sec):
        ps = _passives_before_condition(g.group(1))
        if ps:
            conditional.append({"passives": ps, "dieu_kien": re.sub(r"PS[a-z0-9]+", "", g.group(1)).strip()})
    recommended = _passives_in(re.sub(r"\([^)]*\)", " ", sec))
    for ln in sec_lines:
        m = re.match(r"^([A-Za-z][A-Za-z ]{1,24}):\s*(.*)$", ln)
        if m and _passives_in(m.group(2)):
            roles.append({"role": m.group(1).strip(),
                          "passives": _passives_in(re.sub(r"\([^)]*\)", " ", m.group(2))),
                          "ghi_chu": re.sub(r"PS[a-z0-9]+", "", " ".join(re.findall(r"\(([^)]*)\)", m.group(2)))).strip()})

    # --- pet ly tuong + canh bao
    ideal, in_ideal = [], False
    for ln in lines:
        if re.match(r"ideal pets", ln, re.I):
            in_ideal = True
            continue
        if in_ideal:
            if ln.startswith("⚠") or ln.lower() == "more":
                break
            c = _clean_advice_line(ln)
            if c:
                ideal.append(c)
    warnings = [w.strip() for w in re.findall(r"⚠️?([^⚠]*?)(?=⚠|\bmore\b|$)", flat) if w.strip()]
    return {"code": code, "name": name, "wp_cost": wp, "stats": stats,
            "recommended": recommended, "conditional": conditional, "roles": roles,
            "ideal_pets": ideal, "warnings": warnings,
            "limited": "very limited viability" in flat.lower(),
            "tbd": bool(re.search(r"\bTBD\b", sec)),
            "co_muc_passive": bool(recommended or conditional)}


def _is_subsequence(small: str, big: str) -> bool:
    it = iter(big)
    return all(ch in it for ch in small)


# ===================== Kho vu khi: doc danh sach `owo weapon` (nhieu trang, moi trang SUA 1 tin) =====================
# Moi dong: `FVK6GV` <:rare:..><:rpstaff:..><:udischarge:..> **Staff of Purity** 60.7%
_WLIST_LINE_RE = re.compile(r"`([A-Z0-9]{4,8})`\s*((?:<a?:\w+:\d+>)+)\s*(⭐)?\s*\*\*([^*\n]+)\*\*\s*([\d.]+)%(?:[^\n]*?➤[ \t]*([^\n]*))?")


def _strip_to_known(emoji_name, known):
    """Bo 0-2 chu cai dau cho den khi khop 1 ten da biet (vd 'prgaxe' -> 'gaxe'); khong khop thi bo 1 chu cai do hiem."""
    for k in (0, 1, 2):
        if len(emoji_name) > k and emoji_name[k:] in known:
            return emoji_name[k:]
    return strip_rarity(emoji_name)


def parse_weapon_list(text: str):
    """Trang danh sach vu khi: header "'s Weapons" + "Weapon Filters". Tra ve [{id, rarity, type, passives, name, quality}]."""
    if "'s Weapons" not in (text or "") or "Weapon Filters" not in text:
        return None
    known = set(load_weapon_rules().get("emoji_to_code", {}))
    out = []
    for m in _WLIST_LINE_RE.finditer(text):
        ems = re.findall(r"<a?:(\w+):\d+>", m.group(2))
        if len(ems) < 2:
            continue
        pet = re.sub(r"<a?:\w+:\d+>|:\w+:", "", m.group(6) or "").strip()
        out.append({"id": m.group(1), "rarity": ems[0], "type": _strip_to_known(ems[1], known),
                    "passives": [strip_rarity(x) for x in ems[2:]], "passive_emojis": ems[2:],
                    "name": m.group(4).strip(), "quality": float(m.group(5)),
                    "starred": bool(m.group(3)), "equipped": m.group(6) is not None, "equipped_by": pet or None})
    return out or None


# ===================== Bo luat vu khi + cham diem DOI HINH (2 yeu to: chi so/co che vu khi va passive) =====================
_RULES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weapon_rules.json")


_RARITY_LETTERS = "curemlf"


_rules_cache = {"data": None}


def load_weapon_rules(force: bool = False):
    """Doc weapon_rules.json (cung thu muc voi bot). Khong co file -> bo rong (teamcheck se bao thieu)."""
    if _rules_cache["data"] is None or force:
        try:
            with open(_RULES_PATH, encoding="utf-8") as f:
                _rules_cache["data"] = json.load(f)
        except Exception as e:
            print(f"[tracker][rules] Khong doc duoc weapon_rules.json: {e!r}")
            _rules_cache["data"] = {"types": {}, "emoji_to_code": {}, "passive_alias": {}, "ruby": {}}
    return _rules_cache["data"]


def strip_rarity(emoji_name, table=None):
    """'mrstaff' -> 'rstaff'; 'msac' -> 'sac'. Ten emoji = 1 chu cai do hiem (c/u/r/e/m/l/f) + ten that."""
    if not emoji_name:
        return None
    if table is not None and emoji_name in table:
        return emoji_name
    if emoji_name[0] in _RARITY_LETTERS and len(emoji_name) > 1:
        return emoji_name[1:]
    return emoji_name


# --- Su kien: tin thuong khi hunt, vd
#   🐻 **|** `[8/10]` <@123>, A bear-ista freshly brewed you ... with **435 <:weaponshard:655902978712272917> Weapon Shards** on the side!
#   🍬 **|** `[1/10]` <@123>, Trick or treat! The neighbour is handing out **2 <:crate:523771259302182922> Weapon Crates**!
_EVENT_HEAD_RE = re.compile(
    r"^\s*(?P<kind>[^\n\[|`]{1,40}?)\s*\*{0,2}\|\*{0,2}\s*`?\[(?P<cur>\d+)\s*/\s*(?P<max>\d+)\]`?"
    r"\s*<@!?(?P<uid>\d+)>\s*[,:]?\s*(?P<body>.*)$")


_EVENT_REWARD_RE = re.compile(r"\*\*\s*([\d,]+)\s*(?:<a?:(\w+):(\d+)>)?\s*([^*<\n]*?)\s*\*\*")


def parse_event_hunt(text: str, source_id=None):
    """Doc cac dong su kien `[x/y]` trong tin OwO. Moi dong -> {kind, current, max, text, rewards}.
    source_id (neu co): chi nhan dong nhac DUNG nguoi dang theo doi (<@id>), bo dong cua nguoi khac."""
    events = []
    for line in (text or "").split("\n"):
        m = _EVENT_HEAD_RE.match(line)
        if not m:
            continue
        if source_id and m.group("uid") != str(source_id):
            continue
        kind = re.sub(r"<a?:(\w+):\d+>", r":\1:", m.group("kind")).replace("*", "").strip()
        if not kind:
            continue
        body = m.group("body")
        rewards = []
        for amount, ename, eid, label in _EVENT_REWARD_RE.findall(body):
            if not label.strip():
                continue
            r = {"amount": int(amount.replace(",", "")), "item": label.strip()}
            if ename:
                r["emoji_name"] = ename
                r["emoji_id"] = eid
            rewards.append(r)
        clean = re.sub(r"<a?:\w+:\d+>", "", body).replace("*", "")
        clean = re.sub(r"\s+", " ", clean).strip()
        events.append({"kind": kind, "current": int(m.group("cur")), "max": int(m.group("max")),
                       "text": clean[:300], "rewards": rewards})
    return events or None


# --- Zoo / Inventory / Gem — OwO dùng chữ số mũ Unicode (¹⁰⁴ = 104) cho
# số lượng ở cả 2 loại tin nhắn này, khác hẳn owodex (dùng backtick số
# thường). Cần giải mã riêng, không dùng chung logic với các parser trên.
_SUPERSCRIPT_DIGITS = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
                        "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}


def decode_superscript_number(s: str) -> int:
    digits = "".join(_SUPERSCRIPT_DIGITS.get(c, "") for c in s)
    return int(digits) if digits else 0


def parse_zoo(text: str, continuation: bool = False, start_tier=None):
    """owo zoo — bảng đếm pet theo từng tier. Mỗi dòng bắt đầu bằng 1 tier
    tag, theo sau là danh sách pet dạng :tên: (icon thường) hoặc
    <a?:tên:id> (custom emoji) + số lượng bằng chữ số mũ ngay sau. Dòng
    "blank" là dòng nối tiếp của tier ngay phía trên (khi 1 tier có hơn
    5 loại phải xuống dòng), không phải tier mới."""
    has_header = "'s zoo" in text or "zoo!" in text.lower()
    if not has_header and not continuation:
        return None

    tier_tag_pattern = re.compile(r"^<a?:(\w+):\d+>")
    entry_pattern = re.compile(r"(?:<(a)?:(\w+):(\d+)>|:(\w+):)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")

    pets = []
    sup_lens = []  # độ dài chuỗi số mũ: owo zoo d luôn đệm 0 cho đủ 6 chữ số
    current_tier = None
    # Zoo dai nen OwO chia thanh nhieu tin nhan. Tin tiep noi khong co tieu de
    # "'s zoo"; neu no bat dau bang 1 tier tag (ke ca "blank" = tiep tuc tier
    # truoc do) thi tier dang do duoc ke thua tu tin truoc (start_tier).
    if continuation and not has_header:
        first_line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "")
        if tier_tag_pattern.match(first_line):
            current_tier = start_tier
    for line in text.split("\n"):
        tier_m = tier_tag_pattern.match(line.strip())
        if tier_m:
            tag = tier_m.group(1)
            if tag != "blank":
                current_tier = tag
        if current_tier is None:
            continue
        for m in entry_pattern.finditer(line):
            animated, custom_name, custom_id, plain_name = m.group(1), m.group(2), m.group(3), m.group(4)
            name = custom_name or plain_name
            entry = {"tier": current_tier, "name": name, "count": decode_superscript_number(m.group(5))}
            if custom_id:
                entry["emoji_id"] = custom_id
                entry["emoji_animated"] = bool(animated)
            pets.append(entry)
            sup_lens.append(len(m.group(5)))

    points_m = re.search(r"Zoo Points:\s*__([\d,]+)__", text)
    breakdown_m = re.search(r"\*\*(F-[\d\-A-Za-z, ]+C-[\d,]+)\*\*", text)
    if not pets and not points_m:
        return None
    return {
        "pets": pets,
        "zoo_points": int(points_m.group(1).replace(",", "")) if points_m else None,
        "breakdown_raw": breakdown_m.group(1) if breakdown_m else None,
        "padded": bool(sup_lens) and min(sup_lens) >= 6,  # True = bảng "owo zoo d" (số đã bắt)
    }


_GEM_TIER_PREFIX = {"c": "Common", "u": "Uncommon", "r": "Rare", "e": "Epic",
                     "m": "Mythical", "l": "Legendary", "f": "Fabled"}


_GEM_TIER_RANK = {"Common": 1, "Uncommon": 2, "Rare": 3, "Epic": 4,
                   "Mythical": 5, "Legendary": 6, "Fabled": 7}


def parse_gem_name(emoji_name: str):
    """'cgem1' -> {'tier':'Common','slot':'1'}; 'cstar' (gem đặc biệt, sự kiện) -> slot 'star'. None nếu không phải gem."""
    m = re.match(r"^([curelmf])(?:gem(\d+)|(star))$", emoji_name)
    if not m:
        return None
    # gem thuong theo loai gem1/gem3/gem4 (slot "1"/"3"/"4"); gem DAC BIET (cstar...) chi co
    # trong su kien -> slot "star".
    return {"tier": _GEM_TIER_PREFIX.get(m.group(1)), "slot": m.group(2) or "star"}


def parse_inventory(text: str, continuation: bool = False):
    """owo inventory — danh sách item, mỗi item có mã 3 số (backtick),
    emoji tên item, và số lượng bằng chữ số mũ ngay sau (không có dấu
    cách). Trả về cả item thường lẫn gem — gem được đánh dấu is_gem."""
    if "Inventory" not in text and not continuation:
        return None
    pattern = re.compile(r"`(\d{3})`<(a)?:([a-zA-Z0-9_]+):(\d+)>([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
    items = []
    for code, animated, name, emoji_id, sup in pattern.findall(text):
        gem_info = parse_gem_name(name)
        items.append({
            "code": code, "name": name, "count": decode_superscript_number(sup),
            "is_gem": gem_info is not None,
            "gem_tier": gem_info["tier"] if gem_info else None,
            "gem_slot": gem_info["slot"] if gem_info else None,
            "gem_tier_rank": _GEM_TIER_RANK.get(gem_info["tier"]) if gem_info else None,
            "emoji_id": emoji_id, "emoji_animated": bool(animated),
        })
    if not items:
        return None
    return {"items": items}


def parse_hunt_gem_status(text: str):
    """Dòng 'hunt is empowered by <gem>[hiện/tối đa] ...' trong tin nhắn
    owo hunt/autohunt. Gem nào KHÔNG trang bị sẽ không xuất hiện ở đây —
    đúng đặc điểm bạn mô tả."""
    if "empowered by" not in text:
        return None
    pattern = re.compile(r"<(a)?:([a-zA-Z0-9_]+):(\d+)>`?\[(\d+)/(\d+)\]`?")
    gems = []
    for animated, name, emoji_id, cur, mx in pattern.findall(text):
        gem_info = parse_gem_name(name)
        if not gem_info:
            continue
        gems.append({"slot": gem_info["slot"], "tier": gem_info["tier"], "emoji_name": name,
                     "emoji_id": emoji_id, "emoji_animated": bool(animated),
                     "current": int(cur), "max": int(mx)})
    if not gems:
        return None
    return {"gems": gems}


def parse_battle(text: str):
    """owo battle — dong cuoi cua tin (footer):
      thang:            'You won in 7 turns!  |  +200 xp  |  Streak: 144'
      thua (khong co chuoi): 'You lost in 10 turns!  |  +80 xp'
      thua (cat chuoi):  'You lost in 16 turns!  |  +70 xp  |  Streak ended at 1'
      hoa:              "It's a tie in 24 turns!  |  +100 xp  |  Streak: 330"
    Thua = chuoi hien tai ve 0 ('ended at N' la chuoi da MAT, khong phai chuoi hien tai).
    Hoa = chuoi giu nguyen theo so ghi trong tin."""
    m = re.search(r"(?:You\s+(won|lost)|It[\u2019']?s\s+a\s+(tie))\s+in\s+(\d+)\s+turns?\b[^\n]*", text or "", re.I)
    if not m:
        return None
    line = m.group(0)
    result = (m.group(1) or m.group(2)).lower()
    xp_m = re.search(r"\+\s*([\d,]+)\s*xp", line, re.I)
    streak_m = re.search(r"Streak\s*:\s*(\d+)", line, re.I)
    ended_m = re.search(r"Streak\s+ended\s+at\s+(\d+)", line, re.I)
    if result in ("won", "tie"):
        streak = int(streak_m.group(1)) if streak_m else None  # khong ghi chuoi -> chua biet
        lost_streak = None
    else:
        streak = 0
        lost_streak = int(ended_m.group(1)) if ended_m else 0
    return {
        "result": result, "turns": int(m.group(3)),
        "xp": int(xp_m.group(1).replace(",", "")) if xp_m else None,
        "streak": streak, "lost_streak": lost_streak,
    }


_HUNT_ANIMAL_RE = re.compile(r"<(a)?:(\w+):(\d+)>|:(\w+):")


def parse_hunt_found(text: str):
    """owo hunt — dong 'You found:  :bee: :bee: <a:gowl:123> ...' -> danh sach loai thu
    (khong trung, giu thu tu). Chi doc dung dong 'You found:', khong lay emoji o dong khac."""
    m = re.search(r"You found:[ \t]*([^\n]*)", text or "")
    if not m:
        return None
    animals, seen = [], set()
    for animated, custom_name, custom_id, plain_name in _HUNT_ANIMAL_RE.findall(m.group(1)):
        name = custom_name or plain_name
        key = name.lower()
        if key in seen or key == "blank":
            continue
        seen.add(key)
        entry = {"name": name}
        if custom_id:
            entry["emoji_id"] = custom_id
            entry["emoji_animated"] = bool(animated)
        animals.append(entry)
    return {"animals": animals} if animals else None


def _parse_utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def duration_to_seconds(text):
    """'1H 23M' -> 4980. Doc duoc D/H/M/S. Tra None neu khong doc duoc gi."""
    if not text:
        return None
    upper = text.upper()
    total, found = 0, False
    for unit, mult in (("D", 86400), ("H", 3600), ("M", 60), ("S", 1)):
        m = re.search(rf"(\d+)\s*{unit}", upper)
        if m:
            total += int(m.group(1)) * mult
            found = True
    return total if found else None


# Dong cuoi cua bang zoo: "F-3, CP-9, B-1, G-77, L-371, P-730, M-810, S-82, E-7448,
# R-74914, U-223757, C-439810" — so pet theo tung tier. Ma chu cai -> ten tier.
ZOO_TIER_CODES = {
    "C": "common", "U": "uncommon", "R": "rare", "E": "epic", "M": "mythic",
    "L": "legendary", "G": "gem", "P": "patreon", "CP": "cpatreon",
    "S": "special", "B": "botrank", "F": "fabled",
}


def parse_zoo_breakdown(raw):
    """"F-3, CP-9, ..., C-439810" -> {"fabled": 3, "cpatreon": 9, ..., "common": 439810}.
    Ma la nao khong nhan ra thi bo qua."""
    out = {}
    for code, num in re.findall(r"\b([A-Z]{1,2})-(\d[\d,]*)", raw or ""):
        tier = ZOO_TIER_CODES.get(code)
        if tier:
            out[tier] = int(num.replace(",", ""))
    return out
