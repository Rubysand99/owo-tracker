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

import io
import os
import re
import json
import time
import hmac
import uuid
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
COL_EMOJI = "owot_emoji_registry"
COL_RAW = "owot_raw_samples"
COL_BATTLE = "owot_battle_status"      # v17: chuoi battle moi nhat
COL_NEW_PETS = "owot_new_pets"          # v17: pet vua bat duoc ma chua co trong zoo
COL_ALERTS = "owot_alerts"              # v18: canh bao captcha cua OwO
COL_CHECKLIST = "owot_checklists"        # v26: checklist Daily / Weekly cua Quest Log

EMOJI_TAG = re.compile(r"<(a)?:(\w+):(\d+)>")

# Nhung pet/con vat OwO hien bang EMOJI CHUAN cua Discord (khong co ID rieng,
# vd :bee:) — khong the tai anh qua CDN nen anh xa sang ky tu Unicode that de
# app hien truc tiep, khong can tai mang.
EMOJI_UNICODE = {
    "bee": "🐝", "bug": "🐛", "snail": "🐌", "beetle": "🪲", "butterfly": "🦋",
    "baby_chick": "🐤", "mouse2": "🐁", "rooster": "🐓", "rabbit2": "🐇", "chipmunk": "🐿️",
    "sheep": "🐑", "pig2": "🐖", "cow2": "🐄", "dog2": "🐕", "cat2": "🐈",
    "crocodile": "🐊", "tiger2": "🐅", "penguin": "🐧", "elephant": "🐘", "whale": "🐋",
    "dragon": "🐉", "unicorn": "🦄", "snowman2": "⛄", "ghost": "👻", "dove": "🕊️",
}

emoji_registry_cache = {}  # ten -> {"id":..., "animated": bool} — nap 1 lan/hub, tranh truy van lai


def extract_emoji_tags(text):
    """Tim moi emoji tuy chinh <a?:ten:id> trong 1 doan chu. Tra ve list (ten, id, dong)."""
    return [(name, eid, bool(a)) for a, name, eid in EMOJI_TAG.findall(text or "")]


async def remember_emojis(text):
    """Ghi nho ID cua moi emoji tuy chinh xuat hien trong tin nhan, de dung lai
    sau nay (vd tier tag trong zoo/quest, gem trong hunt...). Khong ghi de neu
    da co (ID 1 emoji la co dinh, khong doi)."""
    for name, eid, animated in extract_emoji_tags(text):
        await mdb[COL_EMOJI].update_one(
            {"_id": name}, {"$setOnInsert": {"id": eid, "animated": animated}}, upsert=True)


async def load_emoji_cache():
    global emoji_registry_cache
    rows = await mdb[COL_EMOJI].find().to_list(length=2000)
    emoji_registry_cache = {r["_id"]: {"id": r["id"], "animated": r.get("animated", False)} for r in rows}


def resolve_emoji(name):
    """Tra ve du lieu hien icon cho 1 ten emoji: uu tien ID that (tai duoc anh
    that tu Discord), sau do ky tu Unicode co san, cuoi cung None (chua biet)."""
    if not name:
        return {}
    found = emoji_registry_cache.get(name)
    if found:
        return {"emoji_id": found["id"], "emoji_animated": found["animated"]}
    uni = EMOJI_UNICODE.get(name)
    if uni:
        return {"emoji": uni}
    return {}


pending_commands = {}  # channel_id -> timestamp gần nhất có lệnh owo từ tracked user
tracked_names = {}  # user_id (chuỗi) -> các tên Discord của người đó (ghi lại mỗi khi họ gõ lệnh owo)
# --- Theo doi phien farm (app = tay, bot = mat) ---
farm_watch = {
    "active": False,        # app bao dang farm (qua /alerts?farm=1)
    "last_seen": 0.0,       # lan cuoi app goi /alerts
    "last_reply_at": 0.0,   # lan cuoi OwO tra loi 1 lenh cua ban
    "last_command_at": 0.0, # lan cuoi ban (hoac app) go 1 lenh owo
    "lost_notified": False, # da bao "mat ket noi dien thoai" chua
    "silent_notified": False,  # da bao "OwO im lang" chua
    "resting": False,       # app dang nghi giai lao (khong go lenh) -> khong tinh la OwO im lang
}
LOST_PHONE_SECONDS = 180      # app im qua 3 phut khi dang farm -> bao
OWO_SILENT_SECONDS = 240      # dang farm ma OwO khong tra loi qua 4 phut -> bao
_notify_recent = {}           # text -> lan gui cuoi (chong spam tin nhac)
# Acc phu cua Ruby: luc farm bang acc chinh, Ruby thuong vao acc nay. Tin nhac ve huntbot gui DM vao day.
# Doi bang lenh ,setalt <id>.
ALT_USER_ID_DEFAULT = "1238687916176183409"
_farm_watchdog_task = None
# Cua so "dang cho Ruby nhap ma huntbot": mo khi OwO vua dua mat khau (hoac Ruby vua go owo hb <thoi gian>)
HB_PENDING_SECONDS = 600
hb_pending = {"amount": None, "at": 0.0}

# --- Chong spam lenh thay gem (AutoMacro) ---
GEM_PICK_HIGHEST_TIER = True   # thay gem: dung vien tier CAO nhat con trong kho (False = tier thap nhat)
GEM_KEEP_IF_COUNT_AT_MOST = 0  # 0 = luon dung tier CAO nhat con vien nao (Ruby khong muon giu lai mythic). Dat 5 neu muon de danh tier it vien
GEM_MISSING_CONFIRM = 2        # slot phai vang mat o 2 tin hunt LIEN TIEP moi tinh la gem het
SWAP_COOLDOWN_SECONDS = 180    # 1 slot vua duoc tao lenh thay thi 3 phut sau moi duoc tao lai
COMMAND_EXPIRE_SECONDS = 600   # lenh cho qua 10 phut = da cu (gem da doi), tu huy, khong gui nua
gem_missing_streak = {}        # slot -> so tin hunt lien tiep khong thay slot do

skipped_foreign = {"name": None, "count": 0}  # tin OwO bi bo qua vi ten khac ten ban (de ,status / ,weaponowner bao)
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
    if not key:
        # Ten toan emoji / ky hieu: khoa so sanh rong -> so nguyen van (khong phan biet hoa thuong)
        raw = (owner or "").strip().casefold()
        return bool(raw) and any((n or "").strip().casefold() == raw for n in names if n)
    return any(_name_key(n) == key for n in names if n)


def reply_target(message, tracked_id):
    """OwO co tra loi (reply) tin nao khong? 'khong_co' = khong co / khong doc duoc,
    'ban' = tra loi tin cua nguoi duoc theo doi, 'nguoi_khac' = tra loi tin cua nguoi khac."""
    ref = getattr(message, "reference", None)
    resolved = getattr(ref, "resolved", None) if ref else None
    author = getattr(resolved, "author", None)
    if author is None:
        return "khong_co"
    return "ban" if str(getattr(author, "id", "")) == str(tracked_id) else "nguoi_khac"


def speaker_name(text):
    """Ten nguoi choi o dong dau tin OwO: '**🌱 | Ruby**, hunt…' / '**| Ruby**, you currently…' -> 'Ruby'."""
    m = re.search(r"\*\*[^|\n*]{0,8}\|\s*([^*\n]+?)\s*\*\*", text or "")
    return clean_owner_name(m.group(1)) if m else None


def header_owner(text):
    """Ten chu trong tieu de zoo / kho: \"Ruby's zoo!\" , \"Ruby's Inventory\" -> 'Ruby'."""
    m = re.search(r"([^\n=*]+?)'s (?:zoo|Inventory)", text or "")
    return clean_owner_name(m.group(1)) if m else None


async def tracked_name_set(source_id):
    names = set(tracked_names.get(str(source_id), set()))
    aliases = await get_config("weapon_owner_aliases", "") or ""
    names |= {a.strip() for a in aliases.split(",") if a.strip()}
    return names


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
        pet_name, pet_id, pet_animated = name_m.group(1), None, False
        emoji_m = re.match(r"\s*<(a)?:(\w+):(\d+)>", block)
        if emoji_m:
            pet_animated, pet_name, pet_id = bool(emoji_m.group(1)), emoji_m.group(2), emoji_m.group(3)
        entry = {
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
    return {
        "traits": traits or None,
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


async def save_checklist(c):
    doc = {k: v for k, v in c.items() if k != "kind"}
    doc["updated_at"] = datetime.utcnow().isoformat()
    await mdb[COL_CHECKLIST].update_one({"_id": c["kind"]}, {"$set": doc}, upsert=True)


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
    entry_pattern = re.compile(r"(?:<(a)?:(\w+):(\d+)>|:(\w+):)([⁰¹²³⁴⁵⁶⁷⁸⁹]+)")

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
            animated, custom_name, custom_id, plain_name = m.group(1), m.group(2), m.group(3), m.group(4)
            name = custom_name or plain_name
            entry = {"tier": current_tier, "name": name, "count": decode_superscript_number(m.group(5))}
            if custom_id:
                entry["emoji_id"] = custom_id
                entry["emoji_animated"] = bool(animated)
            pets.append(entry)

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


def battle_owner_name(message):
    """Ten nguoi danh trong tin battle: embed author = 'Ruby goes into battle!' -> 'Ruby'.
    (flatten_message khong chua author nen phai lay rieng de khong nhan nham battle cua nguoi khac.)"""
    for e in getattr(message, "embeds", None) or []:
        author = getattr(e, "author", None)
        name = getattr(author, "name", None) if author else None
        if name:
            m = re.match(r"^(.*?)\s+goes into battle", name, re.I)
            if m:
                return clean_owner_name(m.group(1))
    return None


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


# ----------------------------------------------------------------------
# LƯU — tất cả upsert theo key tự nhiên (tên pet, tên loại vũ khí, tên
# passive, ID vũ khí) nên gọi lại nhiều lần không tạo bản trùng.
# ----------------------------------------------------------------------
ZOO_PART_WINDOW = 1800  # giay (30 phut): OwO gui tin 2 rat that thuong — co luc 1-2 giay,
                         # co luc gan 2 tieng, nen phai cho rong tay
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
    kind = None
    if is_header:
        merged = parse_zoo(text)
        kind = "zoo_1" if merged else None
        print(f"[tracker][zoo] tin co tieu de, {len(merged['pets']) if merged else 0} pet, "
              f"zoo_points={merged.get('zoo_points') if merged else None}")
    elif session:
        age = time.time() - session["ts"]
        if age < ZOO_PART_WINDOW:
            pets_so_far = session["data"]["pets"]
            part = parse_zoo(text, continuation=True, start_tier=pets_so_far[-1]["tier"] if pets_so_far else None)
            if part:
                merged = merge_zoo_parts(session["data"], part)
                kind = "zoo_2"
                print(f"[tracker][zoo] tin noi tiep (cach {age:.1f}s), ghep xong -> "
                      f"{len(merged['pets'])} pet, zoo_points={merged.get('zoo_points')}")
            else:
                # Chi bao khi tin nay TRONG GIONG zoo (co "Zoo Points" hoac dong pet co so mu) —
                # cua so cho la 30 phut nen moi tin owo khac (cash, daily...) cung roi vao day,
                # neu khong loc se spam log.
                looks_zoo = "Zoo Points" in text or bool(re.search(r"(?<!`)<a?:\w+:\d+>[⁰¹²³⁴⁵⁶⁷⁸⁹]", text))
                if looks_zoo:
                    print(f"[tracker][zoo] tin giong zoo toi trong cua so ({age:.1f}s) nhung parse_zoo khong "
                          f"nhan dien duoc dong dau la tier tag — bo qua. Dong dau: {text.splitlines()[:1]!r}")
        else:
            # Qua han cho — xoa phien de KHONG bao tin nay va moi tin owo khac sau do la
            # "toi qua muon" nua (tranh spam log). Chi in 1 lan luc dong phien.
            zoo_session.pop(channel_id, None)
            print(f"[tracker][zoo] phien cho tin noi tiep da qua {ZOO_PART_WINDOW}s ma khong "
                  f"thay tin nao hop le — dong phien (khong ghep duoc Zoo Points lan nay).")
    else:
        # Khong phai tieu de, cung khong co phien zoo nao dang cho — binh thuong (tin khac).
        pass
    if merged:
        zoo_session[channel_id] = {"ts": time.time(), "data": merged}
        await save_zoo(merged, source_id)
    return kind, merged


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
    # Pet nao da nam trong zoo thi khong con la "pet moi" nua
    try:
        names = [str(p["name"]).lower() for p in z["pets"] if p.get("name")]
        if names:
            await mdb[COL_NEW_PETS].delete_many({"_id": {"$in": names}})
    except Exception as e:
        print(f"[tracker][zoo] Khong don duoc danh sach pet moi: {e!r}")


INV_PART_WINDOW = 600  # giay: kho do dai nen OwO chia 2 tin; tin 2 khong co tieu de "Inventory"
inv_session = {}  # channel_id -> thoi diem tin kho gan nhat

# --- "Moi lan go owo inv = 1 lan chup moi" ---
# Truoc day bot chi them/cap nhat tung mon, KHONG BAO GIO xoa mon da het (gem F, star,
# crate da dung... nam lai mai). Gio moi lan chup (tin co tieu de + tin 2 neu co) duoc
# danh dau bang 1 snapshot id; sau khi cac tin da toi du, mon nao KHONG co trong lan
# chup moi se bi xoa.
INV_MIN_ITEMS = 3      # lan chup doc duoc it hon so mon nay -> coi nhu doc hong, KHONG xoa gi
INV_PRUNE_GRACE = 20   # giay cho tin 2 toi truoc khi xoa mon cu (moi tin toi lai tinh lai tu dau)
inv_snapshot = {}      # channel_id -> {"id": snapshot id hien tai, "count": so mon da doc duoc}
inv_prune_tasks = {}   # channel_id -> asyncio.Task dang cho de xoa mon cu


async def prune_inventory(snapshot_id):
    """Xoa moi mon khong thuoc lan chup `snapshot_id` (ke ca dong cu chua tung co snapshot_id).
    Tra ve so dong da xoa."""
    res = await mdb[COL_INVENTORY].delete_many({"snapshot_id": {"$ne": snapshot_id}})
    return res.deleted_count


async def _prune_later(channel_id, snapshot_id):
    try:
        await asyncio.sleep(INV_PRUNE_GRACE)
        snap = inv_snapshot.get(channel_id)
        # Co lan chup moi hon chen vao trong luc cho -> bo qua, lan chup moi tu lo.
        if not snap or snap["id"] != snapshot_id:
            return
        if snap["count"] < INV_MIN_ITEMS:
            print(f"[tracker] Kho chi doc duoc {snap['count']} mon (<{INV_MIN_ITEMS}) -> giu nguyen kho cu, khong xoa")
            return
        removed = await prune_inventory(snapshot_id)
        if removed:
            print(f"[tracker] Kho moi thay the kho cu: xoa {removed} mon khong con trong kho")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[tracker] Loi khi don kho cu: {e!r}")


def _schedule_prune(channel_id, snapshot_id):
    old = inv_prune_tasks.get(channel_id)
    if old and not old.done():
        old.cancel()
    inv_prune_tasks[channel_id] = asyncio.ensure_future(_prune_later(channel_id, snapshot_id))


async def handle_inventory_text(channel_id, text, source_id=None):
    """Tin co tieu de -> kho moi. Tin KHONG tieu de nhung toi ngay sau (trong INV_PART_WINDOW)
    va chi gom dong item -> phan tiep theo cua cung 1 kho. Tra ve (loai, ket qua) hoac (None, None)."""
    inv = parse_inventory(text)
    kind = "inventory"
    if not inv:
        ts = inv_session.get(channel_id)
        if ts is not None and time.time() - ts < INV_PART_WINDOW:
            inv = parse_inventory(text, continuation=True)
            kind = "inventory_2"
        elif ts is not None:
            inv_session.pop(channel_id, None)
    if not inv:
        return None, None
    inv_session[channel_id] = time.time()
    if kind == "inventory":
        inv_snapshot[channel_id] = {"id": uuid.uuid4().hex, "count": 0}
    elif channel_id not in inv_snapshot:
        # Tin 2 mo coi (khong biet tin 1 o dau): chi ghi them, tuyet doi khong xoa gi.
        await save_inventory(inv, source_id)
        return kind, inv
    snap = inv_snapshot[channel_id]
    snap["count"] += len(inv["items"])
    await save_inventory(inv, source_id, snapshot_id=snap["id"])
    _schedule_prune(channel_id, snap["id"])
    return kind, inv


async def save_inventory(inv, source_id=None, snapshot_id=None):
    """Mỗi item lưu riêng 1 document (khoá theo mã 3 số) — để dễ tra cứu
    từng item và để lệnh ,gems tìm đúng mã cho `owo use`.
    snapshot_id: dau cua lan chup kho hien tai (xem prune_inventory)."""
    for item in inv["items"]:
        doc = {**item, "updated_at": datetime.utcnow().isoformat(), "updated_by": source_id}
        if snapshot_id:
            doc["snapshot_id"] = snapshot_id
        await mdb[COL_INVENTORY].update_one(
            {"_id": item["code"]},
            {"$set": doc},
            upsert=True,
        )


async def save_gem_status(gs, source_id=None):
    """Luu tinh trang gem NGAY LUC HUNT - khoa theo slot (1/3/4...), ghi de ban cu.
    Tra ve cac slot da BIEN MAT DUOC XAC NHAN: phai vang mat o GEM_MISSING_CONFIRM tin
    hunt lien tiep (1 tin thieu gem co the do tin cua nguoi khac / doc sot, khong phai
    gem het that). Slot chi bi xoa khoi bang trang thai khi da xac nhan."""
    seen_slots = {g["slot"] for g in gs["gems"]}
    prev_cursor = mdb[COL_GEM_STATUS].find({})
    prev_docs = await prev_cursor.to_list(length=10)
    prev_slots = {d["_id"] for d in prev_docs}
    missing_now = prev_slots - seen_slots

    for slot in seen_slots:
        gem_missing_streak.pop(slot, None)
    confirmed = set()
    for slot in missing_now:
        gem_missing_streak[slot] = gem_missing_streak.get(slot, 0) + 1
        if gem_missing_streak[slot] >= GEM_MISSING_CONFIRM:
            confirmed.add(slot)
        else:
            print(f"[tracker][gem] slot {slot} khong thay trong tin hunt nay "
                  f"({gem_missing_streak[slot]}/{GEM_MISSING_CONFIRM}) - cho tin tiep theo de chac. "
                  f"Slot dang thay: {sorted(seen_slots)}")

    for g in gs["gems"]:
        await mdb[COL_GEM_STATUS].update_one(
            {"_id": g["slot"]},
            {"$set": {"tier": g["tier"], "emoji_name": g["emoji_name"],
                      "emoji_id": g.get("emoji_id"), "emoji_animated": g.get("emoji_animated", False),
                      "current": g["current"], "max": g["max"],
                      "updated_at": datetime.utcnow().isoformat(), "updated_by": source_id}},
            upsert=True,
        )
    for slot in confirmed:
        await mdb[COL_GEM_STATUS].delete_one({"_id": slot})
        gem_missing_streak.pop(slot, None)
    return confirmed


async def save_battle(b, source_id=None):
    """Chuoi battle: ghi de ban cu. best_streak = chuoi dai nhat bot tung thay."""
    prev = await mdb[COL_BATTLE].find_one({"_id": "latest"}) or {}
    best = max(prev.get("best_streak") or 0, b.get("streak") or 0)
    doc = {"result": b["result"], "turns": b["turns"], "xp": b["xp"],
           "streak": b["streak"] if b["streak"] is not None else prev.get("streak"), "best_streak": best,
           "updated_at": datetime.utcnow().isoformat(), "updated_by": source_id}
    if b["result"] == "lost" and (b.get("lost_streak") or 0) > 0:
        doc["last_lost_streak"] = b["lost_streak"]
    await mdb[COL_BATTLE].update_one({"_id": "latest"}, {"$set": doc}, upsert=True)


async def record_new_pets(found, source_id=None):
    """So loai thu trong tin hunt voi zoo da luu. Zoo co loai nao (KE CA so luong 0 = da bat,
    da hien te, van dung duoc de dung doi) thi KHONG phai pet moi. Chua co zoo -> tra None
    (khong du co so de noi pet nao moi). Tra ve danh sach ten pet moi xuat hien LAN DAU."""
    zoo_doc = await mdb[COL_ZOO].find_one({"_id": "latest"})
    if not zoo_doc or not zoo_doc.get("pets"):
        return None
    known = {p["name"].lower() for p in zoo_doc["pets"]}
    now_iso = datetime.utcnow().isoformat()
    first_time = []
    for a in found["animals"]:
        key = a["name"].lower()
        if key in known:
            continue
        sp = await mdb[COL_PET_SPECIES].find_one({"_id": key}) or {}
        prev = await mdb[COL_NEW_PETS].find_one({"_id": key})
        fields = {"name": a["name"], "last_found_at": now_iso, "updated_by": source_id,
                  "rank": sp.get("rank"), "rank_vi": sp.get("rank_vi")}
        if a.get("emoji_id"):
            fields["emoji_id"] = a["emoji_id"]
            fields["emoji_animated"] = a.get("emoji_animated", False)
        await mdb[COL_NEW_PETS].update_one(
            {"_id": key},
            {"$set": fields, "$inc": {"times_found": 1}, "$setOnInsert": {"first_found_at": now_iso}},
            upsert=True)
        if not prev:
            first_time.append(a["name"])
    cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
    await mdb[COL_NEW_PETS].delete_many({"last_found_at": {"$lt": cutoff}})
    if first_time:
        print(f"[tracker][hunt] PET MOI (chua co trong zoo): {', '.join(first_time)}")
    return first_time


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
    stale_cut = (datetime.utcnow() - timedelta(seconds=COMMAND_EXPIRE_SECONDS)).isoformat()
    await mdb[COL_AUTOMACRO_COMMANDS].update_many(
        {"status": "pending", "created_at": {"$lt": stale_cut}},
        {"$set": {"status": "expired", "completed_at": datetime.utcnow().isoformat()}},
    )
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
    cmd = await mdb[COL_AUTOMACRO_COMMANDS].find_one({"_id": cmd_id})
    await mdb[COL_AUTOMACRO_COMMANDS].update_one(
        {"_id": cmd_id},
        {"$set": {"status": status, "completed_at": datetime.utcnow().isoformat()}},
    )
    # Lenh thay gem da go xong -> tru 1 vien moi ma ra khoi kho (ban sao), de lan sau khong
    # chon lai dung ma cu khi chua kip go `owo inv`. `owo inv` that se ghi de lai cho dung.
    if cmd and cmd.get("action") == "swap_gem" and status == "done" and cmd.get("status") == "pending":
        codes = (cmd.get("params") or {}).get("item_codes") or (cmd.get("params") or {}).get("item_code") or ""
        for code in [c.strip() for c in str(codes).split(",") if c.strip()]:
            await mdb[COL_INVENTORY].update_one({"_id": code, "count": {"$gt": 0}}, {"$inc": {"count": -1}})
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
        icon = {"emoji_id": r["emoji_id"], "emoji_animated": r.get("emoji_animated", False)} if r.get("emoji_id") else {}
        equipped.append(_with_age({
            "slot": r["_id"], "tier": r.get("tier"),
            "current": r.get("current"), "max": mx, "percent": pct, **icon,
        }, r.get("updated_at"), now))
    spare = sorted(
        ({"code": r["_id"], "slot": r.get("gem_slot"), "tier": r.get("gem_tier"),
          "count": r.get("count"), "tier_rank": r.get("gem_tier_rank") or 0,
          **({"emoji_id": r["emoji_id"], "emoji_animated": r.get("emoji_animated", False)} if r.get("emoji_id") else {})}
         for r in spare_rows),
        key=lambda x: (x["slot"] or "", x["tier_rank"]),
    )
    # Gem dang dung lay tu tin owo hunt, gem du phong lay tu tin owo inv -> 2 nguon, 2 gio rieng.
    spare_latest = max((r.get("updated_at") or "" for r in spare_rows), default="") or None
    return {
        "equipped": equipped, "spare": spare,
        "spare_updated_at": _iso_z(spare_latest) if spare_latest else None,
        "spare_age_seconds": _age_seconds(spare_latest, now) if spare_latest else None,
    }


async def _hub_huntbot(now):
    row = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])
    if not row:
        return None
    observed = _parse_utc(row.get("status_at") or row.get("created_at"))
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
        "traits": row.get("traits"),
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
    quests = []
    for q in row.get("quests") or []:
        q = dict(q)
        q.update(resolve_emoji(q.get("rarity")))
        q["rewards"] = [dict(r, **resolve_emoji(r.get("item"))) for r in q.get("rewards") or []]
        quests.append(q)
    return _with_age({
        "seals": row.get("seals"), "all_done": bool(row.get("all_done")),
        "next_quest": next_text, "next_quest_seconds": next_seconds,
        "quests": quests,
    }, row.get("created_at"), now)


async def _hub_daily(now):
    doc = await mdb[COL_DAILY].find_one({"_id": "latest"})
    if not doc:
        return None
    ready = _parse_utc(doc.get("ready_at"))
    seconds_left = max(0, int((ready - now).total_seconds())) if ready else None
    return _with_age({
        "state": doc.get("state"), "streak": doc.get("streak"),
        "last_reward": doc.get("last_reward"), **resolve_emoji("cowoncy"),
        "ready_at": _iso_z(doc.get("ready_at")), "seconds_left": seconds_left,
    }, doc.get("updated_at"), now)


async def _hub_cowoncy(now):
    doc = await mdb[COL_COWONCY].find_one({"_id": "latest"})
    if not doc:
        return None
    return _with_age({"amount": doc.get("amount"), **resolve_emoji("cowoncy")}, doc.get("updated_at"), now)


async def _hub_team(now):
    rows = await mdb[COL_TEAM].find().sort("_id", 1).to_list(length=10)
    if not rows:
        return None
    members = []
    for r in rows:
        m = {k: r.get(k) for k in ("pos", "name", "level", "hp", "wp", "att", "mag", "pr", "mr",
                                   "weaponId", "quality", "emoji_id", "emoji_animated")}
        m["name"] = emoji_to_name(m["name"])
        if not m.get("emoji_id"):
            m.pop("emoji_id", None)
            m.pop("emoji_animated", None)
            m.update(resolve_emoji(m["name"]))
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
        t = by_tier.setdefault(p["tier"], {"species": 0, "total": 0, "sacrificed": 0})
        t["total"] += p.get("count", 0)
        t["species"] += 1  # loai nao da tung bat = da mo khoa, ke ca so luong 0
        if p.get("count", 0) <= 0:
            t["sacrificed"] += 1
    for tier_name, t in by_tier.items():
        t.update(resolve_emoji(tier_name))
    pets = []
    sacrificed_pets = []  # so luong 0 = da bat, da hien te het: VAN LA DA CO / DA MO KHOA
    for p in doc.get("pets", []):
        pet = dict(p)
        if "emoji_id" not in pet:
            pet.update(resolve_emoji(pet["name"]))
        if p.get("count", 0) <= 0:
            pet["sacrificed"] = True
            sacrificed_pets.append(pet)
        else:
            pets.append(pet)
    list_total = sum(t["total"] for t in by_tier.values())

    # So nho trong bang (chu so mu) = pet DANG CO. Dong cuoi (F-6, CP-16, ... C-478489) = so pet
    # DA BAT tu truoc toi nay (ban/hien te di van khong giam) — chi de tham khao, KHONG phai tong pet.
    breakdown = parse_zoo_breakdown(doc.get("breakdown_raw"))
    for tier, t in by_tier.items():
        if tier in breakdown:
            t["caught"] = breakdown[tier]
    return _with_age({
        "zoo_points": doc.get("zoo_points"), "breakdown_raw": doc.get("breakdown_raw"),
        "total_pets": list_total,
        "total_source": "list",
        "list_total": list_total,
        "caught_total": sum(breakdown.values()) if breakdown else None,
        "by_tier": by_tier, "pets": pets,
        "sacrificed_pets": sacrificed_pets,
        "unlocked_total": len(pets) + len(sacrificed_pets),
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


async def _hub_pet_dex(now):
    """So tay pet (owodex): MOI loai pet ban tung tra (`owo dex <ten>` / `odex <ten>`)
    it nhat 1 lan — bao gom CA loai ban CHUA co (chi can tra la biet). Loai nao
    chua bao gio tra thi KHONG co trong day (bot khong biet toan bo pet trong
    game, chi biet loai da duoc hoi)."""
    rows = await mdb[COL_PET_SPECIES].find().to_list(length=2000)
    if not rows:
        return None
    zoo_doc = await mdb[COL_ZOO].find_one({"_id": "latest"})
    # Co mat trong zoo (ke ca so luong 0 = da hien te het) = DA CO / DA MO KHOA.
    owned_counts = {p["name"].lower(): p.get("count", 0) for p in (zoo_doc or {}).get("pets", [])}

    species = []
    for r in rows:
        name = r["display_name"]
        icon = resolve_emoji(name)
        species.append({
            "name": name, "rank": r.get("rank"), "rank_vi": r.get("rank_vi"),
            "owned": name.lower() in owned_counts, "owned_count": owned_counts.get(name.lower()),
            "sacrificed": owned_counts.get(name.lower()) == 0,
            "hp": r.get("hp"), "att": r.get("att"), "pr": r.get("pr"),
            "wp": r.get("wp"), "mag": r.get("mag"), "mr": r.get("mr"),
            "flavor_text": r.get("flavor_text"), "rarity_caught": r.get("rarity_caught"),
            "points": r.get("points"), "sell_cowoncy": r.get("sell_cowoncy"),
            "sell_sold_count": r.get("sell_sold_count"), "sacrifice_essence": r.get("sacrifice_essence"),
            "sacrifice_killed_count": r.get("sacrifice_killed_count"),
            **icon,
        })
    species.sort(key=lambda p: (not p["owned"], (p["rank"] or "").lower(), p["name"].lower()))
    latest_confirmed = max((r.get("confirmed_at") or "" for r in rows), default=None) or None
    return _with_age({
        "total_known": len(species), "total_owned": sum(1 for p in species if p["owned"]),
        "species": species,
    }, latest_confirmed, now)


async def _hub_battle(now):
    doc = await mdb[COL_BATTLE].find_one({"_id": "latest"})
    if not doc:
        return None
    out = {k: doc.get(k) for k in ("result", "turns", "xp", "streak", "best_streak", "last_lost_streak")}
    return _with_age(out, doc.get("updated_at"), now)


async def _hub_new_pets(now):
    rows = await mdb[COL_NEW_PETS].find().sort("last_found_at", -1).to_list(length=30)
    pets = []
    for r in rows:
        pet = {"name": r.get("name") or r["_id"], "rank": r.get("rank"), "rank_vi": r.get("rank_vi"),
               "times_found": r.get("times_found"),
               "first_found_at": _iso_z(r.get("first_found_at")), "last_found_at": _iso_z(r.get("last_found_at"))}
        if r.get("emoji_id"):
            pet["emoji_id"] = r["emoji_id"]
            pet["emoji_animated"] = r.get("emoji_animated", False)
        else:
            pet.update(resolve_emoji(pet["name"]))
        pets.append(pet)
    return {"pets": pets}


async def notify_owner(text: str, dm: bool = True, min_gap: int = 90, target: str = "owner", images=None):
    """Nhan tin TAG ban trong kenh duoc theo doi (+ DM neu duoc) de dien thoai/may khac cua ban cung bao.
    Cung noi dung trong min_gap giay thi chi gui 1 lan (chong spam)."""
    now = time.time()
    last = _notify_recent.get(text, 0)
    if now - last < min_gap:
        return False
    _notify_recent[text] = now
    if target == "alt":
        alt_id = await get_config("alt_user_id", ALT_USER_ID_DEFAULT)
        if await dm_user(alt_id, text, images):
            return True
        print("[tracker][notify] Khong DM duoc acc phu - chuyen sang bao acc chinh")
        text = "(Không DM được acc phụ) " + text
        if images:
            text += "\n🖼️ " + "  ".join(images)
    tid = await get_config("tracked_user_id")
    cid = await get_config("tracked_channel_id")
    sent = False
    if cid:
        try:
            ch = bot.get_channel(int(cid)) or await bot.fetch_channel(int(cid))
            mention = f"<@{tid}> " if tid else ""
            await ch.send(f"{mention}{text}")
            sent = True
        except Exception as e:
            print(f"[tracker][notify] Khong nhan duoc vao kenh: {e!r}")
    if dm and tid:
        try:
            user = bot.get_user(int(tid)) or await bot.fetch_user(int(tid))
            await user.send(text)
            sent = True
        except Exception as e:
            print(f"[tracker][notify] Khong DM duoc (bo qua): {e!r}")
    return sent


async def dm_user(user_id, text: str, images=None) -> bool:
    """DM 1 tai khoan, co the kem anh (hien ngay trong DM, khong can bam link).
    Chi duoc khi tai khoan do CHUNG SERVER voi bot va cho phep nhan tin rieng tu thanh vien server."""
    if not user_id:
        return False
    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
    except Exception as e:
        print(f"[tracker][notify] Khong tim thay {user_id}: {e!r}")
        return False
    if images:
        try:
            embeds = []
            for url in images[:2]:
                em = discord.Embed(color=0xFFD54F)
                em.set_image(url=url)
                embeds.append(em)
            await user.send(content=text, embeds=embeds)
            return True
        except Exception as e:
            print(f"[tracker][notify] Gui kem anh loi ({e!r}) - gui dang link")
            text = text + "\n🖼️ " + "  ".join(images)
    try:
        await user.send(text)
        return True
    except Exception as e:
        print(f"[tracker][notify] Khong DM duoc {user_id}: {e!r}")
        return False


async def handle_post_notify(request: web.Request):
    """App bao bot nhan tin cho Ruby (vd farm bi dung vi loi). Body: {"text": "..."}"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = str(body.get("text") or "").strip()[:400]
    if not text:
        return web.json_response({"error": "empty"}, status=400)
    target = "alt" if str(body.get("target") or "") == "alt" else "owner"
    ok = await notify_owner("📱 " + text, dm=True, target=target)
    return web.json_response({"ok": bool(ok)})


async def farm_watchdog():
    """Chay nen: canh chung khi app dang farm. Bao Ruby neu dien thoai mat ket noi hoac OwO im lang."""
    while True:
        try:
            await asyncio.sleep(30)
            if not farm_watch["active"]:
                continue
            now = time.time()
            quiet_phone = now - farm_watch["last_seen"]
            if quiet_phone > LOST_PHONE_SECONDS:
                if not farm_watch["lost_notified"]:
                    farm_watch["lost_notified"] = True
                    mins = int(quiet_phone // 60)
                    await notify_owner(f"📵 Mất kết nối với điện thoại đang farm hơn {mins} phút "
                                       f"(hết pin / mất mạng / app bị tắt?). Kiểm tra giúp mình nhé.")
                continue
            farm_watch["lost_notified"] = False
            if farm_watch["resting"]:
                continue
            reply_age = now - farm_watch["last_reply_at"] if farm_watch["last_reply_at"] else None
            if reply_age is not None and reply_age > OWO_SILENT_SECONDS:
                if not farm_watch["silent_notified"]:
                    farm_watch["silent_notified"] = True
                    await notify_owner(f"⚠️ App đang farm nhưng đã {int(reply_age // 60)} phút không thấy OwO trả lời. "
                                       f"Có thể bị chặn / Discord mất kênh / OwO lỗi.")
            else:
                farm_watch["silent_notified"] = False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[tracker][watchdog] Loi: {e!r}")


# ----------------------------------------------------------------------
# CAPTCHA: OwO nghi ban spam -> bot (mat) bao cho app (tay) DUNG ngay + reo chuong
# ----------------------------------------------------------------------
CAPTCHA_ACTIVE_SECONDS = 12 * 60   # OwO cho 10 phut; qua 12 phut thi tu coi la het hieu luc
_ZERO_WIDTH_RE = re.compile("[\u200b-\u200f\u2060\ufeff]")
_CAPTCHA_PHRASES = (
    "are you a real human",
    "complete this within 10 minutes",
    "complete your captcha",
    "use the link below so i can check",
)
_CAPTCHA_SOLVED_RE = re.compile(r"(verified|you are human|you're human)[^\n]{0,80}thank", re.I)


def normalize_alert_text(text: str) -> str:
    """Bo ky tu vo hinh (zero-width), gop khoang trang, chu thuong - de so khop cau canh bao."""
    t = _ZERO_WIDTH_RE.sub("", text or "")
    return re.sub(r"\s+", " ", t).strip().lower()


def is_captcha_text(text: str) -> bool:
    norm = normalize_alert_text(text)
    return any(ph in norm for ph in _CAPTCHA_PHRASES)


def is_captcha_solved_text(text: str) -> bool:
    return bool(_CAPTCHA_SOLVED_RE.search(normalize_alert_text(text)))


async def captcha_addressed_to_tracked(message, text: str, tracked_id) -> bool:
    """Canh bao captcha nay la goi BAN? Chua biet ban la ai -> coi la cua ban (thà dung nham con hon bo sot)."""
    if not tracked_id:
        return True
    tid = str(tracked_id)
    raw = _ZERO_WIDTH_RE.sub("", text or "")
    if f"<@{tid}>" in raw or f"<@!{tid}>" in raw:
        return True
    if any(str(getattr(u, "id", "")) == tid for u in (getattr(message, "mentions", None) or [])):
        return True
    if reply_target(message, tracked_id) == "ban":
        return True
    names = await tracked_name_set(tracked_id)
    low = normalize_alert_text(raw)
    if any(n and n.lower() in low for n in names):
        return True
    # tin co nhac 1 nguoi KHAC (khong phai ban) -> la captcha cua nguoi khac
    return not re.search(r"<@!?\d+>", raw)


def _collect_component_media_urls(comp, out):
    """Anh trong tin kieu moi (Components V2): MediaGallery.items[].media.url, Thumbnail.media.url..."""
    media = getattr(comp, "media", None)
    u = getattr(media, "url", None)
    if isinstance(u, str) and u.startswith("http"):
        out.append(u)
    for item in (getattr(comp, "items", None) or []):
        _collect_component_media_urls(item, out)
    for child in (getattr(comp, "children", None) or []):
        _collect_component_media_urls(child, out)
    accessory = getattr(comp, "accessory", None)
    if accessory is not None:
        _collect_component_media_urls(accessory, out)


def find_message_image_urls(message):
    """Moi duong link anh trong tin: tep dinh kem, anh trong embed, anh trong thanh phan."""
    urls = []
    for a in (getattr(message, "attachments", None) or []):
        ct = (getattr(a, "content_type", None) or "").lower()
        name = (getattr(a, "filename", "") or "").lower()
        if ct.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            if getattr(a, "url", None):
                urls.append(a.url)
    for e in (getattr(message, "embeds", None) or []):
        for part in (getattr(e, "image", None), getattr(e, "thumbnail", None)):
            u = getattr(part, "url", None)
            if u:
                urls.append(u)
    for comp in (getattr(message, "components", None) or []):
        _collect_component_media_urls(comp, urls)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:2]


async def check_hb_password_message(message, tracked_id):
    """OwO dua MAT KHAU huntbot (anh) khi go `owo hb <so> `: chuyen anh sang DM acc phu de Ruby TU DOC.
    Bot KHONG doc anh va KHONG giai ma. Ruby doc ma roi nhan lai dung ma do trong DM de app go giup."""
    text = flatten_message(message)
    if "password" not in normalize_alert_text(text):
        return
    if not await captcha_addressed_to_tracked(message, text, tracked_id):
        return
    images = find_message_image_urls(message)
    lines = ["hb",
             "🔐 Mật khẩu huntbot — bạn đọc rồi nhắn lại đúng mã ở đây, ví dụ `abczyx` "
             "(hoặc `24h abczyx` nếu muốn đổi thời gian). Mã hết hạn nhanh!"]
    if not images:
        lines.append("(Không lấy được ảnh — mở tin gốc bên dưới để xem)")
    jump = getattr(message, "jump_url", None)
    if jump:
        lines.append(f"💬 Tin gốc: {jump}")
    open_hb_window(hb_pending["amount"])
    await record_raw("hb_password", text, {"images": images}, message)
    await notify_owner("\n".join(lines), min_gap=45, target="alt", images=images)


def _collect_component_urls(comp, out):
    url = getattr(comp, "url", None)
    if isinstance(url, str) and url.startswith("http"):
        out.append(url)
    for child in (getattr(comp, "children", None) or []):
        _collect_component_urls(child, out)
    accessory = getattr(comp, "accessory", None)
    if accessory is not None:
        _collect_component_urls(accessory, out)


def find_captcha_links(message, text: str):
    """Lay link giai captcha trong tin cua OwO (nut bam, embed hoac chu thuong). Toi da 2 link."""
    urls = []
    for comp in (getattr(message, "components", None) or []):
        _collect_component_urls(comp, urls)
    for e in (getattr(message, "embeds", None) or []):
        if getattr(e, "url", None):
            urls.append(e.url)
    urls += re.findall(r"https?://[^\s<>)\]]+", _ZERO_WIDTH_RE.sub("", text or ""))
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:2]


async def check_captcha_message(message, tracked_id):
    """Goi voi MOI tin cua OwO trong kenh duoc theo doi (khong can doi ban vua go lenh)."""
    text = flatten_message(message)
    if not text.strip():
        return
    if is_captcha_text(text):
        if not await captcha_addressed_to_tracked(message, text, tracked_id):
            print("[tracker][captcha] Canh bao captcha cua nguoi khac - bo qua")
            return
        now_iso = datetime.utcnow().isoformat()
        await mdb[COL_ALERTS].update_one(
            {"_id": "captcha"},
            {"$set": {"active": True, "at": now_iso, "cleared_at": None}},
            upsert=True)
        print("[tracker][captcha] !!! OwO DOI CAPTCHA - bao app dung farm + reo chuong")
        await record_raw("captcha", text, {"active": True}, message)
        links = find_captcha_links(message, text)
        lines = ["🚨 OwO đang đòi CAPTCHA! Giải trong 10 phút kẻo bị ban."]
        if links:
            lines.append("🔗 Link giải: " + "  ".join(links))
        jump = getattr(message, "jump_url", None)
        if jump:
            lines.append(f"💬 Mở tin OwO: {jump}")
        lines.append("Giải xong gõ `,captcha clear` rồi bấm Bắt đầu farm lại trong app.")
        await notify_owner("\n".join(lines), min_gap=120)
    elif is_captcha_solved_text(text):
        doc = await mdb[COL_ALERTS].find_one({"_id": "captcha"})
        if doc and doc.get("active"):
            await mdb[COL_ALERTS].update_one(
                {"_id": "captcha"},
                {"$set": {"active": False, "cleared_at": datetime.utcnow().isoformat()}})
            print("[tracker][captcha] OwO xac nhan da giai captcha - het canh bao")


async def get_captcha_state(now=None):
    """{'active': bool, 'at': iso, 'age_seconds': n}. Qua CAPTCHA_ACTIVE_SECONDS thi tu het hieu luc."""
    now = now or datetime.utcnow()
    doc = await mdb[COL_ALERTS].find_one({"_id": "captcha"}) or {}
    at = doc.get("at")
    age = _age_seconds(at, now) if at else None
    active = bool(doc.get("active")) and age is not None and age < CAPTCHA_ACTIVE_SECONDS
    return {"active": active, "at": _iso_z(at), "age_seconds": age}


async def handle_get_alerts(request: web.Request):
    """App goi moi vai giay khi dang farm: nhe, chi tra canh bao captcha."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    flag = request.query.get("farm")
    now = time.time()
    if flag in ("1", "2"):
        was_resting = farm_watch["resting"]
        farm_watch["active"] = True
        farm_watch["last_seen"] = now
        farm_watch["resting"] = (flag == "2")      # 2 = dang nghi giai lao
        if was_resting and flag == "1":
            farm_watch["last_reply_at"] = now       # vua nghi xong: tinh moc im lang lai tu dau
            farm_watch["silent_notified"] = False
    elif flag == "0":
        farm_watch["active"] = False
        farm_watch["resting"] = False
        farm_watch["lost_notified"] = False
        farm_watch["silent_notified"] = False
    reply_age = int(now - farm_watch["last_reply_at"]) if farm_watch["last_reply_at"] else None
    cmd_age = int(now - farm_watch["last_command_at"]) if farm_watch["last_command_at"] else None
    return web.json_response({
        "captcha": await get_captcha_state(),
        "activity": {"last_reply_age_seconds": reply_age, "last_command_age_seconds": cmd_age},
    })


async def _hub_checklists(now):
    out = {}
    for kind in ("daily", "weekly"):
        doc = await mdb[COL_CHECKLIST].find_one({"_id": kind})
        if doc:
            body = {k: doc.get(k) for k in ("items", "progress", "resets_at_epoch")}
            body["kind"] = kind
            out[kind] = _with_age(body, doc.get("updated_at"), now)
    return out or None


async def _hub_channel():
    """Kenh duoc chi dinh bang ,setchannel -> link Discord de app tu mo dung kenh.
    Link dang https://discord.com/channels/<server>/<kenh>. Chua dat kenh hoac bot khong
    nhin thay kenh (khong biet server) -> null."""
    cid = await get_config("tracked_channel_id")
    if not cid:
        return None
    out = {"id": str(cid), "link": None, "name": None}
    try:
        ch = bot.get_channel(int(cid))
        if ch is not None:
            out["name"] = getattr(ch, "name", None)
            guild = getattr(ch, "guild", None)
            if guild is not None:
                out["link"] = f"https://discord.com/channels/{guild.id}/{cid}"
            else:  # tin nhan rieng (DM)
                out["link"] = f"https://discord.com/channels/@me/{cid}"
    except Exception as e:
        print(f"[tracker] Khong lay duoc link kenh: {e!r}")
    return out


async def build_hub(now=None):
    """Gom du lieu cho man hinh Hub. Muc nao bot chua tung thay thi = null."""
    now = now or datetime.utcnow()
    await load_emoji_cache()
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
        "pet_dex": await _hub_pet_dex(now),
        "battle": await _hub_battle(now),
        "new_pets": await _hub_new_pets(now),
        "channel": await _hub_channel(),
        "captcha": await get_captcha_state(now),
        "checklists": await _hub_checklists(now),
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
    app.router.add_get("/alerts", handle_get_alerts)
    app.router.add_post("/notify", handle_post_notify)
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
    """OwO tra 2 tin cho `owo hb`: (1) trang THONG TIN co chi so nang cap + essence (hunting=False vi
    khong noi gi ve dang san), (2) tin TRANG THAI ('STILL HUNTING... BACK IN 19H 41M'). Truoc day moi tin la
    1 dong rieng nen Hub nhay qua lai giua 2 loai. Gio gop thanh 1 ban ghi: tin nao den thi chi cap nhat
    phan cua minh, phan con lai giu nguyen tu ban ghi truoc."""
    h = dict(h)
    now_iso = datetime.utcnow().isoformat()
    prev = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)]) or {}
    row = {k: v for k, v in prev.items() if k != "_id"}
    traits = h.get("traits")
    if h.get("essence") is not None:
        row["essence"] = h["essence"]
    if traits:                       # trang thong tin: chi cap nhat chi so + essence
        row["traits"] = traits
    else:                            # tin trang thai: cap nhat dang san / tien do / thoi gian con lai
        for k in ("hunting", "progress_pct", "animals_captured", "time_remaining"):
            row[k] = h.get(k)
        row["status_at"] = now_iso   # thoi diem QUAN SAT trang thai (de tinh gio xong cho dung)
    row["created_at"] = now_iso
    await mdb[COL_HUNTBOT].insert_one(row)


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

    global _farm_watchdog_task
    if _farm_watchdog_task is None or _farm_watchdog_task.done():
        _farm_watchdog_task = asyncio.create_task(farm_watchdog())

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
async def on_raw_message_edit(payload):
    """Bam tab Daily/Weekly/Quests trong Quest Log la SUA tin cu chu khong gui tin moi. Doc lai tin da sua
    de co du lieu checklist Weekly va tab Quests (khong can ban go lai owo quest)."""
    try:
        if mdb is None:
            return
        data = payload.data or {}
        author_id = (data.get("author") or {}).get("id")
        if str(author_id) != str(OWO_BOT_ID):
            return
        tracked_channel_id = await get_config("tracked_channel_id")
        if tracked_channel_id and str(payload.channel_id) != str(tracked_channel_id):
            return
        channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        text = flatten_message(message)
        checklist = parse_checklist(text)
        if checklist:
            await save_checklist(checklist)
            await record_raw("checklist", text, checklist, message)
            return
        quest = parse_quest_status(text)
        if quest and quest.get("quests"):
            await save_quest(quest)
            await record_raw("quest", text, quest, message)
    except Exception as e:
        print(f"[tracker][edit] Loi doc tin da sua: {e!r}")


@bot.event
async def on_message(message: discord.Message):
    if mdb is None:
        await bot.process_commands(message)
        return

    # Tin nhan RIENG (DM) cho bot: Ruby gui ma huntbot sau khi tu doc anh
    if message.guild is None and not message.author.bot:
        try:
            if await handle_hb_code_dm(message):
                return
        except Exception as e:
            print(f"[tracker][hb] Loi xu ly ma huntbot qua DM: {e!r}")

    # Gioi han hoat dong vao 1 kenh duy nhat (,setchannel) — neu dat, bo qua
    # HOAN TOAN moi kenh khac (khong theo doi lenh owo, khong doc tin OwO o
    # do). Lenh cua chinh bot nay (,status, ,setchannel, ,debugnext...) van
    # chay duoc o moi kenh, vi do la lenh quan tri, khong phai theo doi OwO.
    tracked_channel_id = await get_config("tracked_channel_id")
    if tracked_channel_id and str(message.channel.id) != str(tracked_channel_id):
        await bot.process_commands(message)
        return

    tracked_id = await get_config("tracked_user_id")
    prefixes = await get_owo_prefixes()
    content_lower = message.content.lower()

    if tracked_id and str(message.author.id) == str(tracked_id) \
            and any(content_lower.startswith(p) for p in prefixes):
        pending_commands[message.channel.id] = time.time()
        farm_watch["last_command_at"] = time.time()
        mt = _HB_TYPED_RE.match(content_lower.strip())
        if mt:
            open_hb_window(mt.group(1))
        last_owo_command[message.channel.id] = content_lower
        author = message.author
        tracked_names[str(author.id)] = {
            n for n in (getattr(author, "display_name", None), getattr(author, "global_name", None),
                        getattr(author, "nick", None), getattr(author, "name", None)) if n
        }
        await bot.process_commands(message)
        return

    if message.author.id == OWO_BOT_ID:
        try:
            await check_captcha_message(message, tracked_id)
        except Exception as e:  # khong de loi o day lam hong luong doc tin con lai
            print(f"[tracker][captcha] Loi kiem tra captcha: {e!r}")
        try:
            await check_hb_password_message(message, tracked_id)
        except Exception as e:
            print(f"[tracker][hb] Loi chuyen mat khau huntbot: {e!r}")

    if message.author.id == OWO_BOT_ID and reply_target(message, tracked_id) == "nguoi_khac":
        # Chac chan OwO dang tra loi tin cua NGUOI KHAC -> bo qua, du loai tin nao (team, quest, ...)
        print("[tracker] Bo qua tin OwO tra loi nguoi khac (reply)")
    elif message.author.id == OWO_BOT_ID:
        last = pending_commands.get(message.channel.id)
        if last and (time.time() - last) < CORRELATION_WINDOW:
            # KHONG gia han cua so khi OwO tra loi: neu gia han, tin OwO tra loi nguoi KHAC
            # trong cung kenh se bi tinh la cua ban (gem, tien, zoo cua nguoi do lan vao du lieu).
            farm_watch["last_reply_at"] = time.time()
            await handle_owo_response(message, tracked_id)
        elif _continuation_open(message.channel.id):
            await handle_continuation_only(message, tracked_id)

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


# ----------------------------------------------------------------------
# MAU THO: luu NGUYEN VAN moi loai tin nhan OwO moi nhat + ket qua bot doc
# duoc, de doi chieu do chinh xac (lenh ,rawdump gui ra 1 file). Day chi la
# ban ghi de kiem tra — khong anh huong du lieu Hub.
# ----------------------------------------------------------------------
RAW_MAX_CHARS = 12000
UNRECOGNIZED_KEEP = 12

# Cac loai tin nhan bot biet doc, va lenh OwO nguoi choi can go de bot thay no.
RAW_EXPECTED = {
    "hunt_gems": "owo hunt",
    "hunt_found": "owo hunt",
    "battle": "owo battle",
    "checklist": "owo q",
    "inventory": "owo inv",
    "zoo_1": "owo zoo",
    "zoo_2": "owo zoo (tin thu 2 — OwO chia bang zoo lam 2 tin)",
    "team": "owo team",
    "quest": "owo quest",
    "daily": "owo daily",
    "huntbot": "owo hb",
    "cowoncy": "owo cash",
    "weapon": "owo weapon <ID vu khi cua ban>",
}


def _json_safe(value):
    """Doi ket qua doc duoc sang dang luu/xuat JSON duoc (kieu la -> chuoi)."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


async def record_raw(kind, text, parsed, message, extra=None):
    """Moi loai 1 ban, ban moi ghi de ban cu."""
    body = text or ""
    doc = {
        "raw": body[:RAW_MAX_CHARS],
        "raw_truncated": len(body) > RAW_MAX_CHARS,
        "parsed": _json_safe(parsed),
        "command": last_owo_command.get(message.channel.id, ""),
        "channel_id": str(message.channel.id),
        "at": datetime.utcnow().isoformat() + "Z",
        # OwO co dung reply khong? (neu co, bot se bo tin tra loi nguoi khac chinh xac hon)
        "reply_to": reply_target(message, await get_config("tracked_user_id")),
    }
    if extra:
        doc.update(extra)
    await mdb[COL_RAW].update_one({"_id": kind}, {"$set": doc}, upsert=True)


async def record_unrecognized(text, message):
    """Tin OwO ma khong loai nao nhan ra — giu vai tin gan nhat de xem OwO co
    doi dinh dang (vd lenh huntbot khong con duoc doc) hay khong."""
    doc = {
        "raw": (text or "")[:2500],
        "command": last_owo_command.get(message.channel.id, ""),
        "at": datetime.utcnow().isoformat() + "Z",
    }
    row = await mdb[COL_RAW].find_one({"_id": "unrecognized"}) or {}
    items = (row.get("items") or []) + [doc]
    await mdb[COL_RAW].update_one({"_id": "unrecognized"}, {"$set": {"items": items[-UNRECOGNIZED_KEEP:]}}, upsert=True)


async def handle_owo_response(message: discord.Message, source_id):
    text = flatten_message(message)
    if not text.strip():
        return

    # Tin OwO tra loi NGUOI KHAC (ten o dong dau / tieu de khong khop ten ban) -> bo qua.
    # Chua biet ten nao (bot vua khoi dong, ban chua go lenh) thi khong loc.
    who = speaker_name(text) or header_owner(text)
    if who:
        names = await tracked_name_set(source_id)
        if names and not weapon_owner_matches(who, names):
            print(f"[tracker] Bo qua tin cua '{who}' (khong khop {sorted(names)})")
            skipped_foreign["name"] = who
            skipped_foreign["count"] += 1
            await record_raw("foreign_skipped", text, {"ten_trong_tin": who, "ten_chap_nhan": sorted(names)}, message)
            return

    await remember_emojis(text)
    recognized = False  # co loai nao nhan ra tin nay khong (neu khong -> ghi vao "unrecognized")

    pet = parse_owodex(text)
    if pet:
        await save_pet_species(pet, source_id)
        await record_raw("owodex", text, pet, message)
        recognized = True

    weapon = parse_weapon_detail(text)
    if weapon:
        # Chỉ ghi vũ khí của CHÍNH người đang theo dõi: owo weapon <ID> xem được cả
        # vũ khí của người khác (tiêu đề ghi tên chủ) — không được lẫn vào dữ liệu của bạn.
        names = set(tracked_names.get(str(source_id), set()))
        aliases = await get_config("weapon_owner_aliases", "") or ""
        names |= {a.strip() for a in aliases.split(",") if a.strip()}
        owner_ok = weapon_owner_matches(weapon.get("owner"), names)
        recognized = True
        await record_raw("weapon", text, weapon, message,
                         extra={"saved": bool(owner_ok), "accepted_owner_names": sorted(names)})
        if owner_ok:
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
            await record_raw("team", text, team, message)
            recognized = True

    hunt = parse_huntbot_status(text)
    if hunt:
        await save_huntbot(hunt)
        await record_raw("huntbot", text, hunt, message)
        recognized = True

    quest = parse_quest_status(text)
    if quest:
        await save_quest(quest)
        await record_raw("quest", text, quest, message)
        recognized = True

    checklist = parse_checklist(text)
    if checklist:
        await save_checklist(checklist)
        await record_raw("checklist", text, checklist, message)
        recognized = True

    daily = parse_daily(text, last_owo_command.get(message.channel.id, ""))
    if daily:
        await save_daily(daily)
        await record_raw("daily", text, daily, message)
        recognized = True

    cash = parse_cowoncy(text)
    if cash:
        await save_cowoncy(cash, source_id)
        await record_raw("cowoncy", text, cash, message)
        recognized = True

    zoo_kind, zoo_result = await handle_zoo_text(message.channel.id, text, source_id)
    if zoo_kind:
        await record_raw(zoo_kind, text, {
            "pets_da_ghep_tong": len(zoo_result["pets"]),
            "zoo_points": zoo_result.get("zoo_points"),
            "breakdown_raw": zoo_result.get("breakdown_raw"),
        }, message)
        recognized = True

    inv_kind, inv = await handle_inventory_text(message.channel.id, text, source_id)
    if inv_kind:
        await record_raw(inv_kind, text, inv, message)
        recognized = True

    gem_status = parse_hunt_gem_status(text)
    if gem_status:
        vanished_slots = await save_gem_status(gem_status, source_id)
        await record_raw("hunt_gems", text, gem_status, message,
                         extra={"vanished_slots": sorted(vanished_slots)})
        recognized = True
        if vanished_slots:
            await remind_gem_replacements(message, vanished_slots, source_id)

    found = parse_hunt_found(text)
    if found:
        new_names = await record_new_pets(found, source_id)
        await record_raw("hunt_found", text, found, message,
                         extra={"pet_moi_lan_dau": new_names, "zoo_da_luu": new_names is not None})
        recognized = True

    battle = parse_battle(text)
    if battle:
        names = await tracked_name_set(source_id)
        owner = battle_owner_name(message)
        if owner and names and not weapon_owner_matches(owner, names):
            print(f"[tracker] Bo qua battle cua '{owner}' (khong khop {sorted(names)})")
            await record_raw("foreign_skipped", text, {"ten_trong_tin": owner, "ten_chap_nhan": sorted(names)}, message)
        else:
            await save_battle(battle, source_id)
            await record_raw("battle", text, battle, message, extra={"owner": owner})
        recognized = True

    if not recognized:
        await record_unrecognized(text, message)


def _continuation_open(channel_id):
    now = time.time()
    z = zoo_session.get(channel_id)
    i = inv_session.get(channel_id)
    return bool((z and now - z["ts"] < ZOO_PART_WINDOW) or (i is not None and now - i < INV_PART_WINDOW))


async def handle_continuation_only(message: discord.Message, source_id):
    """Cua so lenh da dong nhung dang cho phan 2 cua zoo/kho: chi nhan tin NOI TIEP (khong tieu de).
    Tin co tieu de (co the cua nguoi khac) hoac loai tin khac bi bo qua."""
    text = flatten_message(message)
    if not text.strip() or "'s zoo" in text or "zoo!" in text.lower() or "Inventory" in text:
        return
    # Dong item cua kho bat dau bang `123`<:emoji:id>so-mu -> di duong kho truoc, tranh zoo doc nham
    if re.search(r"`\d{3}`<a?:\w+:\d+>[⁰¹²³⁴⁵⁶⁷⁸⁹]", text):
        inv_kind, inv = await handle_inventory_text(message.channel.id, text, source_id)
        if inv_kind:
            await record_raw(inv_kind, text, inv, message)
        return
    zoo_kind, zoo_result = await handle_zoo_text(message.channel.id, text, source_id)
    if zoo_kind:
        await record_raw(zoo_kind, text, {
            "pets_da_ghep_tong": len(zoo_result["pets"]),
            "zoo_points": zoo_result.get("zoo_points"),
            "breakdown_raw": zoo_result.get("breakdown_raw"),
        }, message)


async def remind_gem_replacements(message: discord.Message, slots, source_id):
    """Cac slot gem vua het (da xac nhan) -> nhac trong kenh + tao DUNG 1 lenh cho AutoMacro:
    `owo use 051 065 072` (moi slot 1 vien, khac loai nhau nen go chung 1 lenh duoc).
    Chong spam: neu con lenh thay gem dang cho thi GOP vao lenh moi (huy lenh cu); slot nao
    vua co lenh trong SWAP_COOLDOWN_SECONDS thi bo qua."""
    now = datetime.utcnow()
    cmd_col = mdb[COL_AUTOMACRO_COMMANDS]

    pending = await cmd_col.find({"action": "swap_gem", "status": "pending"}).to_list(length=20)
    pending_slots = set()
    for c in pending:
        pending_slots |= {x for x in str((c.get("params") or {}).get("slots") or (c.get("params") or {}).get("slot") or "").split(",") if x}

    cool_cut = (now - timedelta(seconds=SWAP_COOLDOWN_SECONDS)).isoformat()
    recent = await cmd_col.find({"action": "swap_gem", "status": {"$ne": "pending"},
                                 "created_at": {"$gte": cool_cut}}).to_list(length=20)
    cooling = set()
    for c in recent:
        cooling |= {x for x in str((c.get("params") or {}).get("slots") or (c.get("params") or {}).get("slot") or "").split(",") if x}

    todo = (set(slots) | pending_slots) - (cooling - set(pending_slots))
    if not todo:
        print(f"[tracker][gem] bo qua nhac slot {sorted(slots)}: vua co lenh thay trong {SWAP_COOLDOWN_SECONDS}s")
        return

    picks = []  # (slot, vien duoc chon)
    for slot in sorted(todo):
        options = await mdb[COL_INVENTORY].find(
            {"is_gem": True, "gem_slot": slot, "count": {"$gt": 0}}
        ).sort("gem_tier_rank", -1 if GEM_PICK_HIGHEST_TIER else 1).to_list(length=10)
        if slot in slots:  # chi nhac trong kenh cho slot MOI het, khong nhac lai slot cu
            if not options:
                await message.channel.send(
                    f"<@{source_id}> ⚠️ Gem slot {slot} vừa hết, và trong kho không còn viên nào cùng slot để thay. "
                    f"Cần farm/mua thêm.")
            else:
                lines = [f"`owo use {o['_id']}` — {o['gem_tier']} (còn {o['count']})" for o in options]
                await message.channel.send(
                    f"<@{source_id}> ⚠️ Gem slot {slot} vừa hết độ bền! Chọn 1 trong các lựa chọn còn lại:\n" + "\n".join(lines))
        if options:
            # options da sap xep: tier CAO nhat dung dau. Tier chi con rat it vien thi giu lai (neu con tier khac)
            usable = [o for o in options if (o.get("count") or 0) > GEM_KEEP_IF_COUNT_AT_MOST] or options
            picks.append((slot, usable[0]))

    if not picks:
        return

    for c in pending:  # lenh cu chua chay duoc gop vao lenh moi
        await cmd_col.update_one({"_id": c["_id"]}, {"$set": {"status": "superseded",
                                                              "completed_at": now.isoformat()}})
    codes = [o["_id"] for _, o in picks]
    await queue_automacro_command("swap_gem", {
        "slots": ",".join(sl for sl, _ in picks),
        "slot": picks[0][0],
        "item_codes": ",".join(codes),
        "item_code": codes[0],
        "gem_tier": picks[0][1]["gem_tier"],
        "command_text": "owo use " + " ".join(codes),
    })
    print(f"[tracker][gem] Tao 1 lenh thay gem: owo use {' '.join(codes)} (slot {[sl for sl, _ in picks]})")


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


@bot.command(name="rawdump")
@is_owner()
async def rawdump_cmd(ctx, *, arg: str = ""):
    """Gui cho ban 1 FILE chua NGUYEN VAN tin nhan OwO moi nhat cua tung loai (hunt, inv,
    zoo, team, quest, daily, huntbot, cash, weapon) + ket qua bot doc duoc tu do — de doi
    chieu bot doc dung hay sai. File gui qua TIN NHAN RIENG (khong hien o kenh chung).
    ,rawdump xoa  -> xoa het mau cu de bat dau lai cho sach."""
    if arg.strip().lower() in ("xoa", "xóa", "clear"):
        await mdb[COL_RAW].delete_many({})
        await ctx.send("Đã xoá hết mẫu cũ. Gõ lại các lệnh owo rồi `,rawdump` để lấy mẫu mới.")
        return

    rows = await mdb[COL_RAW].find({}).to_list(length=200)
    samples = {r["_id"]: {k: v for k, v in r.items() if k != "_id"} for r in rows}
    missing = [f"{kind} (gõ: {cmd})" for kind, cmd in RAW_EXPECTED.items() if kind not in samples]
    payload = {
        "tao_luc": datetime.utcnow().isoformat() + "Z",
        "kenh_gioi_han": await get_config("tracked_channel_id") or None,
        "chua_thay_loai_nao": missing,
        "mau": samples,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")

    note = f"Đây là nguyên văn tin nhắn OwO bot đã thấy + kết quả bot đọc được ({len(samples)} loại)."
    if missing:
        note += "\nChưa thấy: " + "; ".join(missing)

    def make_file():
        return discord.File(io.BytesIO(data), filename="owo_raw.json")

    try:
        await ctx.author.send(note, file=make_file())
        if ctx.guild is not None:
            await ctx.send("Đã gửi file qua tin nhắn riêng cho bạn.")
    except discord.Forbidden:
        await ctx.send("Không nhắn riêng được (bạn đang tắt tin nhắn riêng từ thành viên server?). "
                        "Gửi thẳng ở đây — file có thể bị người khác trong kênh thấy:\n" + note,
                        file=make_file())


@bot.command(name="setchannel")
@is_owner()
async def setchannel_cmd(ctx, *, arg: str = ""):
    """Gioi han owo-tracker CHI xu ly lenh owo + tin nhan OwO trong 1 kenh duy
    nhat — tranh theo doi nham o kenh khac (server khac, kenh test...). Cac
    lenh cua CHINH bot nay (,status, ,zoo, ,debugnext...) van dung duoc o moi
    kenh, khong bi anh huong.
    Dung: ,setchannel #ten-kenh (hoac dan thang ID kenh). Bo gioi han: ,setchannel xoa
    Khong kem gi: hien trang thai hien tai."""
    arg = arg.strip()
    if not arg:
        current = await get_config("tracked_channel_id")
        if current:
            await ctx.send(f"Đang giới hạn hoạt động trong kênh <#{current}> (`{current}`).\n"
                            f"Đổi: `,setchannel #kênh` · Bỏ giới hạn: `,setchannel xoa`")
        else:
            await ctx.send("Chưa giới hạn kênh nào — bot xử lý lệnh owo ở MỌI kênh.\n"
                            "Giới hạn: `,setchannel #kênh`")
        return
    if arg.lower() in ("xoa", "xóa", "clear"):
        await set_config("tracked_channel_id", "")
        await ctx.send("Đã bỏ giới hạn kênh — bot xử lý lệnh owo ở mọi kênh trở lại.")
        return
    channel_id = arg.strip("<#>")
    if not channel_id.isdigit():
        await ctx.send("Không đọc được kênh. Dùng: `,setchannel #kênh` hoặc dán thẳng ID kênh.")
        return
    await set_config("tracked_channel_id", channel_id)
    await ctx.send(f"Đã giới hạn: owo-tracker giờ CHỈ xử lý lệnh/tin nhắn OwO trong <#{channel_id}>.")


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
    if skipped_foreign["name"] is not None:
        lines.append(f"Tin gần nhất bị bỏ qua vì tên khác: **{skipped_foreign['name']}** "
                     f"({skipped_foreign['count']} tin từ lúc bot chạy). Nếu đó là bạn: `,weaponowner {skipped_foreign['name']}`")
    await ctx.send("\n".join(lines))


@bot.command(name="status")
async def status(ctx):
    tracked = await get_config("tracked_user_id")
    last_hunt = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])

    embed = discord.Embed(title="Trạng thái theo dõi", color=0xD9A227)
    embed.add_field(name="Đang theo dõi", value=f"<@{tracked}>" if tracked else "Chưa đặt — dùng `,track`", inline=False)
    tracked_channel = await get_config("tracked_channel_id")
    embed.add_field(name="Giới hạn kênh",
                     value=f"<#{tracked_channel}>" if tracked_channel else "Không giới hạn — mọi kênh", inline=False)
    if skipped_foreign["name"] is not None:
        embed.add_field(name="Tin bị bỏ qua (tên khác bạn)",
                         value=f"{skipped_foreign['count']} tin, gần nhất của **{skipped_foreign['name']}**. "
                               f"Nếu đó là bạn: `,weaponowner {skipped_foreign['name']}`", inline=False)
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


_HB_PLAIN_CODE_RE = re.compile(r"^[A-Za-z0-9]{3,12}$")
_HB_AMOUNT_CODE_RE = re.compile(r"^(\d{1,7}[hHmMdD]?)\s+([A-Za-z0-9]{3,12})$")
_HB_TYPED_RE = re.compile(r"^(?:owo\s+(?:hb|autohunt|huntbot)|oah)\s+(\d{1,7}[hHmMdD]?)$", re.I)


def open_hb_window(amount=None):
    hb_pending["amount"] = amount
    hb_pending["at"] = time.time()


async def handle_hb_code_dm(message) -> bool:
    """Ruby (acc chinh hoac acc phu) nhan RIENG cho bot dung ma mat khau huntbot, vd `abczyx`
    (hoac `24h abczyx`). Neu vua co yeu cau mat khau (<10 phut) thi nho app go `owo hb <thoi gian> <ma>`.
    Tra ve True neu tin nay da duoc xu ly (khong chuyen tiep cho lenh khac)."""
    uid = str(message.author.id)
    alt = await get_config("alt_user_id", ALT_USER_ID_DEFAULT)
    if not ((OWNER_ID and uid == str(OWNER_ID)) or (alt and uid == str(alt))):
        return False
    text = (message.content or "").strip()
    if not text or text.startswith(","):
        return False            # lenh binh thuong cua bot -> de process_commands xu ly
    m2 = _HB_AMOUNT_CODE_RE.match(text)
    if m2:
        amount, code = m2.group(1), m2.group(2)
    elif _HB_PLAIN_CODE_RE.match(text):
        amount, code = None, text
    else:
        return False            # tin tro chuyen thuong, khong phai ma
    fresh = (time.time() - hb_pending["at"]) <= HB_PENDING_SECONDS
    if not fresh:
        await message.channel.send("Mình chưa thấy yêu cầu mật khẩu huntbot nào đang chờ. "
                                   "Gõ `,hbstart 24h` để bắt đầu, rồi gửi lại mã nhé.")
        return True
    amount = amount or hb_pending["amount"] or await get_config("hb_last_amount", "24h")
    if not _HB_AMOUNT_RE.match(str(amount)):
        amount = "24h"
    hb_pending["at"] = 0.0      # moi lan nhac chi dung 1 lan, tranh gui lap
    await queue_automacro_command("hb_start", {"command_text": f"owo hb {amount} {code}"})
    await message.channel.send(f"✅ Đã nhờ app gõ `owo hb {amount} {code}`. Nếu app đang farm thì lệnh được gõ chen vào trong vài giây.")
    return True


def is_owner_or_alt():
    """Chu bot HOAC acc phu cua Ruby (de tra loi ma huntbot ngay trong DM)."""
    async def predicate(ctx):
        uid = str(ctx.author.id)
        if OWNER_ID and uid == str(OWNER_ID):
            return True
        alt = await get_config("alt_user_id", ALT_USER_ID_DEFAULT)
        return bool(alt) and uid == str(alt)
    return commands.check(predicate)


_HB_AMOUNT_RE = re.compile(r"^\d{1,7}[hHmMdD]?$")
_HB_CODE_RE = re.compile(r"^[A-Za-z0-9]{3,12}$")


@bot.command(name="hbstart")
@is_owner_or_alt()
async def hbstart_cmd(ctx, amount: str = ""):
    """,hbstart [24h|so cowoncy] = nho app go `owo hb <amount>` de OwO dua mat khau huntbot (mac dinh 24h)."""
    amount = (amount or "24h").strip()
    if not _HB_AMOUNT_RE.match(amount):
        await ctx.send("Thời gian/số tiền không hợp lệ. Ví dụ: `,hbstart 24h` hoặc `,hbstart 100`.")
        return
    await set_config("hb_last_amount", amount)
    open_hb_window(amount)
    await queue_automacro_command("hb_start", {"command_text": f"owo hb {amount}"})
    await ctx.send(f"✅ Đã nhờ app gõ `owo hb {amount}`. OwO sẽ đưa mật khẩu — mình chuyển ảnh sang acc phụ, bạn đọc rồi nhắn lại đúng mã.")


@bot.command(name="hbcode")
@is_owner_or_alt()
async def hbcode_cmd(ctx, first: str = "", second: str = ""):
    """,hbcode <ma> hoac ,hbcode <24h> <ma> = Ruby doc ma huntbot roi nhap o day, app se go `owo hb <amount> <ma>`.
    Bot chi chuyen tiep ma do Ruby tu doc, khong tu giai."""
    if first and second:
        amount, code = first.strip(), second.strip()
    else:
        amount, code = await get_config("hb_last_amount", "24h"), first.strip()
    if not code:
        await ctx.send("Cú pháp: `,hbcode abcde` hoặc `,hbcode 24h abcde`.")
        return
    if not _HB_AMOUNT_RE.match(str(amount)) or not _HB_CODE_RE.match(code):
        await ctx.send("Mã chỉ gồm chữ và số (3–12 ký tự), thời gian dạng `24h`/`100`. Kiểm tra lại giúp mình.")
        return
    await queue_automacro_command("hb_start", {"command_text": f"owo hb {amount} {code}"})
    await ctx.send(f"✅ Đã nhờ app gõ `owo hb {amount} {code}`. Nếu app đang farm thì lệnh được gõ chen vào trong vài giây.")


@bot.command(name="setalt")
@is_owner()
async def setalt_cmd(ctx, user_id: str = ""):
    """,setalt = xem acc phu dang dat. ,setalt <id> = doi acc phu (nhan DM nhac huntbot). ,setalt xoa = tat."""
    user_id = user_id.strip()
    if not user_id:
        cur = await get_config("alt_user_id", ALT_USER_ID_DEFAULT)
        await ctx.send(f"Acc phụ nhận DM nhắc huntbot: `{cur}`. Đổi: `,setalt <id>` · Thử: `,testalt`")
        return
    if user_id.lower() in ("xoa", "tat", "off"):
        await set_config("alt_user_id", "")
        await ctx.send("Đã tắt DM acc phụ — tin nhắc huntbot sẽ gửi cho acc chính.")
        return
    if not user_id.isdigit():
        await ctx.send("ID phải là dãy số, ví dụ `,setalt 1238687916176183409`.")
        return
    await set_config("alt_user_id", user_id)
    await ctx.send(f"Đã đặt acc phụ `{user_id}`. Gõ `,testalt` để thử gửi 1 tin.")


@bot.command(name="testalt")
@is_owner()
async def testalt_cmd(ctx):
    """Thu gui 1 tin DM vao acc phu de kiem tra co nhan duoc khong."""
    alt_id = await get_config("alt_user_id", ALT_USER_ID_DEFAULT)
    if not alt_id:
        await ctx.send("Chưa đặt acc phụ. Dùng `,setalt <id>`.")
        return
    ok = await dm_user(alt_id, "🧪 Tin thử từ owo-tracker: acc phụ nhận được DM là ổn rồi.")
    if ok:
        await ctx.send(f"✅ Đã gửi DM thử cho `{alt_id}`. Vào acc phụ kiểm tra giúp.")
    else:
        await ctx.send(f"❌ Không DM được `{alt_id}`. Acc phụ phải **chung server** với bot và bật "
                       f"\"Cho phép tin nhắn trực tiếp từ thành viên máy chủ\" (Cài đặt Quyền riêng tư).")


@bot.command(name="captcha")
async def captcha_cmd(ctx, action: str = ""):
    """,captcha = xem trang thai canh bao captcha. ,captcha clear = tu bao da giai xong (huy canh bao)."""
    if action.lower() in ("clear", "xoa", "huy", "xong"):
        await mdb[COL_ALERTS].update_one(
            {"_id": "captcha"},
            {"$set": {"active": False, "cleared_at": datetime.utcnow().isoformat()}}, upsert=True)
        await ctx.send("Đã huỷ cảnh báo captcha. Có thể bấm Bắt đầu farm lại trong app.")
        return
    st = await get_captcha_state()
    if st["active"]:
        mins = (st["age_seconds"] or 0) // 60
        await ctx.send(f"🚨 OwO đang đòi captcha (cách đây khoảng {mins} phút). Giải xong thì gõ `,captcha clear`.")
    else:
        await ctx.send("✅ Không có cảnh báo captcha nào đang hiệu lực.")


@bot.command(name="automacro")
@is_owner()
async def automacro_cmd(ctx, action: str = ""):
    """Xem cac lenh dang cho AutoMacro xu ly / da xu ly gan day - de kiem
    tra luong ket noi hoat dong dung khong. `,automacro clear` = huy het lenh dang cho."""
    if action.lower() in ("clear", "xoa", "huy"):
        res = await mdb[COL_AUTOMACRO_COMMANDS].update_many(
            {"status": "pending"},
            {"$set": {"status": "cancelled", "completed_at": datetime.utcnow().isoformat()}})
        await ctx.send(f"Đã huỷ {getattr(res, 'modified_count', '?')} lệnh đang chờ. App sẽ không gõ các lệnh đó nữa.")
        return
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
        value="`,track @user` (owner) · `,setprefixes owo,o` (owner) · `,status` · `,setchannel` (owner) · `,rawdump` (owner) · `,weaponowner` (owner) · "
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
