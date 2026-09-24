"""
owo_tracker_bot.py
===================
Bot Discord duy nhất, dùng chung MongoDB với các dự án khác của bạn.
KHÔNG có dữ liệu game nào được ghi sẵn trong file — mọi thông tin về
pet/vũ khí/passive đều do bot tự bắt được lúc chơi, hoặc do bạn gõ
lệnh nhập trực tiếp. Ghi nhận MỌI pet/vũ khí/passive quan sát được,
không phân biệt hiếm hay thường.

Cài đặt:
  pip install discord.py motor

Biến môi trường:
  DISCORD_TOKEN      — token bot Discord
  OWNER_ID           — Discord ID của bạn (chỉ người này đổi tracked user)
  MONGODB_URI        — connection string MongoDB dùng chung
  MONGODB_DB_NAME    — tên database RIÊNG cho bot này trong cùng cluster
                       (mặc định "owo_tracker" — không đụng tới database
                       của các dự án khác, dù chung URI/cluster)

Chạy:
  DISCORD_TOKEN=... OWNER_ID=... MONGODB_URI=... python owo_tracker_bot.py
"""

import os
import re
import time
import hmac
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ----------------------------------------------------------------------
# CẤU HÌNH
# ----------------------------------------------------------------------
OWO_BOT_ID = 408785106942164992  # kiểm tra lại ID thật trong server bạn
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OWNER_ID = os.environ.get("OWNER_ID")
MONGODB_URI = os.environ.get("MONGODB_URI")
MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "owo_tracker")
CORRELATION_WINDOW = 20  # giây — cửa sổ khớp lệnh owo với phản hồi của OwO bot

# --- API nhỏ cho AutoMacro (app Android) doc lenh can lam ---
# Khong dat AUTOMACRO_API_TOKEN thi API se KHONG chay (an toan mac dinh,
# tranh mo cong ma khong ai bao ve).
AUTOMACRO_API_TOKEN = os.environ.get("AUTOMACRO_API_TOKEN")
AUTOMACRO_API_PORT = int(os.environ.get("PORT", os.environ.get("AUTOMACRO_API_PORT", "8080")))
COL_AUTOMACRO_COMMANDS = "owot_automacro_commands"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=",", intents=intents, help_command=None)

mongo_client = AsyncIOMotorClient(MONGODB_URI) if MONGODB_URI else None
mdb = mongo_client[MONGODB_DB_NAME] if mongo_client else None
# Tên collection có tiền tố riêng — để không lẫn với các dự án khác nếu
# lỡ dùng chung 1 database thay vì tách database riêng như khuyến nghị.
COL_CONFIG = "owot_config"
COL_PET_SPECIES = "owot_pet_species"
COL_WEAPON_TYPES = "owot_weapon_types"
COL_WEAPON_INSTANCES = "owot_weapon_instances"
COL_PASSIVES = "owot_passives"
COL_TEAM = "owot_team_slots"
COL_HUNTBOT = "owot_huntbot_status"
COL_QUEST = "owot_quest_status"
COL_NOTES = "owot_notes"
COL_ZOO = "owot_zoo_snapshot"
COL_INVENTORY = "owot_inventory_items"
COL_GEM_STATUS = "owot_gem_status"
COL_DAILY = "owot_daily_status"
COL_COWONCY = "owot_cowoncy"

pending_commands = {}  # channel_id -> timestamp gần nhất có lệnh owo từ tracked user
tracked_names = {}  # user_id (chuỗi) -> các tên Discord của người đó (ghi lại mỗi khi họ gõ lệnh owo)
skipped_weapon = {"owner": None, "id": None}  # vũ khí gần nhất bị bỏ qua vì sai chủ (để lệnh ,weaponowner báo)
last_owo_command = {}  # channel_id -> nội dung lệnh owo gần nhất (chữ thường), để biết tin OwO đang trả lời lệnh nào
_automacro_api_started = False


# ----------------------------------------------------------------------
# CONFIG helpers
# ----------------------------------------------------------------------
async def get_config(key, default=None):
    doc = await mdb[COL_CONFIG].find_one({"_id": key})
    return doc["value"] if doc else default


async def set_config(key, value):
    await mdb[COL_CONFIG].update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)


async def next_note_id():
    doc = await mdb[COL_CONFIG].find_one_and_update(
        {"_id": "notes_counter"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["value"]


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

# Dịch theo mẫu câu cố định OwO hay dùng — KHÔNG dùng API dịch ngoài (tốn
# phí, phụ thuộc mạng, có thể lỗi âm thầm). Nếu câu không khớp mẫu nào,
# trả về None — nơi gọi hàm này sẽ giữ nguyên bản tiếng Anh thay vì đoán
# bừa ra 1 câu dịch sai.
_TRANSLATE_PATTERNS = [
    (r"^Deals? ([\d.]+)% of your (STR|MAG) to an enemy and apply (\w+) for (\d+) turns?\.?$",
     lambda m: f"Gây {m.group(1)}% {m.group(2)} lên 1 địch và áp {m.group(3)} trong {m.group(4)} lượt."),
    (r"^Deals? ([\d.]+)% of your (STR|MAG) to all opponents\.?$",
     lambda m: f"Gây {m.group(1)}% {m.group(2)} lên TẤT CẢ địch."),
    (r"^Deals? ([\d.]+)% of your (STR|MAG) to (?:an enemy)\.?$",
     lambda m: f"Gây {m.group(1)}% {m.group(2)} lên 1 địch."),
    (r"^Deal ([\d.]+)% of your (STR|MAG) to ALL enemies and heal ALL allies by the damage dealt\.?$",
     lambda m: f"Gây {m.group(1)}% {m.group(2)} lên TẤT CẢ địch, đồng thời hồi máu TẤT CẢ đồng minh "
               f"bằng đúng lượng damage vừa gây ra."),
    (r"^At the start of the turn, apply Taunt to your animal for (\d+) turns?\.?$",
     lambda m: f"Đầu mỗi lượt, tự áp Taunt lên bản thân trong {m.group(1)} lượt."),
    (r"^Increases? your (STR|MAG|PR|WP|MR|HP) by ([\d.]+)%\.?$",
     lambda m: f"Tăng {m.group(1)} thêm {m.group(2)}%."),
    (r"^Decreases? all healing for this animal by -([\d.]+)%\.?$",
     lambda m: f"Giảm {m.group(1)}% hồi máu nhận vào."),
    (r"^Deal \+?([\d.]+)% more damage to bosses\.?$",
     lambda m: f"Gây thêm {m.group(1)}% sát thương khi đánh boss."),
]


def translate_effect_text(text):
    """Dịch 1 câu mô tả hiệu ứng/passive sang tiếng Việt nếu khớp mẫu đã
    biết. Trả về None nếu không khớp — nơi gọi giữ nguyên tiếng Anh."""
    if not text:
        return None
    t = text.strip()
    for pattern, fn in _TRANSLATE_PATTERNS:
        m = re.match(pattern, t)
        if m:
            return fn(m)
    return None


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


def _name_key(name):
    """So sanh ten khong phan biet hoa/thuong va bo qua dau cach, ky hieu."""
    return re.sub(r"[\W_]+", "", (name or "").casefold())


def weapon_owner_matches(owner, names):
    key = _name_key(owner)
    return bool(key) and any(_name_key(n) == key for n in names if n)


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

    return {
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
        entry = {
            "pos": i, "name": emoji_to_name(name_m.group(1)),
            "level": int(lvl_m.group(1)) if lvl_m else None,
            "weaponId": weapon_m.group(1) if weapon_m else None,
            "quality": float(quality_m.group(1)) if quality_m else None,
        }
        if len(nums) >= 6:
            entry.update({"hp": int(nums[0]), "wp": int(nums[1]), "att": int(nums[2]),
                          "mag": int(nums[3]), "pr": int(nums[4]), "mr": int(nums[5])})
        result.append(entry)
    return result


def parse_huntbot_status(text: str):
    if "HUNTBOT" not in text.upper():
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
    return {
        "essence": int(essence_m.group(1).replace(",", "")) if essence_m else None,
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
    entry_pattern = re.compile(r"(?:<a?:(\w+):\d+>|:(\w+):)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")

    pets = []
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
            name = m.group(1) or m.group(2)
            pets.append({"tier": current_tier, "name": name, "count": decode_superscript_number(m.group(3))})

    points_m = re.search(r"Zoo Points:\s*__([\d,]+)__", text)
    breakdown_m = re.search(r"\*\*(F-[\d\-A-Za-z, ]+C-[\d,]+)\*\*", text)
    if not pets and not points_m:
        return None
    return {
        "pets": pets,
        "zoo_points": int(points_m.group(1).replace(",", "")) if points_m else None,
        "breakdown_raw": breakdown_m.group(1) if breakdown_m else None,
    }


_GEM_TIER_PREFIX = {"c": "Common", "u": "Uncommon", "r": "Rare", "e": "Epic",
                     "m": "Mythical", "l": "Legendary", "f": "Fabled"}
_GEM_TIER_RANK = {"Common": 1, "Uncommon": 2, "Rare": 3, "Epic": 4,
                   "Mythical": 5, "Legendary": 6, "Fabled": 7}


def parse_gem_name(emoji_name: str):
    """'cgem1' -> {'tier':'Common','slot':'1'}. None nếu không phải gem."""
    m = re.match(r"^([curelmf])gem(\d+)$", emoji_name)
    if not m:
        return None
    return {"tier": _GEM_TIER_PREFIX.get(m.group(1)), "slot": m.group(2)}


def parse_inventory(text: str):
    """owo inventory — danh sách item, mỗi item có mã 3 số (backtick),
    emoji tên item, và số lượng bằng chữ số mũ ngay sau (không có dấu
    cách). Trả về cả item thường lẫn gem — gem được đánh dấu is_gem."""
    if "Inventory" not in text:
        return None
    pattern = re.compile(r"`(\d{3})`<a?:([a-zA-Z0-9_]+):(\d+)>([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")
    items = []
    for code, name, emoji_id, sup in pattern.findall(text):
        gem_info = parse_gem_name(name)
        items.append({
            "code": code, "name": name, "count": decode_superscript_number(sup),
            "is_gem": gem_info is not None,
            "gem_tier": gem_info["tier"] if gem_info else None,
            "gem_slot": gem_info["slot"] if gem_info else None,
            "gem_tier_rank": _GEM_TIER_RANK.get(gem_info["tier"]) if gem_info else None,
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
    pattern = re.compile(r"<a?:([a-zA-Z0-9_]+):\d+>\[(\d+)/(\d+)\]")
    gems = []
    for name, cur, mx in pattern.findall(text):
        gem_info = parse_gem_name(name)
        if not gem_info:
            continue
        gems.append({"slot": gem_info["slot"], "tier": gem_info["tier"],
                     "emoji_name": name, "current": int(cur), "max": int(mx)})
    if not gems:
        return None
    return {"gems": gems}


# ----------------------------------------------------------------------
# LƯU — tất cả upsert theo key tự nhiên (tên pet, tên loại vũ khí, tên
# passive, ID vũ khí) nên gọi lại nhiều lần không tạo bản trùng.
# ----------------------------------------------------------------------
ZOO_PART_WINDOW = 60  # giay: tin tiep noi cua zoo phai toi trong khoang nay sau tin truoc
zoo_session = {}  # channel_id -> {"ts": thoi diem tin zoo gan nhat, "data": zoo da ghep}


def merge_zoo_parts(first, part):
    """Ghep 2 phan cua cung 1 bang zoo: cong danh sach pet; Zoo Points / breakdown
    lay tu phan nao co (thuong nam o tin cuoi cung)."""
    return {
        "pets": first["pets"] + part["pets"],
        "zoo_points": part["zoo_points"] if part.get("zoo_points") is not None else first.get("zoo_points"),
        "breakdown_raw": part.get("breakdown_raw") or first.get("breakdown_raw"),
    }


async def handle_zoo_text(channel_id, text, source_id=None):
    """Xu ly 1 tin nhan co the thuoc bang zoo. Tin co tieu de -> bat dau bang zoo
    moi. Tin khong tieu de nhung toi ngay sau tin zoo (cung kenh, trong vong
    ZOO_PART_WINDOW giay) -> ghep vao bang dang doc."""
    is_header = "'s zoo" in text or "zoo!" in text.lower()
    session = zoo_session.get(channel_id)
    merged = None
    if is_header:
        merged = parse_zoo(text)
    elif session and time.time() - session["ts"] < ZOO_PART_WINDOW:
        pets_so_far = session["data"]["pets"]
        part = parse_zoo(text, continuation=True, start_tier=pets_so_far[-1]["tier"] if pets_so_far else None)
        if part:
            merged = merge_zoo_parts(session["data"], part)
    if merged:
        zoo_session[channel_id] = {"ts": time.time(), "data": merged}
        await save_zoo(merged, source_id)


async def save_zoo(z, source_id=None):
    """Zoo là 1 bản chụp toàn cảnh — ghi đè bản cũ mỗi lần quan sát mới,
    không cộng dồn (số lượng pet là tuyệt đối, không phải log sự kiện)."""
    await mdb[COL_ZOO].update_one(
        {"_id": "latest"},
        {"$set": {"pets": z["pets"], "zoo_points": z.get("zoo_points"),
                  "breakdown_raw": z.get("breakdown_raw"),
                  "updated_at": datetime.utcnow().isoformat(), "updated_by": source_id}},
        upsert=True,
    )


async def save_inventory(inv, source_id=None):
    """Mỗi item lưu riêng 1 document (khoá theo mã 3 số) — để dễ tra cứu
    từng item và để lệnh ,gems tìm đúng mã cho `owo use`."""
    for item in inv["items"]:
        await mdb[COL_INVENTORY].update_one(
            {"_id": item["code"]},
            {"$set": {**item, "updated_at": datetime.utcnow().isoformat(), "updated_by": source_id}},
            upsert=True,
        )


async def save_gem_status(gs, source_id=None):
    """Lưu tình trạng gem NGAY LÚC HUNT — khoá theo slot (1/3/4), ghi đè
    bản cũ. Trả về danh sách slot đã BIẾN MẤT so với lần trước (từng
    trang bị, giờ không còn hiện trong tin nhắn) — dấu hiệu gem vừa hết
    hoặc bị tháo, dùng để quyết định có cần nhắc hay không."""
    seen_slots = {g["slot"] for g in gs["gems"]}
    prev_cursor = mdb[COL_GEM_STATUS].find({})
    prev_docs = await prev_cursor.to_list(length=10)
    prev_slots = {d["_id"] for d in prev_docs}
    vanished_slots = prev_slots - seen_slots

    for g in gs["gems"]:
        await mdb[COL_GEM_STATUS].update_one(
            {"_id": g["slot"]},
            {"$set": {"tier": g["tier"], "emoji_name": g["emoji_name"],
                      "current": g["current"], "max": g["max"],
                      "updated_at": datetime.utcnow().isoformat(), "updated_by": source_id}},
            upsert=True,
        )
    for slot in vanished_slots:
        await mdb[COL_GEM_STATUS].delete_one({"_id": slot})
    return vanished_slots


# ----------------------------------------------------------------------
# HANG DOI LENH cho AutoMacro (app Android tu dong hoa) + API nho de
# app do doc lenh va bao lai ket qua. Khong dung chung MONGODB_URI/token
# voi dien thoai — chi lo token API (thu hoi duoc), URI that chi nam o
# server nay.
# ----------------------------------------------------------------------
async def queue_automacro_command(action: str, params: dict):
    """Ghi 1 lenh moi, trang thai 'pending'. AutoMacro se doc qua API,
    thuc thi, roi bao lai qua /commands/<id>/ack."""
    if mdb is None:
        return
    doc_id = await next_note_id()  # dung chung bo dem voi ,note, chi can duy nhat
    await mdb[COL_AUTOMACRO_COMMANDS].insert_one({
        "_id": doc_id,
        "action": action,
        "params": params,
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    })
    return doc_id


def _check_api_token(request: web.Request) -> bool:
    if not AUTOMACRO_API_TOKEN:
        return False
    got = request.headers.get("Authorization", "").encode("utf-8")
    want = f"Bearer {AUTOMACRO_API_TOKEN}".encode("utf-8")
    return hmac.compare_digest(got, want)


async def handle_get_pending_commands(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    cursor = mdb[COL_AUTOMACRO_COMMANDS].find({"status": "pending"}).sort("_id", 1)
    docs = await cursor.to_list(length=20)
    for d in docs:
        d["id"] = d.pop("_id")
    return web.json_response({"commands": docs})


async def handle_ack_command(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        cmd_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "invalid id"}, status=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    status = body.get("status", "done")  # "done" hoac "failed"
    await mdb[COL_AUTOMACRO_COMMANDS].update_one(
        {"_id": cmd_id},
        {"$set": {"status": status, "completed_at": datetime.utcnow().isoformat()}},
    )
    return web.json_response({"ok": True})


# ----------------------------------------------------------------------
# HUB — tong hop du lieu moi nhat bot da doc duoc tu tin nhan OwO, tra ve
# 1 cuc JSON de app AutoMacro hien thanh man hinh "Hub". Chi DOC, khong
# ghi gi vao DB. Moi muc kem `updated_at` + `age_seconds` de app bao
# "cap nhat X phut truoc" — vi bot chi biet nhung gi OwO da in ra khi
# ban go lenh, muc nao lau chua go lenh thi du lieu se cu.
# ----------------------------------------------------------------------
def _iso_z(value):
    """Chuoi ISO gio UTC 'khong mui gio' cua bot -> them 'Z' cho app biet la UTC."""
    if not value:
        return None
    return value if value.endswith("Z") else value + "Z"


def _parse_utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None


def _age_seconds(value, now):
    t = _parse_utc(value)
    if t is None:
        return None
    return max(0, int((now - t).total_seconds()))


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


def _with_age(d, updated_at, now):
    d["updated_at"] = _iso_z(updated_at)
    d["age_seconds"] = _age_seconds(updated_at, now)
    return d


async def _hub_gems(now):
    rows = await mdb[COL_GEM_STATUS].find().sort("_id", 1).to_list(length=10)
    spare_rows = await mdb[COL_INVENTORY].find(
        {"is_gem": True, "count": {"$gt": 0}}
    ).to_list(length=200)
    if not rows and not spare_rows:
        return None
    equipped = []
    for r in rows:
        mx = r.get("max") or 0
        pct = round(r["current"] / mx * 100) if mx else 0
        equipped.append(_with_age({
            "slot": r["_id"], "tier": r.get("tier"),
            "current": r.get("current"), "max": mx, "percent": pct,
        }, r.get("updated_at"), now))
    spare = sorted(
        ({"code": r["_id"], "slot": r.get("gem_slot"), "tier": r.get("gem_tier"),
          "count": r.get("count"), "tier_rank": r.get("gem_tier_rank") or 0}
         for r in spare_rows),
        key=lambda x: (x["slot"] or "", x["tier_rank"]),
    )
    return {"equipped": equipped, "spare": spare}


async def _hub_huntbot(now):
    row = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])
    if not row:
        return None
    observed = _parse_utc(row.get("created_at"))
    secs = duration_to_seconds(row.get("time_remaining")) if row.get("hunting") else None
    ready_at, seconds_left = None, None
    if secs is not None and observed is not None:
        ready = observed + timedelta(seconds=secs)
        ready_at = ready.isoformat() + "Z"
        seconds_left = max(0, int((ready - now).total_seconds()))
    return _with_age({
        "hunting": bool(row.get("hunting")),
        "progress_pct": row.get("progress_pct"),
        "animals_captured": row.get("animals_captured"),
        "essence": row.get("essence"),
        "time_remaining_text": row.get("time_remaining"),
        "ready_at": ready_at,
        "seconds_left": seconds_left,
    }, row.get("created_at"), now)


async def _hub_quest(now):
    row = await mdb[COL_QUEST].find_one(sort=[("_id", -1)])
    if not row:
        return None
    next_text = row.get("next_quest")
    epoch = row.get("next_quest_epoch")
    next_seconds = None
    if epoch is not None:
        next_seconds = max(0, int(epoch - (now - datetime(1970, 1, 1)).total_seconds()))
        next_text = None  # chi la moc <t:...>, khong phai chu doc duoc
    return _with_age({
        "seals": row.get("seals"), "all_done": bool(row.get("all_done")),
        "next_quest": next_text, "next_quest_seconds": next_seconds,
        "quests": row.get("quests") or [],
    }, row.get("created_at"), now)


async def _hub_daily(now):
    doc = await mdb[COL_DAILY].find_one({"_id": "latest"})
    if not doc:
        return None
    ready = _parse_utc(doc.get("ready_at"))
    seconds_left = max(0, int((ready - now).total_seconds())) if ready else None
    return _with_age({
        "state": doc.get("state"), "streak": doc.get("streak"),
        "last_reward": doc.get("last_reward"),
        "ready_at": _iso_z(doc.get("ready_at")), "seconds_left": seconds_left,
    }, doc.get("updated_at"), now)


async def _hub_cowoncy(now):
    doc = await mdb[COL_COWONCY].find_one({"_id": "latest"})
    if not doc:
        return None
    return _with_age({"amount": doc.get("amount")}, doc.get("updated_at"), now)


async def _hub_team(now):
    rows = await mdb[COL_TEAM].find().sort("_id", 1).to_list(length=10)
    if not rows:
        return None
    members = []
    for r in rows:
        m = {k: r.get(k) for k in ("pos", "name", "level", "hp", "wp", "att", "mag", "pr", "mr",
                                   "weaponId", "quality")}
        m["name"] = emoji_to_name(m["name"])
        # Ban ghi cu tung doc nham ID emoji thanh so lieu (so ~18 chu so) -> bo, cho lan owo team ke tiep ghi de.
        for stat in ("hp", "wp", "att", "mag", "pr", "mr"):
            if isinstance(m[stat], int) and m[stat] >= 10 ** 9:
                m[stat] = None
        members.append(m)
    return _with_age({"members": members}, rows[0].get("updated_at"), now)


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


async def _hub_zoo(now):
    doc = await mdb[COL_ZOO].find_one({"_id": "latest"})
    if not doc:
        return None
    by_tier = {}
    for p in doc.get("pets", []):
        t = by_tier.setdefault(p["tier"], {"species": 0, "total": 0})
        t["total"] += p.get("count", 0)
        if p.get("count", 0) > 0:
            t["species"] += 1
    pets = [p for p in doc.get("pets", []) if p.get("count", 0) > 0]
    list_total = sum(t["total"] for t in by_tier.values())

    # Tong pet lay tu DONG CUOI cua bang zoo (so lieu day du) khi dong do phu du
    # moi tier; thieu tier nao thi quay ve cach cong cac so nho trong bang.
    breakdown = parse_zoo_breakdown(doc.get("breakdown_raw"))
    use_breakdown = bool(breakdown) and all(tier in breakdown for tier in by_tier)
    if use_breakdown:
        for tier, t in by_tier.items():
            t["total"] = breakdown[tier]
    return _with_age({
        "zoo_points": doc.get("zoo_points"), "breakdown_raw": doc.get("breakdown_raw"),
        "total_pets": sum(breakdown.values()) if use_breakdown else list_total,
        "total_source": "breakdown" if use_breakdown else "list",
        "list_total": list_total,
        "by_tier": by_tier, "pets": pets,
    }, doc.get("updated_at"), now)


async def _hub_inventory(now):
    rows = await mdb[COL_INVENTORY].find().sort("_id", 1).to_list(length=1000)
    rows = [r for r in rows if r.get("count", 0) > 0]
    if not rows:
        return None
    items = [{"code": r["_id"], "name": r.get("name"), "count": r.get("count"),
              "is_gem": bool(r.get("is_gem"))} for r in rows]
    latest = max((r.get("updated_at") or "" for r in rows), default=None) or None
    return _with_age({"kinds": len(items), "total_items": sum(i["count"] for i in items),
                      "items": items}, latest, now)


async def _hub_weapons(now):
    rows = await mdb[COL_WEAPON_INSTANCES].find().sort("updated_at", -1).to_list(length=100)
    if not rows:
        return None
    weapons = [{"id": r["_id"], "type_name": r.get("type_name"), "quality": r.get("quality"),
                "passive_name": r.get("passive_name"),
                "passive_desc": r.get("passive_desc_vi") or r.get("passive_desc")} for r in rows]
    return _with_age({"count": len(weapons), "weapons": weapons}, rows[0].get("updated_at"), now)


async def build_hub(now=None):
    """Gom du lieu cho man hinh Hub. Muc nao bot chua tung thay thi = null."""
    now = now or datetime.utcnow()
    return {
        "hub_version": 1,
        "server_time": now.isoformat() + "Z",
        "daily": await _hub_daily(now),
        "cowoncy": await _hub_cowoncy(now),
        "gems": await _hub_gems(now),
        "huntbot": await _hub_huntbot(now),
        "quest": await _hub_quest(now),
        "team": await _hub_team(now),
        "zoo": await _hub_zoo(now),
        "inventory": await _hub_inventory(now),
        "weapons": await _hub_weapons(now),
    }


async def handle_get_hub(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        data = await build_hub()
    except Exception as e:  # khong de app nhan trang loi kho hieu
        print(f"[tracker] Loi khi dung hub: {e!r}")
        return web.json_response({"error": "hub_failed"}, status=500)
    return web.json_response(data)


async def start_automacro_api_server():
    app = web.Application()
    app.router.add_get("/commands/pending", handle_get_pending_commands)
    app.router.add_post("/commands/{id}/ack", handle_ack_command)
    app.router.add_get("/hub", handle_get_hub)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", AUTOMACRO_API_PORT)
    await site.start()
    print(f"[tracker] API cho AutoMacro dang chay o cong {AUTOMACRO_API_PORT}")


async def save_pet_species(p, source_id=None):
    key = p["name"].lower()
    hp, att, pr, wp, mag, mr = p["stats"]
    await mdb[COL_PET_SPECIES].update_one(
        {"_id": key},
        {"$set": {
            "display_name": p["name"], "aliases": p.get("aliases", [p["name"]]),
            "rank": p["rank"], "rank_vi": p.get("rank_vi"),
            "hp": hp, "att": att, "pr": pr, "wp": wp, "mag": mag, "mr": mr,
            "count_seen": p["count"], "flavor_text": p.get("flavor_text"),
            "rarity_caught": p.get("rarity_caught"), "points": p.get("points"),
            "sell_cowoncy": p.get("sell_cowoncy"), "sell_sold_count": p.get("sell_sold_count"),
            "sacrifice_essence": p.get("sacrifice_essence"),
            "sacrifice_killed_count": p.get("sacrifice_killed_count"),
            "confirmed_at": datetime.utcnow().isoformat(),
            "confirmed_by": source_id, "source": "owodex",
        }},
        upsert=True,
    )


async def save_weapon_type(w, source_id=None):
    key = w["type_name"].lower()
    update = {
        "display_name": w["type_name"],
        "confirmed_at": datetime.utcnow().isoformat(),
        "confirmed_by": source_id,
    }
    if w.get("main_desc"):
        update["main_desc"] = w["main_desc"]
        vi = translate_effect_text(w["main_desc"])
        if vi:
            update["main_desc_vi"] = vi
    doc = {"$set": update}
    if w.get("inherent_effects"):
        effects_with_vi = []
        for eff in w["inherent_effects"]:
            eff = dict(eff)
            vi = translate_effect_text(eff.get("desc"))
            if vi:
                eff["desc_vi"] = vi
            effects_with_vi.append(eff)
        doc["$addToSet"] = {"inherent_effects": {"$each": effects_with_vi}}
    await mdb[COL_WEAPON_TYPES].update_one({"_id": key}, doc, upsert=True)


async def save_weapon_instance(w, source_id=None):
    passive = w.get("passive") or {}
    passive_desc_vi = translate_effect_text(passive.get("desc"))
    await mdb[COL_WEAPON_INSTANCES].update_one(
        {"_id": w["id"]},
        {"$set": {
            "type_name": w["type_name"], "quality": w["quality"],
            "passive_name": passive.get("name"), "passive_desc": passive.get("desc"),
            "passive_desc_vi": passive_desc_vi,
            "owner_id": source_id, "updated_at": datetime.utcnow().isoformat(),
        }},
        upsert=True,
    )


async def save_passive(name, desc, source_id=None):
    if not name:
        return
    key = name.lower()
    await mdb[COL_PASSIVES].update_one(
        {"_id": key},
        {"$set": {"display_name": name, "description": desc,
                  "description_vi": translate_effect_text(desc),
                  "confirmed_at": datetime.utcnow().isoformat(), "confirmed_by": source_id}},
        upsert=True,
    )


async def save_team(team):
    await mdb[COL_TEAM].delete_many({})
    if team:
        docs = []
        for m in team:
            d = dict(m)
            d["_id"] = d["pos"]
            d["updated_at"] = datetime.utcnow().isoformat()
            docs.append(d)
        await mdb[COL_TEAM].insert_many(docs)


async def save_huntbot(h):
    h = dict(h)
    h["created_at"] = datetime.utcnow().isoformat()
    await mdb[COL_HUNTBOT].insert_one(h)


async def save_quest(q):
    q = dict(q)
    q["created_at"] = datetime.utcnow().isoformat()
    await mdb[COL_QUEST].insert_one(q)


async def save_daily(d):
    """Daily la 1 ban chup duy nhat, ghi de. Streak/phan thuong chi co trong tin
    "da nhan" — lan sau thay tin "chua toi gio" thi giu nguyen, khong xoa."""
    now = datetime.utcnow()
    fields = {"state": d["state"], "updated_at": now.isoformat()}
    if d.get("seconds_until_next") is not None:
        fields["ready_at"] = (now + timedelta(seconds=d["seconds_until_next"])).isoformat()
    if d.get("streak") is not None:
        fields["streak"] = d["streak"]
    if d.get("reward") is not None:
        fields["last_reward"] = d["reward"]
    await mdb[COL_DAILY].update_one({"_id": "latest"}, {"$set": fields}, upsert=True)


async def save_cowoncy(c, source_id=None):
    await mdb[COL_COWONCY].update_one(
        {"_id": "latest"},
        {"$set": {"amount": c["amount"], "updated_at": datetime.utcnow().isoformat(),
                  "updated_by": source_id}},
        upsert=True,
    )


# ----------------------------------------------------------------------
# LẮNG NGHE
# ----------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"[tracker] Đăng nhập: {bot.user} (discord.py {discord.__version__})")
    if mdb is None:
        print("[tracker] CẢNH BÁO: chưa có MONGODB_URI — bot sẽ lỗi khi cố lưu/đọc dữ liệu.")
        return
    tracked = await get_config("tracked_user_id")
    print(f"[tracker] Đang theo dõi user ID: {tracked or '(chưa đặt — dùng ,track)'}")

    global _automacro_api_started
    if AUTOMACRO_API_TOKEN:
        if not _automacro_api_started:
            _automacro_api_started = True
            asyncio.create_task(start_automacro_api_server())
    else:
        print("[tracker] Chưa đặt AUTOMACRO_API_TOKEN — API cho AutoMacro KHÔNG chạy (an toàn mặc định).")


DEFAULT_OWO_PREFIXES = ["owo"]


async def get_owo_prefixes():
    """Danh sách prefix OwO chấp nhận cho tracked user — OwO cho phép
    người chơi tự đặt prefix riêng (vd "o"), nên không thể hardcode 1
    giá trị duy nhất. Mặc định ["owo"], chỉnh qua ,setprefixes."""
    raw = await get_config("owo_prefixes")
    if not raw:
        return DEFAULT_OWO_PREFIXES
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


@bot.event
async def on_message(message: discord.Message):
    if mdb is None:
        await bot.process_commands(message)
        return

    tracked_id = await get_config("tracked_user_id")
    prefixes = await get_owo_prefixes()
    content_lower = message.content.lower()

    if tracked_id and str(message.author.id) == str(tracked_id) \
            and any(content_lower.startswith(p) for p in prefixes):
        pending_commands[message.channel.id] = time.time()
        last_owo_command[message.channel.id] = content_lower
        author = message.author
        tracked_names[str(author.id)] = {
            n for n in (getattr(author, "display_name", None), getattr(author, "global_name", None),
                        getattr(author, "nick", None), getattr(author, "name", None)) if n
        }
        await bot.process_commands(message)
        return

    if message.author.id == OWO_BOT_ID:
        last = pending_commands.get(message.channel.id)
        if last and (time.time() - last) < CORRELATION_WINDOW:
            pending_commands[message.channel.id] = time.time()
            await handle_owo_response(message, tracked_id)

    await bot.process_commands(message)


def _collect_component_text(comp, out):
    """Tin nhan kieu moi cua Discord (Components V2 — vd bang Quest Log co cac
    tab Daily/Weekly/Quests) khong nam trong content hay embed ma nam trong
    cac thanh phan long nhau (Container/Section/TextDisplay). Di het cay, lay
    moi doan chu."""
    content = getattr(comp, "content", None)
    if isinstance(content, str) and content:
        out.append(content)
    for child in (getattr(comp, "children", None) or []):
        _collect_component_text(child, out)
    accessory = getattr(comp, "accessory", None)
    if accessory is not None:
        _collect_component_text(accessory, out)


def flatten_message(message: discord.Message) -> str:
    text = message.content or ""
    for embed in message.embeds:
        if embed.title:
            text += "\n" + embed.title
        if embed.description:
            text += "\n" + embed.description
        for f in embed.fields:
            text += f"\n**{f.name}:** {f.value}"
        if embed.footer and embed.footer.text:
            text += "\n" + embed.footer.text
    parts = []
    for comp in (getattr(message, "components", None) or []):
        _collect_component_text(comp, parts)
    if parts:
        text += "\n" + "\n".join(parts)
    return text


async def handle_owo_response(message: discord.Message, source_id):
    text = flatten_message(message)
    if not text.strip():
        return

    pet = parse_owodex(text)
    if pet:
        await save_pet_species(pet, source_id)

    weapon = parse_weapon_detail(text)
    if weapon:
        # Chỉ ghi vũ khí của CHÍNH người đang theo dõi: owo weapon <ID> xem được cả
        # vũ khí của người khác (tiêu đề ghi tên chủ) — không được lẫn vào dữ liệu của bạn.
        names = set(tracked_names.get(str(source_id), set()))
        aliases = await get_config("weapon_owner_aliases", "") or ""
        names |= {a.strip() for a in aliases.split(",") if a.strip()}
        if weapon_owner_matches(weapon.get("owner"), names):
            await save_weapon_type(weapon, source_id)
            await save_weapon_instance(weapon, source_id)
            if weapon.get("passive"):
                await save_passive(weapon["passive"]["name"], weapon["passive"]["desc"], source_id)
            for eff in weapon.get("inherent_effects", []):
                await save_passive(eff["name"], eff["desc"], source_id)
        else:
            skipped_weapon["owner"], skipped_weapon["id"] = weapon.get("owner"), weapon["id"]
            print(f"[tracker] Bỏ qua vũ khí {weapon['id']}: chủ là '{weapon.get('owner')}', "
                  f"không khớp tên đang theo dõi {sorted(names)}")

    if "Lvl" in text and re.search(r"\[\d+\]", text):
        team = parse_team(text)
        if team:
            await save_team(team)

    hunt = parse_huntbot_status(text)
    if hunt:
        await save_huntbot(hunt)

    quest = parse_quest_status(text)
    if quest:
        await save_quest(quest)

    daily = parse_daily(text, last_owo_command.get(message.channel.id, ""))
    if daily:
        await save_daily(daily)

    cash = parse_cowoncy(text)
    if cash:
        await save_cowoncy(cash, source_id)

    await handle_zoo_text(message.channel.id, text, source_id)

    inv = parse_inventory(text)
    if inv:
        await save_inventory(inv, source_id)

    gem_status = parse_hunt_gem_status(text)
    if gem_status:
        vanished_slots = await save_gem_status(gem_status, source_id)
        for slot in vanished_slots:
            await remind_gem_replacement(message, slot, source_id)


async def remind_gem_replacement(message: discord.Message, slot: str, source_id):
    """Gem ở 1 slot vừa biến mất khỏi tin nhắn hunt (hết độ bền hoặc bị
    tháo) — tra inventory tìm các lựa chọn còn lại cùng slot, gợi ý đúng
    mã lệnh owo use. Không tự chọn hộ tier nào — liệt kê hết, để người
    dùng tự quyết."""
    cursor = mdb[COL_INVENTORY].find(
        {"is_gem": True, "gem_slot": slot, "count": {"$gt": 0}}
    ).sort("gem_tier_rank", 1)
    options = await cursor.to_list(length=10)

    if not options:
        await message.channel.send(
            f"<@{source_id}> ⚠️ Gem slot {slot} vừa hết, và trong kho không còn viên nào cùng slot để thay. "
            f"Cần farm/mua thêm."
        )
        return

    lines = [f"`owo use {o['_id']}` — {o['gem_tier']} (còn {o['count']})" for o in options]
    await message.channel.send(
        f"<@{source_id}> ⚠️ Gem slot {slot} vừa hết độ bền! Chọn 1 trong các lựa chọn còn lại:\n" + "\n".join(lines)
    )

    # Ghi 1 lenh cho AutoMacro tu dong thay - MAC DINH chon vien TIER THAP
    # NHAT con lai (options da sap xep tang dan, dung tier thap truoc de
    # danh tier cao cho luc can). Doi "options[0]" thanh "options[-1]"
    # neu muon uu tien dung tier CAO nhat khi thay tu dong.
    chosen = options[0]
    await queue_automacro_command("swap_gem", {
        "slot": slot,
        "item_code": chosen["_id"],
        "gem_tier": chosen["gem_tier"],
        "command_text": f"owo use {chosen['_id']}",
    })


# ----------------------------------------------------------------------
# LỆNH: theo dõi & trạng thái cá nhân
# ----------------------------------------------------------------------
def is_owner():
    async def predicate(ctx):
        return OWNER_ID and str(ctx.author.id) == str(OWNER_ID)
    return commands.check(predicate)


@bot.command(name="track")
@is_owner()
async def track(ctx, user: discord.User = None):
    if not user:
        await ctx.send("Dùng: `,track @user`")
        return
    await set_config("tracked_user_id", str(user.id))
    await ctx.send(f"Đã đặt theo dõi: **{user.name}** (`{user.id}`).")


@bot.command(name="setprefixes")
@is_owner()
async def setprefixes_cmd(ctx, *, prefixes: str = ""):
    """OwO cho phép đặt prefix riêng (vd 'o' thay vì 'owo') — bot cần
    biết chính xác bạn đang dùng prefix nào để nhận ra lệnh của bạn.
    Dùng: ,setprefixes owo,o"""
    if not prefixes:
        current = await get_owo_prefixes()
        await ctx.send(f"Đang nhận diện các prefix: {', '.join(f'`{p}`' for p in current)}\n"
                        f"Đổi bằng: `,setprefixes owo,o` (cách nhau bằng dấu phẩy)")
        return
    await set_config("owo_prefixes", prefixes)
    new_list = await get_owo_prefixes()
    await ctx.send(f"Đã cập nhật, giờ nhận diện: {', '.join(f'`{p}`' for p in new_list)}")


@bot.command(name="weaponowner")
@is_owner()
async def weaponowner_cmd(ctx, *, aliases: str = ""):
    """Bot chỉ ghi vũ khí có tên chủ khớp tên Discord của bạn (tự nhận từ mỗi lần bạn
    gõ lệnh owo). Nếu OwO ghi chủ bằng tên khác, thêm ở đây: ,weaponowner Tên1, Tên2
    Xoá hết tên thêm: ,weaponowner xoa"""
    if aliases.strip().lower() in ("xoa", "xóa", "clear"):
        await set_config("weapon_owner_aliases", "")
        await ctx.send("Đã xoá các tên chủ vũ khí thêm tay.")
        return
    if aliases.strip():
        await set_config("weapon_owner_aliases", aliases.strip())
    tracked = await get_config("tracked_user_id")
    auto = sorted(tracked_names.get(str(tracked), set()))
    extra = await get_config("weapon_owner_aliases", "") or ""
    lines = [f"Tên tự nhận từ Discord: {', '.join(f'`{n}`' for n in auto) or '(chưa có — hãy gõ 1 lệnh owo)'}",
             f"Tên thêm tay: {extra or '(không có)'}"]
    if skipped_weapon["owner"] is not None:
        lines.append(f"Vũ khí gần nhất bị bỏ qua: `{skipped_weapon['id']}` — chủ ghi là **{skipped_weapon['owner']}**")
    await ctx.send("\n".join(lines))


@bot.command(name="status")
async def status(ctx):
    tracked = await get_config("tracked_user_id")
    last_hunt = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])

    embed = discord.Embed(title="Trạng thái theo dõi", color=0xD9A227)
    embed.add_field(name="Đang theo dõi", value=f"<@{tracked}>" if tracked else "Chưa đặt — dùng `,track`", inline=False)
    if last_hunt:
        state = f"{last_hunt['progress_pct']}% · {last_hunt['animals_captured']} pet · còn {last_hunt['time_remaining']}" \
            if last_hunt["hunting"] else "Không đang hunt"
        embed.add_field(name="HuntBot", value=state, inline=False)
    await ctx.send(embed=embed)


@bot.command(name="huntbot")
async def huntbot_cmd(ctx):
    row = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])
    if not row:
        await ctx.send("Chưa có dữ liệu HuntBot.")
        return
    embed = discord.Embed(title="HuntBot", color=0x0F6E56)
    embed.add_field(name="Đang hunt", value="Có" if row["hunting"] else "Không")
    embed.add_field(name="Tiến độ", value=f"{row['progress_pct']}%")
    embed.add_field(name="Đã bắt", value=f"{row['animals_captured']} pet")
    embed.add_field(name="Còn lại", value=row["time_remaining"] or "—")
    embed.add_field(name="Animal Essence", value=row["essence"])
    await ctx.send(embed=embed)


@bot.command(name="quests")
async def quests_cmd(ctx):
    row = await mdb[COL_QUEST].find_one(sort=[("_id", -1)])
    if not row:
        await ctx.send("Chưa có dữ liệu quest.")
        return
    status_text = "Đã xong hết hôm nay" if row["all_done"] else "Còn quest chưa xong"
    await ctx.send(f"**Quest:** {status_text} · Seals: {row['seals']} · Kế tiếp: {row['next_quest'] or '—'}")


@bot.command(name="team")
async def team_cmd(ctx):
    cursor = mdb[COL_TEAM].find().sort("_id", 1)
    rows = await cursor.to_list(length=10)
    if not rows:
        await ctx.send("Chưa có dữ liệu đội hình.")
        return
    lines = [f"[{r['pos']}] **{emoji_to_name(r['name'])}** Lvl{r['level']} — HP{r['hp']} WP{r['wp']} "
             f"ATT{r['att']} MAG{r['mag']} · `{r['weaponId']}` {r['quality']}%" for r in rows]
    await ctx.send("\n".join(lines))


@bot.command(name="myweapons")
async def myweapons_cmd(ctx, *, search: str = ""):
    q = {"type_name": {"$regex": search, "$options": "i"}} if search else {}
    cursor = mdb[COL_WEAPON_INSTANCES].find(q).sort("updated_at", -1).limit(15)
    rows = await cursor.to_list(length=15)
    if not rows:
        await ctx.send("Chưa có vũ khí nào được ghi nhận.")
        return
    lines = [f"`{r['_id']}` **{r['type_name']}** {r['quality']}% — {r.get('passive_name') or 'chưa rõ passive'}"
             for r in rows]
    await ctx.send("\n".join(lines))


@bot.command(name="zoo")
async def zoo_cmd(ctx, *, search: str = ""):
    doc = await mdb[COL_ZOO].find_one({"_id": "latest"})
    if not doc:
        await ctx.send("Chưa có dữ liệu zoo. Gõ `owo zoo` trong kênh có bot để bot tự ghi nhận.")
        return
    pets = doc["pets"]
    if search:
        pets = [p for p in pets if search.lower() in p["name"].lower()]
    if not pets:
        await ctx.send("Không có pet nào khớp tìm kiếm trong zoo đã lưu.")
        return
    by_tier = {}
    for p in pets:
        by_tier.setdefault(p["tier"], []).append(p)
    chunks = []
    for tier, plist in by_tier.items():
        line = f"**{tier}**: " + ", ".join(f"{p['name']} ×{p['count']}" for p in plist)
        chunks.append(line)
    header = f"Zoo Points: **{doc.get('zoo_points','?')}**"
    if doc.get("breakdown_raw"):
        header += f" ({doc['breakdown_raw']})"
    text = header + "\n" + "\n".join(chunks)
    for i in range(0, len(text), 1900):
        await ctx.send(text[i:i + 1900])


@bot.command(name="inv")
async def inv_cmd(ctx, *, search: str = ""):
    q = {"name": {"$regex": search, "$options": "i"}} if search else {}
    cursor = mdb[COL_INVENTORY].find(q).sort("code", 1)
    rows = await cursor.to_list(length=100)
    if not rows:
        await ctx.send("Chưa có dữ liệu inventory. Gõ `owo inventory` trong kênh có bot để bot tự ghi nhận.")
        return
    lines = [f"`{r['_id']}` **{r['name']}** ×{r['count']}" for r in rows]
    text = "\n".join(lines)
    for i in range(0, len(text), 1900):
        await ctx.send(text[i:i + 1900])


@bot.command(name="gems")
async def gems_cmd(ctx):
    cursor = mdb[COL_GEM_STATUS].find().sort("_id", 1)
    rows = await cursor.to_list(length=10)
    if not rows:
        await ctx.send("Chưa ghi nhận tình trạng gem nào — bot cần thấy ít nhất 1 lần hunt để bắt đầu theo dõi.")
        return
    embed = discord.Embed(title="Tình trạng gem đang trang bị", color=0x2BC9C0)
    for r in rows:
        pct = round(r["current"] / r["max"] * 100) if r["max"] else 0
        embed.add_field(name=f"Slot {r['_id']} — {r['tier']}",
                         value=f"{r['current']}/{r['max']} ({pct}%)", inline=True)
    embed.set_footer(text="Slot biến mất khỏi tin hunt = hết độ bền, bot sẽ tự nhắc owo use.")
    await ctx.send(embed=embed)


@bot.command(name="automacro")
@is_owner()
async def automacro_cmd(ctx):
    """Xem cac lenh dang cho AutoMacro xu ly / da xu ly gan day - de kiem
    tra luong ket noi hoat dong dung khong."""
    pending = await mdb[COL_AUTOMACRO_COMMANDS].find({"status": "pending"}).sort("_id", 1).to_list(length=10)
    recent_done = await mdb[COL_AUTOMACRO_COMMANDS].find(
        {"status": {"$ne": "pending"}}
    ).sort("_id", -1).to_list(length=5)

    lines = [f"API cho AutoMacro: {'BẬT' if AUTOMACRO_API_TOKEN else 'TẮT (chưa đặt AUTOMACRO_API_TOKEN)'}"]
    lines.append(f"\n**Đang chờ ({len(pending)}):**")
    if pending:
        lines += [f"#{d['_id']} `{d['action']}` — {d['params'].get('command_text', d['params'])}" for d in pending]
    else:
        lines.append("(không có)")

    lines.append(f"\n**Vừa xử lý gần đây:**")
    if recent_done:
        lines += [f"#{d['_id']} `{d['action']}` — {d['status']}" for d in recent_done]
    else:
        lines.append("(chưa có)")

    await ctx.send("\n".join(lines))


# ----------------------------------------------------------------------
# LỆNH: ghi chú
# ----------------------------------------------------------------------
@bot.command(name="note")
async def note_cmd(ctx, action: str = "list", *, text: str = ""):
    if action == "add" and text:
        nid = await next_note_id()
        await mdb[COL_NOTES].insert_one({"_id": nid, "text": text, "done": False,
                                          "created_at": datetime.utcnow().isoformat()})
        await ctx.send(f"Đã thêm (#{nid}): {text}")
    elif action == "done" and text.isdigit():
        await mdb[COL_NOTES].update_one({"_id": int(text)}, {"$set": {"done": True}})
        await ctx.send("Đã đánh dấu xong.")
    else:
        cursor = mdb[COL_NOTES].find().sort([("done", 1), ("_id", 1)])
        rows = await cursor.to_list(length=100)
        if not rows:
            await ctx.send("Chưa có ghi chú nào. Dùng `,note add <nội dung>`.")
        else:
            lines = [f"{'✅' if r['done'] else '⬜'} `{r['_id']}` {r['text']}" for r in rows]
            await ctx.send("\n".join(lines))


# ----------------------------------------------------------------------
# LỆNH: pet species — xem/tra cứu + nhập tay khi cần
# ----------------------------------------------------------------------
@bot.command(name="pet", aliases=["dex"])
async def pet_cmd(ctx, *, name: str = ""):
    if not name:
        await ctx.send("Dùng: `,pet <tên>` (hoặc `,dex <tên>`)")
        return
    doc = await mdb[COL_PET_SPECIES].find_one({"_id": name.lower()})
    if not doc:
        await ctx.send(f"Chưa có dữ liệu cho `{name}`. Tra `owo owodex {name}` trong kênh có bot để tự ghi nhận, "
                        f"hoặc dùng `,petset` để nhập tay.")
        return

    rank_display = doc.get("rank_vi") or doc.get("rank", "—")
    embed = discord.Embed(
        title=doc["display_name"],
        description=doc.get("flavor_text"),
        color=0x9B6BC9,
    )
    embed.add_field(name="Rank", value=rank_display, inline=True)
    embed.add_field(name="Số đã bắt", value=doc.get("count_seen") or "—", inline=True)
    if doc.get("rarity_caught"):
        embed.add_field(name="Độ hiếm", value=f"{doc['rarity_caught']} đã từng bắt (toàn server)", inline=True)
    embed.add_field(
        name="Chỉ số",
        value=f"HP{doc['hp']} ATT{doc['att']} PR{doc['pr']} WP{doc['wp']} MAG{doc['mag']} MR{doc['mr']}",
        inline=False,
    )
    if doc.get("points") is not None:
        embed.add_field(name="Zoo Points", value=str(doc["points"]), inline=True)
    if doc.get("sell_cowoncy") is not None:
        embed.add_field(name="Bán", value=f"{doc['sell_cowoncy']} Cowoncy ({doc['sell_sold_count']} đã bán)", inline=True)
    else:
        embed.add_field(name="Bán", value="Không bán được", inline=True)
    if doc.get("sacrifice_essence") is not None:
        embed.add_field(name="Hy sinh", value=f"{doc['sacrifice_essence']} Essence ({doc['sacrifice_killed_count']} đã hy sinh)", inline=True)
    else:
        embed.add_field(name="Hy sinh", value="Không hy sinh được", inline=True)
    if doc.get("aliases"):
        embed.add_field(name="Alias", value=", ".join(doc["aliases"]), inline=False)
    embed.set_footer(text=f"Nguồn: {doc.get('source','—')} · xác nhận lúc {doc.get('confirmed_at','?')[:16]}")
    await ctx.send(embed=embed)


@bot.command(name="pets")
async def pets_cmd(ctx, *, search: str = ""):
    q = {"display_name": {"$regex": search, "$options": "i"}} if search else {}
    cursor = mdb[COL_PET_SPECIES].find(q).sort("display_name", 1).limit(25)
    rows = await cursor.to_list(length=25)
    if not rows:
        await ctx.send("Chưa ghi nhận pet nào khớp.")
        return
    lines = [f"**{r['display_name']}** ({r.get('rank','?')}) — "
             f"HP{r['hp']}/ATT{r['att']}/PR{r['pr']}/WP{r['wp']}/MAG{r['mag']}/MR{r['mr']}" for r in rows]
    await ctx.send("\n".join(lines))


@bot.command(name="petset")
async def petset_cmd(ctx, name: str, rank: str, hp: int, att: int, pr: int, wp: int, mag: int, mr: int):
    """Nhập tay 1 pet khi không có sẵn owodex — vd đọc từ nguồn khác.
    Dùng: ,petset <tên> <rank> <hp> <att> <pr> <wp> <mag> <mr>"""
    key = name.lower()
    await mdb[COL_PET_SPECIES].update_one(
        {"_id": key},
        {"$set": {"display_name": name, "rank": rank.capitalize(),
                  "hp": hp, "att": att, "pr": pr, "wp": wp, "mag": mag, "mr": mr,
                  "confirmed_at": datetime.utcnow().isoformat(),
                  "confirmed_by": str(ctx.author.id), "source": "manual"}},
        upsert=True,
    )
    await ctx.send(f"Đã lưu **{name}** ({rank}) — HP{hp}/ATT{att}/PR{pr}/WP{wp}/MAG{mag}/MR{mr}.")


# ----------------------------------------------------------------------
# LỆNH: weapon types — xem/tra cứu + nhập tay
# ----------------------------------------------------------------------
@bot.command(name="weapontype")
async def weapontype_cmd(ctx, *, name: str = ""):
    if not name:
        await ctx.send("Dùng: `,weapontype <tên>`")
        return
    doc = await mdb[COL_WEAPON_TYPES].find_one({"_id": name.lower()})
    if not doc:
        await ctx.send(f"Chưa có dữ liệu cho loại vũ khí `{name}`.")
        return
    desc = doc.get("main_desc_vi") or doc.get("main_desc", "—")
    embed = discord.Embed(title=doc["display_name"], description=desc, color=0x4C86D6)
    if doc.get("main_desc_vi") and doc.get("main_desc"):
        embed.add_field(name="Nguyên văn (EN)", value=doc["main_desc"], inline=False)
    effects = doc.get("inherent_effects", [])
    if effects:
        lines = [f"**{e['name']}**: {e.get('desc_vi') or e['desc']}" for e in effects]
        embed.add_field(name="Hiệu ứng cố định", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"Xác nhận lúc {doc.get('confirmed_at','?')[:16]}")
    await ctx.send(embed=embed)


@bot.command(name="weapontypes")
async def weapontypes_cmd(ctx, *, search: str = ""):
    q = {"display_name": {"$regex": search, "$options": "i"}} if search else {}
    cursor = mdb[COL_WEAPON_TYPES].find(q).sort("display_name", 1).limit(25)
    rows = await cursor.to_list(length=25)
    if not rows:
        await ctx.send("Chưa ghi nhận loại vũ khí nào khớp.")
        return
    await ctx.send("\n".join(
        f"**{r['display_name']}** — {r.get('main_desc_vi') or r.get('main_desc','(chưa rõ mô tả)')}" for r in rows
    ))


@bot.command(name="weapontypeset")
async def weapontypeset_cmd(ctx, name: str, *, desc: str):
    """Nhập/sửa tay mô tả 1 loại vũ khí. Dùng: ,weapontypeset <tên> <mô tả>"""
    key = name.lower()
    await mdb[COL_WEAPON_TYPES].update_one(
        {"_id": key},
        {"$set": {"display_name": name, "main_desc": desc,
                  "confirmed_at": datetime.utcnow().isoformat(), "confirmed_by": str(ctx.author.id)}},
        upsert=True,
    )
    await ctx.send(f"Đã lưu mô tả cho **{name}**.")


# ----------------------------------------------------------------------
# LỆNH: passives — xem/tra cứu + nhập tay
# ----------------------------------------------------------------------
@bot.command(name="passive")
async def passive_cmd(ctx, *, name: str = ""):
    if not name:
        await ctx.send("Dùng: `,passive <tên>`")
        return
    doc = await mdb[COL_PASSIVES].find_one({"_id": name.lower()})
    if not doc:
        await ctx.send(f"Chưa có dữ liệu cho passive `{name}`.")
        return
    if doc.get("description_vi"):
        await ctx.send(f"**{doc['display_name']}**\n{doc['description_vi']}\n-# EN: {doc['description']}")
    else:
        await ctx.send(f"**{doc['display_name']}**\n{doc['description']}")


@bot.command(name="passives")
async def passives_cmd(ctx, *, search: str = ""):
    q = {"display_name": {"$regex": search, "$options": "i"}} if search else {}
    cursor = mdb[COL_PASSIVES].find(q).sort("display_name", 1).limit(25)
    rows = await cursor.to_list(length=25)
    if not rows:
        await ctx.send("Chưa ghi nhận passive nào khớp.")
        return
    await ctx.send("\n".join(f"**{r['display_name']}** — {r.get('description_vi') or r['description']}" for r in rows))


@bot.command(name="passiveset")
async def passiveset_cmd(ctx, name: str, *, desc: str):
    """Nhập/sửa tay 1 passive. Dùng: ,passiveset <tên> <mô tả>"""
    await save_passive(name, desc, str(ctx.author.id))
    await ctx.send(f"Đã lưu passive **{name}**.")


@bot.command(name="ping")
async def ping_cmd(ctx):
    ms = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! `{ms}ms`")


@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="OwO Tracker — danh sách lệnh",
        description="Prefix: `,`",
        color=0xD9A227,
    )
    embed.add_field(
        name="Theo dõi cá nhân",
        value="`,track @user` (owner) · `,setprefixes owo,o` (owner) · `,status` · `,weaponowner` (owner) · "
              "`,huntbot` · `,quests` · `,team` · `,myweapons [tìm]` · "
              "`,zoo [tìm]` · `,inv [tìm]` · `,gems`",
        inline=False,
    )
    embed.add_field(
        name="Ghi chú",
        value="`,note add <text>` · `,note list` · `,note done <id>`",
        inline=False,
    )
    embed.add_field(
        name="Pet (loài)",
        value="`,pet <tên>` / `,dex <tên>` · `,pets [tìm]` · "
              "`,petset <tên> <rank> <hp> <att> <pr> <wp> <mag> <mr>`",
        inline=False,
    )
    embed.add_field(
        name="Loại vũ khí",
        value="`,weapontype <tên>` · `,weapontypes [tìm]` · `,weapontypeset <tên> <mô tả>`",
        inline=False,
    )
    embed.add_field(
        name="Passive",
        value="`,passive <tên>` · `,passives [tìm]` · `,passiveset <tên> <mô tả>`",
        inline=False,
    )
    embed.add_field(name="Khác", value="`,ping` · `,help` · `,debugnext` (owner) · `,automacro` (owner)", inline=False)
    embed.set_footer(text="Bot chỉ thấy được server đã mời nó vào — không tự theo dõi ở nơi khác.")
    await ctx.send(embed=embed)


# ----------------------------------------------------------------------
# DEBUG
# ----------------------------------------------------------------------
@bot.command(name="debugnext")
@is_owner()
async def debugnext(ctx):
    await ctx.send("Đang chờ tin nhắn OwO tiếp theo để in debug ra console...")

    def check(m):
        return m.author.id == OWO_BOT_ID

    try:
        msg = await bot.wait_for("message", check=check, timeout=30)
        print("=== DEBUG OwO MESSAGE ===")
        print("content:", repr(msg.content))
        for e in msg.embeds:
            print("embed:", e.to_dict())
        # Tin nhan kieu moi (vd Quest Log): chu nam trong components, khong phai content/embed
        for c in msg.components:
            try:
                print("component:", c.to_dict())
            except Exception as err:
                print("component (không in được):", repr(c), err)
        print("flatten_message (đúng chuỗi bot sẽ đem đi parse):", repr(flatten_message(msg)))
        await ctx.send("Đã in ra console.")
    except asyncio.TimeoutError:
        await ctx.send("Không thấy tin nhắn OwO nào trong 30 giây.")


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise SystemExit("Thiếu biến môi trường DISCORD_TOKEN.")
    if not MONGODB_URI:
        raise SystemExit("Thiếu biến môi trường MONGODB_URI.")
    if not OWNER_ID:
        print("[tracker] Cảnh báo: chưa đặt OWNER_ID — lệnh ,track sẽ luôn bị từ chối.")
    bot.run(DISCORD_TOKEN)
