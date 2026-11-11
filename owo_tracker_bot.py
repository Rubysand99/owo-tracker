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
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
import auto_refresh   # quyết định thuần: nhắc huntbot + chen lệnh check khi đang farm
import tools_api      # hàm thuần cho các đường API của màn "Công cụ": teamcheck / zoodiff / unlocked / acc phụ
# Các hàm đọc tin OwO nằm ở owo_parsers.py; import lại đây để code cũ và test (b.parse_xxx) chạy như trước.
from owo_parsers import (
    _GEM_TIER_RANK,
    _fold,
    _KNOWN_PASSIVES,
    _parse_utc,
    clean_owner_name,
    decode_superscript_number,
    duration_to_seconds,
    emoji_to_name,
    GEM_SLOTS,
    GEM_TIERS,
    decode_allowed_tiers,
    encode_allowed_tiers,
    filter_allowed_gems,
    load_weapon_rules,
    normalize_gem_tier_pref,
    parse_gem_tier_words,
    parse_battle,
    parse_checklist,
    parse_cowoncy,
    parse_daily,
    parse_event_hunt,
    parse_gem_name,
    parse_hunt_found,
    parse_hunt_gem_status,
    parse_huntbot_status,
    parse_inventory,
    parse_owodex,
    parse_quest_status,
    parse_team,
    parse_weapon_advice,
    parse_weapon_detail,
    parse_weapon_list,
    parse_weapon_shards,
    parse_zoo,
    parse_zoo_breakdown,
    pick_gem_option,
    resolve_gem_slot,
    strip_rarity,
)


def _read_version(base_dir=None) -> str:
    """Số phiên bản của bot: nội dung file VERSION (GitHub Actions tự tăng sau mỗi lần cập nhật lên main).
    Không đọc được thì trả '?' — không bao giờ làm bot hỏng chỉ vì thiếu file."""
    try:
        path = os.path.join(base_dir or os.path.dirname(os.path.abspath(__file__)), "VERSION")
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or "?"
    except Exception:
        return "?"


def _read_git_sha(base_dir=None) -> str:
    """Mã commit ngắn nếu chạy từ 1 repo git (VPS / Termux); không có git (vd Railway) thì chuỗi rỗng."""
    try:
        import subprocess
        out = subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], cwd=base_dir or os.path.dirname(os.path.abspath(__file__)),
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


BOT_VERSION = _read_version()
BOT_COMMIT = _read_git_sha()


def bot_version_text() -> str:
    """'v1.12 (a1b2c3d)' — số phiên bản kèm mã commit khi có."""
    return f"v{BOT_VERSION}" + (f" ({BOT_COMMIT})" if BOT_COMMIT else "")


def _utcnow() -> datetime:
    """Giờ UTC hiện tại dạng naive — thay cho datetime.utcnow() (đã deprecated từ Python 3.12).
    Giữ NGUYÊN định dạng ISO không có múi giờ đang lưu trong MongoDB nên dữ liệu cũ vẫn so sánh đúng."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ----------------------------------------------------------------------
# CẤU HÌNH
# ----------------------------------------------------------------------
OWO_BOT_ID = 408785106942164992  # kiểm tra lại ID thật trong server bạn
import weapon_auto
import weapon_import
NEON_BOT_ID = weapon_auto.NEON_BOT_ID  # bot NeonUtil (chỉ số/bậc vũ khí), chỉ đọc trong kênh farm
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
# Dia chi lang nghe cua API. Mac dinh 0.0.0.0 (Railway/Termux). Tren VPS dat 127.0.0.1 va de Caddy/nginx lo HTTPS ben ngoai.
AUTOMACRO_API_HOST = os.environ.get("AUTOMACRO_API_HOST", "0.0.0.0")
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
COL_ZOO_HISTORY = "owot_zoo_history"      # mỗi lần quan sát zoo (current = owo zoo, all = owo zoo d)
COL_ZOO_UNLOCKED = "owot_zoo_unlocked"    # pet từng xuất hiện trong zoo = đã mở khóa (không bao giờ mất)
COL_INVENTORY = "owot_inventory_items"
COL_GEM_STATUS = "owot_gem_status"
COL_DAILY = "owot_daily_status"
COL_COWONCY = "owot_cowoncy"
COL_WEAPON_SHARDS = "owot_weapon_shards"  # v29: so weapon shards (owo ws)
COL_EVENT = "owot_event_hunt"              # v29: tin san thuong su kien [x/10]
COL_WEAPON_REVIEW = "owot_weapon_review"   # v30: quyet dinh Giu/Bo tung cay (Hub noi)
COL_WEAPON_LIST = "owot_weapon_list"         # v29: kho vu khi tu danh sach `owo weapon` (nhieu trang)
COL_WEAPON_ADVICE = "owot_weapon_advice"   # v29: loi khuyen `?tag <vu khi>` do app thu thap trong server OwO
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
_auto_refresh_task = None
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


def parse_id_list(raw) -> list:
    """'123, 456' -> ['123', '456'] (bo trung, giu thu tu, chi nhan so)."""
    out = []
    for x in re.split(r"[,\s]+", str(raw or "")):
        if x.isdigit() and x not in out:
            out.append(x)
    return out


def scope_allows(scope_guild, scope_channel, guild_id, channel_id, ignored=None) -> bool:
    """Tin o (guild_id, channel_id) co thuoc pham vi theo doi khong?
    Gioi han theo SERVER (,setserver) thang gioi han theo 1 KENH (,setchannel); ca hai trong = moi noi.
    Tin rieng (guild_id None) khong thuoc pham vi nao khi da dat gioi han.
    `ignored` = danh sach kenh BO QUA (,ignorechannel): tin o kenh do khong bao gio duoc theo doi."""
    if ignored and str(channel_id) in {str(x) for x in ignored}:
        return False
    if scope_guild:
        return guild_id is not None and str(guild_id) == str(scope_guild)
    if scope_channel:
        return str(channel_id) == str(scope_channel)
    return True


async def tracking_scope():
    """(server_id, kenh_id) dang gioi han; chuoi rong = khong gioi han o muc do."""
    return (str(await get_config("tracked_guild_id") or ""), str(await get_config("tracked_channel_id") or ""))


_last_farm_channel = {"id": None}


async def remember_farm_channel(channel_id):
    """Theo doi ca server: nho kenh gan nhat Ruby go lenh owo, de bot biet nhan tag / mo Discord vao dau."""
    cid = str(channel_id)
    if _last_farm_channel["id"] != cid:
        _last_farm_channel["id"] = cid
        await set_config("last_farm_channel_id", cid)


async def notify_channel_id():
    """Kenh de bot nhan tag Ruby: kenh chi dinh (,setchannel); theo doi ca server -> kenh gan nhat Ruby go lenh."""
    scope_guild, scope_channel = await tracking_scope()
    if scope_guild:
        return await get_config("last_farm_channel_id") or None
    return scope_channel or None


async def get_event_mode() -> bool:
    """v29: cong tat Event do Ruby bat/tat (app hoac `,eventmode`). BAT = dang co su kien, duoc dung
    slot thu 4 = gem Special (`star`). TAT = khong bao gio tu dat gem Special."""
    return (await get_config("event_mode")) == "on"


async def set_event_mode(on: bool):
    await set_config("event_mode", "on" if on else "off")


async def next_note_id():
    doc = await mdb[COL_CONFIG].find_one_and_update(
        {"_id": "notes_counter"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["value"]


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


_MENTION_HEADER_RE = re.compile(r"<@!?(\d+)>'s\s+[A-Za-z]")          # "### 📜 <@id>'s Quest Log", "<@id>'s Weapons"
_LEAD_MENTION_RE = re.compile(r"^[\s#>*_\-]*<@!?(\d+)>")               # tin OwO mo dau bang ping nguoi nhan


def owner_verdict(text, tracked_id, names):
    """Tin OwO nay la cua ai? Tra ve (ket_luan, nhan): 'mine' | 'other' | None (khong thay chu trong chu).
    Uu tien <@id> (tieu de "<@id>'s ..." hoac ping dau tin) khi tracked_id la ID so that; roi toi ten o dong dau /
    tieu de zoo-kho. Chi ket luan 'other' khi chac chan co chu KHAC; khong ro chu thi tra None."""
    tid = str(tracked_id or "")
    plain = text or ""
    if tid.isdigit():
        head = "\n".join(plain.split("\n")[:4])
        m = _MENTION_HEADER_RE.search(head) or _LEAD_MENTION_RE.match(plain)
        if m:
            return ("mine" if m.group(1) == tid else "other"), f"<@{m.group(1)}>"
    who = speaker_name(plain) or header_owner(plain)
    if who and names:
        return ("mine" if weapon_owner_matches(who, names) else "other"), who
    return None, who


# --- Gan tin KHONG co ten (vd trang thai huntbot) voi lenh cua ban ------------------------------------
HB_COMMAND_RE = re.compile(r"^(?:hb|huntbot|autohunt|ah)(?:\s|$)")
recent_owo_commands = {}   # channel_id -> [(thoi_diem, noi_dung_lenh_bo_prefix), ...] cac lenh owo gan day cua ban


def owo_command_body(content_lower, prefixes):
    """'owo hb 24h' -> 'hb 24h' (bo prefix OwO dai nhat khop)."""
    for p in sorted(prefixes or [], key=len, reverse=True):
        if content_lower.startswith(p):
            return content_lower[len(p):].strip()
    return content_lower.strip()


def record_recent_command(channel_id, content_lower, prefixes, now=None):
    now = time.time() if now is None else now
    items = [x for x in recent_owo_commands.get(channel_id, []) if now - x[0] < 120]
    items.append((now, owo_command_body(content_lower, prefixes)))
    recent_owo_commands[channel_id] = items[-10:]


def command_recent(channel_id, regex, window=None, now=None):
    """Ban co go lenh khop `regex` trong kenh nay trong `window` giay gan day khong?"""
    window = CORRELATION_WINDOW if window is None else window
    now = time.time() if now is None else now
    return any(now - ts < window and regex.match(body) for ts, body in recent_owo_commands.get(channel_id, []))


async def tracked_name_set(source_id):
    names = set(tracked_names.get(str(source_id), set()))
    aliases = await get_config("weapon_owner_aliases", "") or ""
    names |= {a.strip() for a in aliases.split(",") if a.strip()}
    return names


async def save_checklist(c):
    doc = {k: v for k, v in c.items() if k != "kind"}
    doc["updated_at"] = _utcnow().isoformat()
    await mdb[COL_CHECKLIST].update_one({"_id": c["kind"]}, {"$set": doc}, upsert=True)


def slice_advice_reply(tag: str, screen: str) -> str:
    """Lay phan tin tra loi SAU dong lenh `?tag <tag>` cuoi cung tren man hinh (khong thay thi lay ca man hinh)."""
    lines = (screen or "").split("\n")
    want = f"?tag {tag}".lower()
    idx = -1
    for i, ln in enumerate(lines):
        if ln.strip().lower() == want:
            idx = i
    return "\n".join(lines[idx + 1:]) if idx >= 0 else "\n".join(lines)


async def save_weapon_list(entries, source_id=None):
    now_iso = _utcnow().isoformat()
    for e in entries:
        await mdb[COL_WEAPON_LIST].update_one({"_id": e["id"]}, {"$set": {**e, "seen_at": now_iso, "owner_id": source_id}}, upsert=True)


async def plan_weapon_probe(max_probes: int = 80):
    """Chon it cay nhat nhung phu du MOI LOAI vu khi va MOI PASSIVE trong kho (tham lam): moi cay se duoc go
    `owo w <ID>` de bot hoc ten day du + co che. Tra ve (danh sach ID, phan chua phu duoc)."""
    rows = await mdb[COL_WEAPON_LIST].find({}).to_list(length=5000)
    cand = []
    for r in rows:
        elems = {("type", r.get("type"))} | {("passive", pb) for pb in r.get("passives", [])}
        cand.append((r["_id"], r.get("quality") or 0, elems))
    uncovered = set().union(*[c[2] for c in cand]) if cand else set()
    chosen = []
    while uncovered and len(chosen) < max_probes:
        best = max(cand, key=lambda c: (len(c[2] & uncovered), c[1]))
        if not (best[2] & uncovered):
            break
        chosen.append(best[0])
        uncovered -= best[2]
    return chosen, sorted(f"{k}:{v}" for k, v in uncovered)


async def queue_weapon_probe(max_probes: int = 80):
    ids, left = await plan_weapon_probe(max_probes)
    for wid in ids:
        await queue_automacro_command("weapon_probe", {"command_text": f"owo w {wid}"})
    return ids, left


async def build_weapon_knowledge():
    """Gom kien thuc: loai vu khi (mo ta chinh + hieu ung co san), passive (khoa trong game + ten day du + mo ta),
    kem so luong trong kho cua Ruby."""
    lst = await mdb[COL_WEAPON_LIST].find({}).to_list(length=5000)
    inst = await mdb[COL_WEAPON_INSTANCES].find({}).to_list(length=5000)
    types = await mdb[COL_WEAPON_TYPES].find({}).to_list(length=300)
    type_count, passive_count, passive_example = {}, {}, {}
    for r in lst:
        type_count[r.get("type")] = type_count.get(r.get("type"), 0) + 1
        for pb in r.get("passives", []):
            passive_count[pb] = passive_count.get(pb, 0) + 1
            passive_example.setdefault(pb, r["_id"])
    passives = {}
    for d in inst:
        for e in d.get("effects") or []:
            k = e.get("key")
            if not k:
                continue
            row = passives.setdefault(k, {"key": k, "name": e.get("name"), "desc": e.get("desc"), "emoji_names": [], "on_types": []})
            if e.get("emoji") not in row["emoji_names"]:
                row["emoji_names"].append(e.get("emoji"))
            if d.get("type_name") and d["type_name"] not in row["on_types"]:
                row["on_types"].append(d["type_name"])
    for k, n in passive_count.items():
        passives.setdefault(k, {"key": k, "name": None, "desc": None, "emoji_names": [], "on_types": []})["so_cay_trong_kho"] = n
        passives[k]["vi_du_id"] = passive_example.get(k)
    return {"tao_luc": _utcnow().isoformat(), "so_cay_trong_kho": len(lst), "so_cay_da_xem_chi_tiet": len(inst),
            "loai_vu_khi": [{"base": b, "so_cay": n} for b, n in sorted(type_count.items(), key=lambda x: -x[1])],
            "kien_thuc_loai": [{"ten": t.get("display_name"), "mo_ta_chinh": t.get("main_desc"), "hieu_ung_co_san": t.get("inherent_effects")} for t in types],
            "passive": sorted(passives.values(), key=lambda x: x["key"])}


async def send_weapon_knowledge():
    data = json.dumps(await build_weapon_knowledge(), ensure_ascii=False, indent=1).encode("utf-8")
    return await send_file_to_owner("🧠 App đã quét kho vũ khí và đọc chi tiết từng loại + từng passive. Gửi file này cho Claude "
                                    "để ghép tên passive đầy đủ với lời khuyên server.", "weapon_knowledge.json", data)


def quality_grade(q):
    if q is None:
        return "❔", "chưa rõ"
    if q >= 80:
        return "🟢", "xuất sắc"
    if q >= 60:
        return "🟡", "khá"
    if q >= 40:
        return "🟠", "trung bình"
    return "🔴", "yếu"


def evaluate_team_member(member, instance, rules, team_weapon_keys=()):
    """Cham 1 thanh vien doi hinh theo 2 yeu to: (1) CHI SO / CO CHE vu khi, (2) PASSIVE. Tra ve dict + cac dong chu.
    Khong doan: khong map duoc passive/loai vu khi -> ❓ (khong coi la sai)."""
    types = rules.get("types", {})
    e2c = rules.get("emoji_to_code", {})
    alias = rules.get("passive_alias", {})
    ruby = rules.get("ruby", {})
    base = strip_rarity(member.get("weapon_emoji"), e2c)
    code = e2c.get(base)
    rule = types.get(code) if code else None
    out = {"pos": member.get("pos"), "pet": member.get("name"), "weapon_code": code,
           "weapon_key": rule.get("key") if rule else None, "passive": None, "passive_verdict": "unknown",
           "quality": member.get("quality"), "lines": []}
    pet_line = (f"**{member.get('pos')}. {member.get('name')}** Lv{member.get('level')} — "
                f"HP {member.get('hp')} · WP {member.get('wp')} · STR {member.get('att')} · MAG {member.get('mag')} · "
                f"PR {member.get('pr')}% · MR {member.get('mr')}%")
    out["lines"].append(pet_line)
    if not member.get("weapon_emoji"):
        out["lines"].append("🗡️ Chưa biết loại vũ khí (gõ `owo team` lại để bot đọc loại vũ khí).")
        return out
    wname = rule["name"] if rule else (base or "?")
    icon, grade = quality_grade(member.get("quality"))
    out["lines"].append(f"🗡️ {wname} ({member.get('weapon_rarity') or '?'}) — chất lượng {member.get('quality')}% → {icon} {grade}")
    # --- yeu to 1: chi so / co che
    if rule:
        if rule.get("stats"):
            out["lines"].append("📏 Chỉ số lý tưởng: " + "; ".join(rule["stats"][:4]))
        if rule.get("limited"):
            out["lines"].append("⚠️ Server ghi: vũ khí này ít dùng được trong nhiều đội.")
    cost = (instance or {}).get("wp_cost")
    pet_wp = member.get("wp")
    if cost and pet_wp:
        out["lines"].append(f"⚙️ Vũ khí tốn {cost} WP, pet có {pet_wp} WP → đủ khoảng {pet_wp // cost} lượt dùng.")
    elif rule and rule.get("wp_cost") and pet_wp:
        nums = [int(x) for x in re.findall(r"\d+", str(rule["wp_cost"]))]
        if nums:
            lo, hi = min(nums), max(nums)
            u_lo, u_hi = pet_wp // hi, pet_wp // lo
            uses = f"{u_lo}" if u_lo == u_hi else f"{u_lo}–{u_hi}"
            out["lines"].append(f"⚙️ Chi phí WP điển hình {rule['wp_cost']}, pet có {pet_wp} WP → khoảng {uses} lượt "
                                f"(chưa có chi tiết cây này: gõ `owo weapon {member.get('weaponId')}`).")
    # --- yeu to 2: passive
    pe = (member.get("passive_emojis") or [None])[0]
    pbase = strip_rarity(pe)
    info = (rules.get("passives", {}).get(pbase)) or {}
    pkey = alias.get(pbase, pbase)           # khoa trong loi khuyen cua server
    out["passive"] = pkey
    if not pe:
        out["lines"].append("✨ Chưa đọc được passive của cây này.")
        return out
    shown = f"{info['ten']} ({pbase})" if info.get("ten") else str(pbase)
    summary = info.get("tom_tat_vi")
    if not rule:
        out["lines"].append(f"✨ Passive: {shown} — ❓ chưa có lời khuyên cho loại vũ khí này.")
        if summary:
            out["lines"].append(f"   ↳ {summary}")
        return out
    rec = set(rule.get("recommended", []))
    for r in rule.get("roles", []):
        rec |= set(r.get("passives", []))
    conds = {}
    for c in rule.get("conditional", []):
        for ps in c.get("passives", []):
            conds[ps] = c.get("dieu_kien", "")
    server_any = set()
    for t in types.values():
        server_any |= set(t.get("recommended", []))
        for c in t.get("conditional", []):
            server_any |= set(c.get("passives", []))
    ruby_picks = set(rule.get("ruby_them", []))
    if pkey == "sacrifice" and rule.get("key") in set(ruby.get("sacrifice_hop_voi", [])):
        ruby_picks.add("sacrifice")
    hoi_wp = set(ruby.get("passive_hoi_wp", []))
    if pkey in rec:
        out["passive_verdict"] = "ok"
        out["lines"].append(f"✨ Passive: {shown} — ✅ nằm trong danh sách server khuyên.")
    elif pkey in ruby_picks:
        out["passive_verdict"] = "ruby"
        extra = f" ({conds[pkey]})" if pkey in conds else ""
        out["lines"].append(f"✨ Passive: {shown} — ✅ bạn chọn cho loại này{extra}.")
    elif pkey in hoi_wp:
        out["passive_verdict"] = "ruby_wp"
        out["lines"].append(f"✨ Passive: {shown} — ✅ passive hồi WP (bạn thích), server không liệt kê riêng cho loại này.")
    elif pkey in conds:
        cond = conds[pkey]
        need_rstaff = "rstaff" in cond.lower()
        if need_rstaff and "rstaff" in set(team_weapon_keys):
            out["passive_verdict"] = "cond_ok"
            out["lines"].append(f"✨ Passive: {shown} — ✅ có điều kiện, đội có rstaff nên hợp ({cond}).")
        else:
            out["passive_verdict"] = "cond"
            out["lines"].append(f"✨ Passive: {shown} — ⚠️ chỉ hợp khi: {cond}.")
    elif pkey not in (set(rules.get("known_passives", [])) | _KNOWN_PASSIVES):
        out["passive_verdict"] = "unknown"
        out["lines"].append(f"✨ Passive: {shown} — ❓ chưa biết passive này.")
    elif pkey not in server_any:
        out["passive_verdict"] = "unlisted"
        out["lines"].append(f"✨ Passive: {shown} — ⚪ server chưa có lời khuyên cho passive này (bạn tự đánh giá).")
    else:
        out["passive_verdict"] = "no"
        out["lines"].append(f"✨ Passive: {shown} — ❌ không có trong khuyên ({', '.join(sorted(rec)) or 'chưa có'}).")
    if summary:
        out["lines"].append(f"   ↳ {summary}")
    return out


async def build_team_check():
    """Doc doi hinh dang luu, ghep chi tiet vu khi (neu co), cham diem. Tra ve (van ban, danh sach ket qua)."""
    rules = load_weapon_rules()
    members = await mdb[COL_TEAM].find().sort("_id", 1).to_list(length=10)
    if not members:
        return "Chưa có đội hình. Gõ `owo team` (hoặc `owo setteam 1`) trong kênh farm để bot đọc.", []
    ids = [m.get("weaponId") for m in members if m.get("weaponId")]
    inst = {}
    if ids:
        for d in await mdb[COL_WEAPON_INSTANCES].find({"_id": {"$in": ids}}).to_list(length=20):
            inst[d["_id"]] = d
    e2c = rules.get("emoji_to_code", {})
    team_keys = []
    for m in members:
        code = e2c.get(strip_rarity(m.get("weapon_emoji"), e2c))
        if code and code in rules.get("types", {}):
            team_keys.append(rules["types"][code].get("key"))
    results = [evaluate_team_member(m, inst.get(m.get("weaponId")), rules, team_keys) for m in members]
    ok = sum(1 for r in results if r["passive_verdict"] in ("ok", "ruby", "ruby_wp", "cond_ok"))
    bad = [r["pet"] for r in results if r["passive_verdict"] == "no"]
    neutral = sum(1 for r in results if r["passive_verdict"] == "unlisted")
    head = (f"🛡️ **Chấm đội hình** — passive hợp: {ok}/{len(results)}"
            + (f" · server chưa có lời khuyên: {neutral}" if neutral else "")
            + (f" · cần xem lại: {', '.join(bad)}" if bad else ""))
    text = head + "\n\n" + "\n\n".join("\n".join(r["lines"]) for r in results)
    return text, results


async def store_weapon_advice(tags: dict):
    """tags: {tag: nguyen chu man hinh}. Tra ve danh sach doc da luu."""
    docs = []
    now_iso = _utcnow().isoformat()
    for tag, screen in tags.items():
        tag = str(tag).strip().lower()[:30]
        if not tag or not isinstance(screen, str):
            continue
        reply = slice_advice_reply(tag, screen)
        doc = {"tag": tag, "raw_reply": reply[:12000], "raw_screen": screen[:20000],
               "parsed": parse_weapon_advice(reply), "updated_at": now_iso}
        await mdb[COL_WEAPON_ADVICE].update_one({"_id": tag}, {"$set": doc}, upsert=True)
        docs.append(doc)
    return docs


def weapon_advice_payload(docs):
    return {"tao_luc": _utcnow().isoformat(), "so_tag": len(docs),
            "tags": {d["tag"]: {"parsed": d["parsed"], "raw_reply": d["raw_reply"], "raw_screen": d.get("raw_screen")}
                     for d in docs}}


async def send_file_to_owner(text: str, filename: str, data: bytes):
    """Gui 1 file kem loi nhan: vao kenh theo doi (tag ban) va DM, giong notify_owner."""
    tid = await get_config("tracked_user_id")
    cid = await notify_channel_id()
    sent = False
    if cid:
        try:
            ch = bot.get_channel(int(cid)) or await bot.fetch_channel(int(cid))
            mention = f"<@{tid}> " if tid else ""
            await ch.send(f"{mention}{text}", file=discord.File(io.BytesIO(data), filename=filename))
            sent = True
        except Exception as e:
            print(f"[tracker][file] Khong gui file vao kenh: {e!r}")
    if tid:
        try:
            user = bot.get_user(int(tid)) or await bot.fetch_user(int(tid))
            await user.send(text, file=discord.File(io.BytesIO(data), filename=filename))
            sent = True
        except Exception as e:
            print(f"[tracker][file] Khong DM duoc file (bo qua): {e!r}")
    return sent


async def send_weapon_advice_file(docs):
    payload = weapon_advice_payload(docs)
    data = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    ok = sum(1 for d in docs if d["parsed"].get("co_muc_passive"))
    text = (f"📚 App đã học xong lời khuyên vũ khí: **{len(docs)}** loại, đọc được mục passive ở **{ok}** loại. "
            f"Gửi file này cho Claude để làm bộ lọc vũ khí.")
    return await send_file_to_owner(text, "weapon_advice.json", data)


# 4 loai gem cua OwO (slot -> ten). Lenh dung gem van la ID so: `owo use 51 65 72 79`.
GEM_TYPE_NAMES = {"1": "Hunting", "3": "Empowering", "4": "Lucky", "star": "Special"}


def gem_type_name(slot):
    return GEM_TYPE_NAMES.get(str(slot), f"Slot {slot}")


async def get_gem_tier_pref(slot) -> str:
    """Sở thích tier khi thay gem của 1 loại: 'highest' | 'lowest' | tên tier ('Rare'...).
    Lưu trong config `gem_tier_<slot>` (đặt bằng `,gemtier`); chưa đặt thì theo GEM_PICK_HIGHEST_TIER."""
    raw = await get_config(f"gem_tier_{slot}", "")
    pref = normalize_gem_tier_pref(raw) if raw else None
    return pref or ("highest" if GEM_PICK_HIGHEST_TIER else "lowest")


async def get_gem_allowed(slot):
    """Các tier ĐƯỢC PHÉP dùng khi thay gem loại này: set tên tier, hoặc None = mọi tier (mặc định)."""
    return decode_allowed_tiers(await get_config(f"gem_allow_{slot}", ""))


async def set_gem_allowed(slot, allowed):
    await set_config(f"gem_allow_{slot}", encode_allowed_tiers(allowed))


def gem_allowed_text(allowed) -> str:
    """'✅Common ⛔Uncommon ✅Rare ...' — bật/tắt từng tier."""
    allowed = set(GEM_TIERS) if allowed is None else allowed
    return " ".join(f"{'✅' if t in allowed else '⛔'}{t}" for t in GEM_TIERS)


def gem_pref_label(pref) -> str:
    return {"highest": "cao nhất", "lowest": "thấp nhất"}.get(pref, str(pref))


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


# ----------------------------------------------------------------------
# LƯU — tất cả upsert theo key tự nhiên (tên pet, tên loại vũ khí, tên
# passive, ID vũ khí) nên gọi lại nhiều lần không tạo bản trùng.
# ----------------------------------------------------------------------
ZOO_PART_WINDOW = 1800  # giay (30 phut): OwO gui tin 2 rat that thuong — co luc 1-2 giay,
                         # co luc gan 2 tieng, nen phai cho rong tay
zoo_session = {}  # channel_id -> {"ts": thoi diem tin zoo gan nhat, "data": zoo da ghep}


def merge_zoo_parts(first, part):
    """Ghep 2 phan cua cung 1 bang zoo: cong danh sach pet (moi loai chi 1 dong; trung ten thi lay
    so luong cua phan MOI hon); Zoo Points / breakdown lay tu phan nao co."""
    by_name = {}
    for p in list(first["pets"]) + list(part["pets"]):
        by_name[str(p.get("name")).lower()] = p
    return {
        "pets": list(by_name.values()),
        "zoo_points": part["zoo_points"] if part.get("zoo_points") is not None else first.get("zoo_points"),
        "breakdown_raw": part.get("breakdown_raw") or first.get("breakdown_raw"),
        "padded": bool(part.get("padded")) if part.get("pets") else bool(first.get("padded")),
    }


ZOO_ASSEMBLE_WINDOW = 30   # giay: cac tin cua CUNG 1 lan go zoo den cach nhau vai giay
ZOO_SETTLE_SECONDS = 10    # bang zoo vua cap nhat < 10 giay: con dang ghep, chua dung de ket luan "pet moi"


async def handle_zoo_text(channel_id, text, source_id=None):
    """Xu ly 1 tin nhan co the thuoc bang zoo. OwO nay chia zoo thanh 3 tin va thu tu DEN KHONG CO DINH:
    thuc te tin co tieu de ("'s zoo") den CUOI, sau 2 tin con lai (xem owo_raw.json 2026-10-10). Nen ghep
    khong phu thuoc thu tu: tin nao giong zoo cung duoc nhan, tin tieu de den sau van ghep vao phien dang
    mo (khong xoa trang). Tin tieu de den khi phien da cu (>30s) = lan go zoo moi -> bat dau lai."""
    is_header = "'s zoo" in text or "zoo!" in text.lower()
    now = time.time()
    session = zoo_session.get(channel_id)
    age = (now - session["ts"]) if session else None
    fresh = session is not None and age < ZOO_ASSEMBLE_WINDOW      # cung 1 lan go zoo
    open_long = session is not None and age < ZOO_PART_WINDOW      # cho tin noi tiep den tre
    merged = None
    kind = None
    has_header = False
    if is_header:
        part = parse_zoo(text)
        if part:
            if fresh:
                # Tieu de den sau cac tin con lai (thu tu that cua OwO), hoac go zoo lan 2 ngay sau lan 1
                # (<30s): ghep chu khong xoa trang — so luong pet gan nhu khong doi trong vai giay.
                merged = merge_zoo_parts(session["data"], part)
            else:
                merged = part
            has_header = True
            kind = "zoo_1"
        print(f"[tracker][zoo] tin co tieu de, {len(part['pets']) if part else 0} pet, "
              f"ghep -> {len(merged['pets']) if merged else 0} pet, zoo_points={merged.get('zoo_points') if merged else None}")
    else:
        pets_so_far = session["data"]["pets"] if session else []
        start_tier = pets_so_far[-1]["tier"] if pets_so_far else None
        part = parse_zoo(text, continuation=True, start_tier=start_tier) if (open_long or _looks_like_zoo(text)) else None
        if part:
            if open_long:
                merged = merge_zoo_parts(session["data"], part)
                has_header = bool(session.get("has_header"))
            else:
                merged = part                                       # tin dau tien cua 1 lan go zoo, chua co tieu de
            kind = "zoo_2"
            print(f"[tracker][zoo] tin noi tiep, ghep -> {len(merged['pets'])} pet, "
                  f"zoo_points={merged.get('zoo_points')}, da_co_tieu_de={has_header}")
        elif session and age >= ZOO_PART_WINDOW:
            zoo_session.pop(channel_id, None)
            print(f"[tracker][zoo] phien zoo da qua {ZOO_PART_WINDOW}s — dong phien.")
        elif session and _looks_like_zoo(text):
            print(f"[tracker][zoo] tin giong zoo nhung parse_zoo khong nhan ra dong tier dau — bo qua. "
                  f"Dong dau: {text.splitlines()[:1]!r}")
    if merged:
        merged["has_header"] = has_header
        zoo_session[channel_id] = {"ts": now, "data": merged, "has_header": has_header}
        # Chi LUU khi da co tin tieu de. Cac tin khong tieu de den truoc chi duoc giu tam trong bo nho,
        # cho tin tieu de den cuoi roi moi ghep + luu — neu khong tin tieu de khong den thi bang zoo cu
        # (day du) khong bi ghi de bang ban thieu.
        if has_header:
            await save_zoo(merged, source_id)
    return kind, merged


def _looks_like_zoo(text):
    """Tin co ve la 1 phan cua bang zoo: co 'Zoo Points' hoac dong pet co so luong chu so mu."""
    return "Zoo Points" in text or bool(re.search(r"(?<!`)<a?:\w+:\d+>[⁰¹²³⁴⁵⁶⁷⁸⁹]", text))


async def save_zoo(z, source_id=None):
    """Zoo là 1 bản chụp toàn cảnh — ghi đè bản cũ mỗi lần quan sát mới,
    không cộng dồn (số lượng pet là tuyệt đối, không phải log sự kiện)."""
    if z.get("padded"):
        # "owo zoo d" = số ĐÃ BẮT, không phải số đang giữ -> không được ghi đè zoo đang giữ
        print("[tracker][zoo] bang 'owo zoo d' (so da bat) — giu nguyen zoo dang giu, chi luu lich su.")
    else:
        await mdb[COL_ZOO].update_one(
            {"_id": "latest"},
            {"$set": {"pets": z["pets"], "zoo_points": z.get("zoo_points"),
                      "breakdown_raw": z.get("breakdown_raw"), "has_header": z.get("has_header", True),
                      "updated_at": _utcnow().isoformat(), "updated_by": source_id}},
            upsert=True,
        )
    await _archive_zoo(z)
    # Pet nao da nam trong zoo thi khong con la "pet moi" nua
    try:
        names = [str(p["name"]).lower() for p in z["pets"] if p.get("name")]
        if names:
            await mdb[COL_NEW_PETS].delete_many({"_id": {"$in": names}})
    except Exception as e:
        print(f"[tracker][zoo] Khong don duoc danh sach pet moi: {e!r}")


ZOO_HISTORY_KEEP = 30  # mỗi loại (current / all) giữ tối đa 30 lần ghi gần nhất
ZOO_KIND_LABEL = {"current": "owo zoo (đang giữ)", "all": "owo zoo d (số đã bắt)"}
ZOO_TIER_ORDER = ["common", "uncommon", "rare", "epic", "mythic", "legendary", "fabled",
                  "gem", "botrank", "patreon", "cpatreon", "special"]
# Emoji thường của OwO (OwO gửi dạng :tên:, phải đổi sang ký tự thật thì tin nhắn của bot mới hiện hình)
ZOO_STD_EMOJI = {
    "bee": "🐝", "bug": "🐛", "snail": "🐌", "beetle": "🐞", "butterfly": "🦋",
    "baby_chick": "🐤", "mouse2": "🐁", "rooster": "🐓", "rabbit2": "🐇", "chipmunk": "🐿️",
    "sheep": "🐑", "pig2": "🐖", "cow2": "🐄", "dog2": "🐕", "cat2": "🐈",
    "crocodile": "🐊", "tiger2": "🐅", "penguin": "🐧", "elephant": "🐘", "whale": "🐳",
    "dragon": "🐉", "unicorn": "🦄", "snowman2": "☃️", "ghost": "👻", "dove": "🕊️",
}


def _zoo_key(p):
    return f"{p.get('tier')}:{p.get('emoji_id') or str(p.get('name')).lower()}"


def _zoo_emoji(p):
    if p.get("emoji_id"):
        return f"<{'a' if p.get('emoji_animated') else ''}:{p.get('name')}:{p['emoji_id']}>"
    return ZOO_STD_EMOJI.get(str(p.get("name")), f":{p.get('name')}:")


def _zoo_pack(items, limit=1800):
    out, cur = [], ""
    for it in items:
        if cur and len(cur) + 1 + len(it) > limit:
            out.append(cur)
            cur = it
        else:
            cur = f"{cur} {it}" if cur else it
    if cur:
        out.append(cur)
    return out


def _zoo_chunks(text, limit=1900):
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


def _zoo_vn_time(iso):
    try:
        return (datetime.fromisoformat(iso) + timedelta(hours=7)).strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return str(iso)


async def _archive_zoo(z):
    """Lưu lịch sử zoo (current = owo zoo, all = owo zoo d) và ghi nhớ pet đã mở khóa.
    Lỗi ở đây KHÔNG được làm hỏng luồng lưu zoo chính."""
    try:
        kind = "all" if z.get("padded") else "current"
        now = _utcnow().isoformat()
        pets = [{"tier": p.get("tier"), "name": p.get("name"), "count": p.get("count", 0),
                 "emoji_id": p.get("emoji_id"), "emoji_animated": bool(p.get("emoji_animated"))}
                for p in z.get("pets", [])]
        last = await mdb[COL_ZOO_HISTORY].find({"kind": kind}).sort("at", -1).to_list(length=1)
        same = bool(last) and last[0].get("zoo_points") == z.get("zoo_points") and last[0].get("pets") == pets
        # OwO chia zoo thanh nhieu tin: moi lan ghep them 1 tin la 1 ban chup THIEU. Chi luu lich su khi ban chup da
        # DAY DU (co tin tieu de + Zoo Points) — neu khong 1 lan go zoo tao 3 dong va ,zoodiff so ban thieu voi ban du.
        complete = (z.get("zoo_points") is not None or bool(z.get("breakdown_raw"))) and z.get("has_header", True)
        if complete and not same:
            await mdb[COL_ZOO_HISTORY].insert_one({"kind": kind, "at": now, "zoo_points": z.get("zoo_points"),
                                                   "breakdown_raw": z.get("breakdown_raw"), "pets": pets})
            old = await mdb[COL_ZOO_HISTORY].find({"kind": kind}).sort("at", -1).skip(ZOO_HISTORY_KEEP).to_list(length=500)
            if old:
                await mdb[COL_ZOO_HISTORY].delete_many({"_id": {"$in": [d["_id"] for d in old]}})
        have = {d["_id"] for d in await mdb[COL_ZOO_UNLOCKED].find({}, {"_id": 1}).to_list(length=5000)}
        fresh = {}
        for p in pets:
            k = _zoo_key(p)
            if p["name"] and k not in have and k not in fresh:
                fresh[k] = {"_id": k, "tier": p["tier"], "name": p["name"], "emoji_id": p["emoji_id"],
                            "emoji_animated": p["emoji_animated"], "first_seen": now, "first_seen_kind": kind}
        if fresh:
            await mdb[COL_ZOO_UNLOCKED].insert_many(list(fresh.values()), ordered=False)
    except Exception as e:
        print(f"[tracker][zoo] Khong luu duoc lich su / pet da mo khoa: {e!r}")


async def _zoo_unlocked_rows():
    """Mọi pet đã mở khóa: danh sách đã ghi nhớ + pet trong zoo đang giữ (để không thiếu dù chưa ghi nhớ kịp)."""
    rows = await mdb[COL_ZOO_UNLOCKED].find({}).to_list(length=5000)
    seen = {r["_id"] for r in rows}
    latest = await mdb[COL_ZOO].find_one({"_id": "latest"})
    for p in (latest or {}).get("pets", []):
        if p.get("name") and _zoo_key(p) not in seen:
            seen.add(_zoo_key(p))
            rows.append({"_id": _zoo_key(p), "tier": p.get("tier"), "name": p.get("name"),
                         "emoji_id": p.get("emoji_id"), "emoji_animated": bool(p.get("emoji_animated"))})
    rank = {t: i for i, t in enumerate(ZOO_TIER_ORDER)}
    rows.sort(key=lambda r: rank.get(r.get("tier"), 99))  # sort ổn định: giữ thứ tự ghi nhớ trong từng tier
    return rows


def _zoo_diff_text(old, new, kind):
    out = [f"**So 2 lần ghi {ZOO_KIND_LABEL[kind]}**",
           f"{_zoo_vn_time(old['at'])} → {_zoo_vn_time(new['at'])} (giờ VN)"]
    body = []
    pts = None
    if old.get("zoo_points") is not None and new.get("zoo_points") is not None:
        pts = new["zoo_points"] - old["zoo_points"]
    if pts:
        body.append(f"Zoo Points: {pts:+,}")
    bo, bn = parse_zoo_breakdown(old.get("breakdown_raw")), parse_zoo_breakdown(new.get("breakdown_raw"))
    td = {t: bn.get(t, 0) - bo.get(t, 0) for t in ZOO_TIER_ORDER if bn.get(t, 0) != bo.get(t, 0)}
    if td:
        body.append("Tổng đã bắt theo tier: " + ", ".join(f"{t} {v:+,}" for t, v in td.items()))
    mo = {_zoo_key(p): p for p in old.get("pets", [])}
    mn = {_zoo_key(p): p for p in new.get("pets", [])}
    fresh = [p for k, p in mn.items() if k not in mo]
    gone = [p for k, p in mo.items() if k not in mn]
    changed = sorted(({**mn[k], "before": mo[k].get("count", 0), "after": mn[k].get("count", 0)}
                      for k in mn if k in mo and mn[k].get("count", 0) != mo[k].get("count", 0)),
                     key=lambda r: -abs(r["after"] - r["before"]))
    if fresh:
        body.append(f"Mới mở khóa ({len(fresh)}): " + " ".join(_zoo_emoji(p) for p in fresh[:30]))
    if gone:
        body.append(f"Biến mất khỏi danh sách ({len(gone)}): " + " ".join(_zoo_emoji(p) for p in gone[:30]))
    if changed:
        body.append(f"Đổi số lượng: {len(changed)} loại, hiện {min(10, len(changed))} loại đổi nhiều nhất")
        for r in changed[:10]:
            body.append(f"{_zoo_emoji(r)} {r['name']}: {r['before']:,} → {r['after']:,} ({r['after'] - r['before']:+,})")
    return "\n".join(out + (body or ["Không có gì thay đổi."]))


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
        doc = {**item, "updated_at": _utcnow().isoformat(), "updated_by": source_id}
        if snapshot_id:
            doc["snapshot_id"] = snapshot_id
        await mdb[COL_INVENTORY].update_one(
            {"_id": item["code"]},
            {"$set": doc},
            upsert=True,
        )


async def save_gem_status(gs, source_id=None):
    """Luu tinh trang gem NGAY LUC HUNT - khoa theo slot (1/3/4...), ghi de ban cu.
    Tra ve cac slot gem HET: (1) da hien [0/xx] = het do ben ngay luc nay; (2) BIEN MAT DUOC XAC NHAN: phai vang mat o GEM_MISSING_CONFIRM tin
    hunt lien tiep (1 tin thieu gem co the do tin cua nguoi khac / doc sot, khong phai
    gem het that). Slot chi bi xoa khoi bang trang thai khi da xac nhan."""
    seen_slots = {g["slot"] for g in gs["gems"]}
    prev_cursor = mdb[COL_GEM_STATUS].find({})
    prev_docs = await prev_cursor.to_list(length=10)
    prev_slots = {d["_id"] for d in prev_docs}
    missing_now = prev_slots - seen_slots
    # v29: Event BAT, chua thay gem Special dang dung, ma kho con gem Special -> thieu slot star (xac nhan
    # sau GEM_MISSING_CONFIRM tin hunt nhu cac slot khac roi moi dat lenh dung)
    if "star" not in seen_slots and await get_event_mode():
        if await mdb[COL_INVENTORY].find_one({"is_gem": True, "gem_slot": "star", "count": {"$gt": 0}}):
            missing_now = missing_now | {"star"}

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

    # Gem hien [0/xx] = vien do da het do ben ngay o luot hunt nay -> khong can doi den luot hunt sau thay thieu gem
    # moi dat lenh dung: thieu gem, vien con lai hao nhanh gap doi.
    exhausted = {g["slot"] for g in gs["gems"] if g["current"] <= 0}
    for slot in exhausted:
        print(f"[tracker][gem] slot {slot} hien 0/xx - gem da het do ben, dat lenh thay NGAY")

    for g in gs["gems"]:
        await mdb[COL_GEM_STATUS].update_one(
            {"_id": g["slot"]},
            {"$set": {"tier": g["tier"], "emoji_name": g["emoji_name"],
                      "emoji_id": g.get("emoji_id"), "emoji_animated": g.get("emoji_animated", False),
                      "current": g["current"], "max": g["max"],
                      "updated_at": _utcnow().isoformat(), "updated_by": source_id}},
            upsert=True,
        )
    for slot in confirmed:
        await mdb[COL_GEM_STATUS].delete_one({"_id": slot})
        gem_missing_streak.pop(slot, None)
    return confirmed | exhausted


async def save_battle(b, source_id=None):
    """Chuoi battle: ghi de ban cu. best_streak = chuoi dai nhat bot tung thay."""
    prev = await mdb[COL_BATTLE].find_one({"_id": "latest"}) or {}
    best = max(prev.get("best_streak") or 0, b.get("streak") or 0)
    doc = {"result": b["result"], "turns": b["turns"], "xp": b["xp"],
           "streak": b["streak"] if b["streak"] is not None else prev.get("streak"), "best_streak": best,
           "updated_at": _utcnow().isoformat(), "updated_by": source_id}
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
    # Zoo bi chia 2 tin; "Zoo Points" nam o tin CUOI. Chua thay no = bang zoo co the moi doc 1 nua
    # -> pet nam o nua con lai se bi bao nham la "moi". Khong du co so thi khong ket luan.
    if zoo_doc.get("zoo_points") is None and not zoo_doc.get("breakdown_raw"):
        return None
    if zoo_doc.get("has_header") is False:
        return None   # moi ghep duoc cac tin khong tieu de, chua thay tin dau bang
    try:
        upd = datetime.fromisoformat(zoo_doc.get("updated_at"))
        if (_utcnow() - upd).total_seconds() < ZOO_SETTLE_SECONDS:
            return None   # bang zoo vua cap nhat, cac tin con lai co the dang den
    except (ValueError, TypeError):
        pass  # updated_at thieu/sai dinh dang: coi nhu zoo da cu
    known = {p["name"].lower() for p in zoo_doc["pets"]}
    now_iso = _utcnow().isoformat()
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
    cutoff = (_utcnow() - timedelta(days=7)).isoformat()
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
_app_off_cache = {"v": None, "at": 0.0}


async def is_app_off() -> bool:
    """Công tắc tổng `,off`: BẬT = bot không giao việc nào cho app nữa. Lưu trong Mongo nên không mất khi Railway deploy lại."""
    now = time.time()
    if _app_off_cache["v"] is None or now - _app_off_cache["at"] > 5:
        try:
            _app_off_cache["v"] = (await get_config("app_off")) == "on"
        except Exception as e:
            print(f"[tracker] is_app_off: không đọc được cấu hình app_off ({type(e).__name__}: {e})")
            if _app_off_cache["v"] is None:
                _app_off_cache["v"] = False  # chưa từng đọc được và DB đang lỗi: coi như chưa tắt
        _app_off_cache["at"] = now
    return bool(_app_off_cache["v"])


async def set_app_off(on: bool):
    await set_config("app_off", "on" if on else "off")
    _app_off_cache["v"] = bool(on)
    _app_off_cache["at"] = time.time()


async def queue_automacro_command(action: str, params: dict):
    """Ghi 1 lenh moi, trang thai 'pending'. AutoMacro se doc qua API,
    thuc thi, roi bao lai qua /commands/<id>/ack."""
    if mdb is None:
        return
    if await is_app_off():
        print(f"[tracker][off] App dang TAT (,off): khong giao viec {action} cho app.")
        return None
    doc_id = await next_note_id()  # dung chung bo dem voi ,note, chi can duy nhat
    await mdb[COL_AUTOMACRO_COMMANDS].insert_one({
        "_id": doc_id,
        "action": action,
        "params": params,
        "status": "pending",
        "created_at": _utcnow().isoformat(),
        "completed_at": None,
    })
    return doc_id


# ===================== Duyet vu khi: Giu / Bo bang 2 nut tren Hub noi =====================
# Quy trinh: `,weaponreview` -> bot dang 1 tin EMBED danh sach (dang kiem tra / con lai / ID Giu / ID Bo) -> app go `owo w <ID>`
# -> Ruby xem embed cua OwO roi bam Giu / Bo tren Hub -> bot ghi quyet dinh, XOA tin lenh + tin tra loi cua OwO cua cay do
# (chi de lai embed danh sach) -> app go cay ke tiep. CHI GHI DANH SACH - khong tu dismantle / ban gi ca.
# Cay co SAO hoac dang trang bi mac dinh la GIU (khong dua vao hang doi duyet).
REVIEW_KEY = "weapon_review_session"
REVIEW_FIELD_MAX = 1000


async def review_decisions() -> dict:
    rows = await mdb[COL_WEAPON_REVIEW].find({}).to_list(length=20000)
    return {r["_id"]: r.get("decision") for r in rows}


async def review_pending_ids(decided: dict = None) -> list:
    """ID cac cay CAN duyet (khong sao, khong dang trang bi, chua quyet), thu tu on dinh: theo loai roi chat luong thap -> cao."""
    decided = decided if decided is not None else await review_decisions()
    rows = await mdb[COL_WEAPON_LIST].find({}).to_list(length=20000)
    todo = [r for r in rows if not r.get("starred") and not r.get("equipped") and r["_id"] not in decided]
    todo.sort(key=lambda r: (r.get("type") or "", r.get("quality") or 0, r["_id"]))
    return [r["_id"] for r in todo]


async def review_default_keep_ids() -> list:
    rows = await mdb[COL_WEAPON_LIST].find({"$or": [{"starred": True}, {"equipped": True}]}).to_list(length=20000)
    return sorted(r["_id"] for r in rows)


def _review_ids_text(ids, empty="—"):
    if not ids:
        return empty
    text = " ".join(f"`{i}`" for i in ids)
    if len(text) <= REVIEW_FIELD_MAX:
        return text
    kept = []
    size = 12
    for i in reversed(ids):            # uu tien hien cac ID MOI quyet
        size += len(i) + 3
        if size > REVIEW_FIELD_MAX:
            break
        kept.append(i)
    kept.reverse()
    return f"… (+{len(ids) - len(kept)} cũ) " + " ".join(f"`{i}`" for i in kept)


async def review_embed(sess: dict):
    decided = await review_decisions()
    keep = [i for i, d in decided.items() if d == "keep"]
    drop = [i for i, d in decided.items() if d == "drop"]
    pending = await review_pending_ids(decided)
    default_keep = await review_default_keep_ids()
    cur = sess.get("current")
    em = discord.Embed(title="🗡️ Duyệt vũ khí", color=0xFFC24B if sess.get("active") else 0x8B94A7)
    if sess.get("active") and sess.get("phase") == "scanning":
        em.description = ("⏳ Đang quét lại toàn bộ kho (app gõ `owo w` rồi lật trang). **Dừng farm** và chưa bấm gì — "
                          "quét xong Tom sẽ tự chọn cây đầu tiên.")
    elif sess.get("active") and sess.get("auto"):
        em.description = (f"🤖 Tự duyệt (NeonUtil) — đang kiểm tra `{cur}`. **Dừng farm**, không cần bấm gì." if cur
                          else "🤖 Tự duyệt: đang chuẩn bị…")
    elif sess.get("active"):
        em.description = (f"Đang kiểm tra: `{cur}`\nBấm **Giữ** / **Bỏ** trên Hub nổi." if cur
                          else "✅ Hết cây cần duyệt.")
    else:
        em.description = "Đã dừng duyệt."
    em.add_field(name="Còn lại", value=str(len(pending)), inline=True)
    em.add_field(name=f"⭐ Giữ mặc định ({len(default_keep)})", value="có sao / đang trang bị", inline=True)
    em.add_field(name=f"✅ Giữ ({len(keep)})", value=_review_ids_text(keep), inline=False)
    em.add_field(name=f"🗑️ Bỏ ({len(drop)})", value=_review_ids_text(drop), inline=False)
    missing = list(sess.get("missing") or [])
    if missing:
        em.add_field(name=f"❓ ID không còn trong kho ({len(missing)})", value=_review_ids_text(missing), inline=False)
    if sess.get("scanned"):
        em.set_footer(text=f"Quét kho: {sess['scanned']} cây" + (f" · gỡ {sess['pruned']} ID đã quyết nhưng không còn" if sess.get("pruned") else ""))
    return em


async def review_get() -> dict:
    return await get_config(REVIEW_KEY, {}) or {}


async def review_refresh_embed(sess: dict = None):
    """Sua tin embed danh sach tai cho; mat tin (bi xoa) thi dang lai tin moi."""
    sess = sess or await review_get()
    cid = sess.get("channel_id")
    if not cid:
        return
    try:
        ch = bot.get_channel(int(cid)) or await bot.fetch_channel(int(cid))
        em = await review_embed(sess)
        mid = sess.get("msg_id")
        if mid:
            try:
                await ch.get_partial_message(int(mid)).edit(embed=em)
                return
            except discord.NotFound:
                pass
        msg = await ch.send(embed=em)
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.msg_id": msg.id}}, upsert=True)
    except Exception as e:
        print(f"[tracker][review] Khong cap nhat duoc embed danh sach: {e!r}")


async def review_note_message(message, wid: str):
    """Nho ID tin nhan thuoc luot kiem tra cay `wid` (tin lenh `owo w <id>` cua Ruby + tin tra loi cua OwO) de xoa sau khi bam Giu/Bo."""
    sess = await review_get()
    if not sess.get("active") or not sess.get("current"):
        return
    if str(sess["current"]).lower() != str(wid).lower() or str(message.channel.id) != str(sess.get("channel_id")):
        return
    await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$addToSet": {"value.check_msg_ids": message.id}})


async def review_delete_checks(sess: dict):
    """Xoa cac tin cua luot kiem tra (KHONG dong vao embed danh sach). Khong du quyen Manage Messages thi bao 1 lan."""
    ids = [m for m in (sess.get("check_msg_ids") or []) if str(m) != str(sess.get("msg_id"))]
    if not ids:
        return
    try:
        ch = bot.get_channel(int(sess["channel_id"])) or await bot.fetch_channel(int(sess["channel_id"]))
    except Exception as e:
        print(f"[tracker][review] Khong mo duoc kenh de xoa tin: {e!r}")
        return
    denied = False
    for mid in ids:
        try:
            await ch.get_partial_message(int(mid)).delete()
        except discord.NotFound:
            pass
        except discord.Forbidden:
            denied = True
        except Exception as e:
            print(f"[tracker][review] Xoa tin {mid} loi: {e!r}")
    if denied and not sess.get("delete_warned"):
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.delete_warned": True}})
        await notify_owner("⚠️ Bot không có quyền **Manage Messages** trong kênh duyệt vũ khí nên không xoá được tin kiểm tra. "
                           "Cấp quyền đó cho bot (hoặc kệ, vẫn duyệt bình thường).", min_gap=600)


async def weapon_list_accepted(text: str, tracked_id) -> bool:
    """Trang danh sach kho vu khi nay co nhan vao khong? Binh thuong: lenient nhu cu (khong mention thi van nhan).
    Dang QUET CHO DUYET VU KHI (phase scanning): CHI nhan trang co tieu de `<@ID cua ban>'s Weapons` - trang nguoi khac /
    khong co mention deu bo, de khong lan cay cua nguoi khac trong server nhieu nguoi choi."""
    mention = re.search(r"<@!?(\d+)>'s Weapons", text or "")
    sess = await review_get()
    if sess.get("active") and sess.get("phase") == "scanning":
        return bool(tracked_id) and bool(mention) and mention.group(1) == str(tracked_id)
    return not tracked_id or not mention or mention.group(1) == str(tracked_id)


async def _review_next_after_removal(removed_id: str):
    """Bo `removed_id` khoi danh sach kho (khong con that), chon cay ke tiep. Tra ve (next_id, remaining)."""
    await mdb[COL_WEAPON_LIST].delete_one({"_id": removed_id})
    pending = await review_pending_ids()
    return (pending[0] if pending else None), len(pending)


_WEAPON_NOT_FOUND_RE = re.compile(r"could not find a weapon with that unique weapon id", re.I)


async def review_skip_missing(message):
    """OwO bao `owo w <ID>` khong tim thay cay do (da ban / ra): bo ID khoi danh sach, ghi nho de bao, go cay ke tiep.
    Chi xu ly khi lenh gan nhat Ruby go trong kenh dung la `owo w <cay dang duyet>` (khong nham voi tin khac)."""
    sess = await review_get()
    cur = sess.get("current")
    if not sess.get("active") or sess.get("phase") == "scanning" or not cur:
        return False
    if str(message.channel.id) != str(sess.get("channel_id")):
        return False
    last = (last_owo_command.get(message.channel.id) or "").strip()
    if not re.match(r"^\S+\s+w\s+" + re.escape(str(cur).lower()) + r"$", last):
        return False
    await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$addToSet": {"value.check_msg_ids": message.id}})
    sess = await review_get()
    await review_delete_checks(sess)
    nxt, remaining = await _review_next_after_removal(cur)
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY}, {"$set": {"value.current": nxt, "value.check_msg_ids": []}, "$push": {"value.missing": cur}}, upsert=True)
    print(f"[tracker][review] ID {cur} khong con trong kho -> bo qua; cay ke tiep: {nxt}")
    await review_refresh_embed(await review_get())
    if nxt:
        await queue_automacro_command("weapon_review", {"command_text": f"owo w {nxt}"})
    return True


async def _after_review_scan():
    """App quet xong kho: loc quyet dinh cu khong con trong kho, chon cay dau tien, nho app go `owo w <ID>` de duyet."""
    await asyncio.sleep(6)   # cho tin sua cua trang cuoi kip toi
    sess = await review_get()
    if not sess.get("active") or sess.get("phase") != "scanning":
        return
    rows = await mdb[COL_WEAPON_LIST].find({}).to_list(length=20000)
    n = len(rows)
    if n == 0:
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.active": False}}, upsert=True)
        await review_refresh_embed(await review_get())
        await notify_owner("⚠️ Quét kho xong nhưng Tom không đọc được cây nào có tiêu đề `<@bạn>'s Weapons` — "
                           "kiểm tra `,track` đã đặt đúng tài khoản chưa, rồi gõ lại `,weaponreview`.", min_gap=60)
        return
    have = {r["_id"] for r in rows}
    decided = await review_decisions()
    stale = [i for i in decided if i not in have]
    if stale:
        await mdb[COL_WEAPON_REVIEW].delete_many({"_id": {"$in": stale}})
    if sess.get("auto"):
        await _auto_set({"scanned": n, "pruned": len(stale)})
        await _auto_begin(int(sess.get("auto_limit") or 0))
        return
    pending = await review_pending_ids()
    nxt = pending[0] if pending else None
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value.phase": "review", "value.current": nxt, "value.check_msg_ids": [],
                  "value.scanned": n, "value.pruned": len(stale)}}, upsert=True)
    await review_refresh_embed(await review_get())
    warn = (f"\n⚠️ Quét được {n} cây — gần mức tối đa app lật được (~1500). Nếu kho còn nhiều hơn thì cây ở trang cuối chưa được duyệt."
            if n >= 1450 else "")
    await notify_owner(f"🗡️ Đã quét kho: {n} cây. Còn {len(pending)} cây cần duyệt" +
                       (f", gỡ {len(stale)} ID đã quyết nhưng không còn trong kho." if stale else ".") + warn, min_gap=60)
    if nxt:
        await queue_automacro_command("weapon_review", {"command_text": f"owo w {nxt}"})


def review_bucket(doc: dict) -> str:
    """Ngan cua 1 cay trong COL_WEAPON_REVIEW: keep / drop / unknown. Cay bot GIU vi chua chac (UNSURE_REASONS) tinh la 'unknown'
    cho toi khi Ruby tu quyet (manual)."""
    d = doc.get("decision")
    if d == "unknown":
        return "unknown"
    if d == "keep" and not doc.get("manual") and doc.get("reason") in weapon_import.UNSURE_REASONS:
        return "unknown"
    return d if d in ("keep", "drop") else "unknown"


async def review_lists() -> dict:
    """3 danh sach ID cho tab Misc: keep / drop / unknown (gom ca cay chua quyet, khong sao, khong trang bi). Moi danh sach sap xep theo ID."""
    rows = await mdb[COL_WEAPON_REVIEW].find({}).to_list(length=100000)
    out = {"keep": [], "drop": [], "unknown": []}
    for r in rows:
        out[review_bucket(r)].append(str(r["_id"]))
    decided = {r["_id"] for r in rows}
    out["unknown"] += [i for i in await review_pending_ids({i: 1 for i in decided}) if i not in decided]
    for k in out:
        out[k] = sorted(set(out[k]))
    sess = await review_get()
    return {**out, "current_id": sess.get("current"), "active": bool(sess.get("active"))}


async def clean_invalidate(reason: str):
    """Quyet dinh tay doi -> ke hoach don kho dang cho khong con dung: huy buoc cho, bat Ruby xuat lai `nw inv export`."""
    now = _utcnow().isoformat()
    await mdb[COL_AUTOMACRO_COMMANDS].update_many(
        {"status": "pending", "action": {"$regex": "^clean_"}},
        {"$set": {"status": "cancelled", "completed_at": now}})
    await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value": {
        "active": False, "steps": [], "cursor": 0, "total": 0, "at": now, "empty_reason": reason}}}, upsert=True)


async def review_select(wid: str):
    """Ruby chon tay 1 ID trong 3 danh sach de kiem tra (app go `owo w <ID>`). Tra ve (dict, loi)."""
    wid = str(wid or "").strip().upper()
    if not wid or len(wid) > 20 or not wid.isalnum():
        return None, "ID khong hop le"
    sess = await review_get()
    if sess.get("autoneon"):
        return None, "dang tu duyet, bam Dung truoc"
    if sess.get("active") and sess.get("phase") == "scanning":
        return None, "dang quet kho, doi quet xong roi chon cay"
    if sess.get("active") and sess.get("auto"):
        return None, "dang tu duyet (NeonUtil), chua chon tay duoc"
    known = await mdb[COL_WEAPON_REVIEW].find_one({"_id": wid}) or await mdb[COL_WEAPON_LIST].find_one({"_id": wid})
    if not known:
        return None, "khong tim thay cay nay"
    lists = await review_lists()
    queue = []
    for k in ("keep", "drop", "unknown"):
        if wid in lists[k]:
            ids = lists[k]
            queue = ids[ids.index(wid) + 1:]
            break
    await review_delete_checks(sess)
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value.active": True, "value.phase": "review", "value.current": wid, "value.check_msg_ids": [],
                  "value.manual": True, "value.manual_queue": queue[:500]}},
        upsert=True)
    sess = await review_get()
    if not sess.get("channel_id"):
        # chua co phien duyet nao (khong co kenh de dang embed): chi chay duoc o muc app, khong can embed
        pass
    await review_refresh_embed(sess)
    return {"ok": True, "id": wid, "remaining": len(await review_pending_ids())}, None


async def review_stop():
    """Ruby bam 'Dung' tren Hub: tat phien duyet (danh sach Giu/Bo van luu), an nut Giu/Bo/?."""
    sess = await review_get()
    await review_delete_checks(sess)
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value.active": False, "value.current": None, "value.check_msg_ids": [], "value.manual_queue": [],
                  "value.autoneon": False, "value.autoneon_queue": []}},
        upsert=True)
    await review_refresh_embed(await review_get())
    return {"ok": True}


# ---- Tu duyet cay "Chua ro" bang dong gon NeonUtil tu tra loi `owo w <ID>` (khong bam nut / khong goi lenh cua Neon) ----
AUTONEON_WAIT_SECONDS = 30      # qua ngan nay Neon khong tra loi -> bo qua cay do
AUTONEON_MAX_FAILS = 3          # that bai lien tiep -> dung
_autoneon_lock = asyncio.Lock()


async def autoneon_start():
    """Xep hang doi = cac cay 'Chua ro' (tru cay Ruby tu dat '?' bang tay), app go `owo w` tung cay. Tra ve (dict, loi)."""
    sess = await review_get()
    if sess.get("active") and sess.get("phase") == "scanning":
        return None, "dang quet kho, doi quet xong"
    if sess.get("active") and sess.get("auto"):
        return None, "dang tu duyet bang NeonUtil kieu cu"
    rows = {str(r["_id"]): r for r in await mdb[COL_WEAPON_REVIEW].find({}).to_list(length=100000)}
    lists = await review_lists()
    queue = [i for i in lists["unknown"] if not (rows.get(i, {}).get("manual") and rows[i].get("decision") == "unknown")]
    # cay bi Bo chi vi chua xem chi so (chua_xem_bp): cho Neon doc de cuu lai cay tot
    queue += [i for i, r in rows.items() if r.get("decision") == "drop" and r.get("reason") == "chua_xem_bp" and not r.get("manual")]
    queue = sorted(set(queue))
    if not queue:
        return None, "khong co cay nao can duyet (Chua ro / chua xem chi so)"
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value.active": True, "value.phase": "review", "value.manual": True, "value.autoneon": True,
                  "value.autoneon_queue": queue, "value.autoneon_fails": 0, "value.autoneon_done": 0,
                  "value.autoneon_changed": 0, "value.check_msg_ids": []}}, upsert=True)
    await _autoneon_next()
    return {"ok": True, "queue": len(queue)}, None


async def _autoneon_next():
    """Chon cay ke tiep trong hang doi, nho app go `owo w <ID>`, hen gio bo qua neu Neon im lang."""
    sess = await review_get()
    await review_delete_checks(sess)
    queue = list(sess.get("autoneon_queue") or [])
    if not sess.get("autoneon") or not queue:
        done = int(sess.get("autoneon_done") or 0)
        changed = int(sess.get("autoneon_changed") or 0)
        await mdb[COL_CONFIG].update_one(
            {"_id": REVIEW_KEY},
            {"$set": {"value.active": False, "value.autoneon": False, "value.current": None, "value.autoneon_queue": []}}, upsert=True)
        await review_refresh_embed(await review_get())
        if sess.get("autoneon"):
            await notify_owner(f"✅ Tự duyệt xong: đã đọc {done} cây, xếp lại {changed} cây vào Giữ/Bỏ. Gõ `nw inv export` để lập kế hoạch dọn kho mới.", min_gap=30)
        return
    wid = queue[0]
    started = time.time()
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value.current": wid, "value.autoneon_started": started, "value.autoneon_queue": queue[1:], "value.check_msg_ids": []}})
    await review_refresh_embed(await review_get())
    qid = await queue_automacro_command("weapon_review", {"command_text": f"owo w {wid}"})
    if qid is None:
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.autoneon": False, "value.active": False}})
        await notify_owner("⚠️ App đang TẮT (`,off`) nên chưa giao việc — bật Hub nổi, dừng farm rồi bấm Tự duyệt lại.", min_gap=60)
        return
    asyncio.create_task(_autoneon_watch(wid, started))


async def _autoneon_watch(wid: str, started: float):
    await asyncio.sleep(AUTONEON_WAIT_SECONDS)
    async with _autoneon_lock:
        sess = await review_get()
        if not sess.get("autoneon") or sess.get("current") != wid or sess.get("autoneon_started") != started:
            return   # da xu ly xong / da dung
        fails = int(sess.get("autoneon_fails") or 0) + 1
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.autoneon_fails": fails}})
        if fails >= AUTONEON_MAX_FAILS:
            await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.autoneon": False, "value.active": False}})
            await review_refresh_embed(await review_get())
            await notify_owner(f"⚠️ Tự duyệt dừng: {fails} cây liên tiếp không nhận được dòng trả lời của NeonUtil "
                               "(đã dừng farm chưa? Neon có đang trả lời `owo w` không?).", min_gap=60)
            return
        await _autoneon_next()


async def autoneon_handle_neon(message):
    """Tin cua NeonUtil: neu dang tu duyet va doc duoc dong gon cua cay hien tai -> ap luat, ghi Giu/Bo, chuyen cay ke."""
    sess = await review_get()
    if not sess.get("autoneon") or not sess.get("current"):
        return
    wid = str(sess["current"]).upper()
    started = float(sess.get("autoneon_started") or 0)
    if message.created_at.timestamp() < started - 2:
        return
    ref = getattr(message, "reference", None)
    ref_msg = getattr(ref, "resolved", None) if ref else None
    if ref_msg is not None and hasattr(ref_msg, "embeds"):
        # tin Neon tra loi dung tin OwO cua cay khac -> bo qua (tin OwO cua cay hien tai co ghi ID)
        if wid.lower() not in flatten_message(ref_msg).lower():
            return
    rules = load_weapon_rules()
    got = weapon_import.neon_bp(flatten_message(message), rules)
    if not got:
        return
    async with _autoneon_lock:
        sess = await review_get()
        if not sess.get("autoneon") or str(sess.get("current") or "").upper() != wid or sess.get("autoneon_started") != started:
            return
        doc = await mdb[COL_WEAPON_REVIEW].find_one({"_id": wid}) or {}
        lst = await mdb[COL_WEAPON_LIST].find_one({"_id": wid}) or {}
        changed = 0
        if doc.get("reason") != "loai_dac_biet":
            q = doc.get("q")
            if q is None:
                q = lst.get("quality") or 0
            locked = weapon_import.is_locked_reason(doc.get("reason"))
            w = {"id": wid, "t": got["t"], "bp": got["bp"], "q": q, "l": locked}
            # cap nhat top Knowledge voi cay nay
            stored = await get_config(KNOWLEDGE_TOP_KEY, [])
            cand = {str(e["id"]): e["v"] for e in (stored if isinstance(stored, list) else []) if isinstance(e, dict) and "id" in e and "v" in e}
            kv = weapon_import.knowledge_quality(w)
            if kv is not None:
                cand[wid] = kv
            order = sorted(cand, key=lambda i: (-cand[i], i))[:weapon_import.KNOWLEDGE_TOP_N]
            await set_config(KNOWLEDGE_TOP_KEY, [{"id": i, "v": cand[i]} for i in order])
            decision, why = weapon_import.decide(w, set(order))
            if locked:
                # Cay khoa: khong doi Giu/Bo; chi bao Ruby neu chi so khong dat luat
                if why == "khoa_khong_dat" and doc.get("reason") != "khoa_khong_dat":
                    await mdb[COL_WEAPON_REVIEW].update_one({"_id": wid}, {"$set": {"reason": "khoa_khong_dat", "bp": got["bp"]}}, upsert=True)
                    await notify_owner(f"🔒 Cây khóa `{wid}` có chỉ số KHÔNG đạt luật (cần ≥ 2 chỉ số ≥ 80%): `{got['bp']}`. "
                                       "Bot không làm gì cây này, bạn tự quyết.", min_gap=5)
            else:
                if why == "bp_la":
                    decision = "unknown"       # khong doc ro -> giu o 'Chua ro', khong tu quyet
                prev = review_bucket(doc) if doc else "unknown"
                if decision != "unknown" or prev != "unknown":
                    await mdb[COL_WEAPON_REVIEW].update_one(
                        {"_id": wid}, {"$set": {"decision": decision, "reason": why, "bp": got["bp"], "manual": True,
                                                "auto_neon": True, "at": _utcnow().isoformat()}}, upsert=True)
                    if decision != prev:
                        changed = 1
                        await clean_invalidate("đã tự duyệt thêm cây — gõ lại `nw inv export` để lập kế hoạch dọn kho mới")
        await mdb[COL_CONFIG].update_one(
            {"_id": REVIEW_KEY}, {"$set": {"value.autoneon_fails": 0}, "$inc": {"value.autoneon_done": 1, "value.autoneon_changed": changed}})
        await _autoneon_next()


async def review_decide(decision: str):
    """Ghi quyet dinh cho cay dang kiem tra, xoa tin cua no, chon cay ke tiep. Tra ve (dict, loi).
    Quyet dinh cua Ruby danh dau manual=True: `,weaponimport` lan sau khong ghi de, ly do goc (vd 'khoa') giu nguyen."""
    if decision not in ("keep", "drop", "unknown"):
        return None, "decision phai la keep, drop hoac unknown"
    sess = await review_get()
    cur = sess.get("current")
    if not sess.get("active") or not cur:
        return None, "khong co cay nao dang duyet"
    if sess.get("autoneon"):
        return None, "dang tu duyet, bam Dung truoc khi tu quyet"
    prev = await mdb[COL_WEAPON_REVIEW].find_one({"_id": cur}) or {}
    changed = prev.get("decision") != decision or review_bucket(prev) != decision
    await mdb[COL_WEAPON_REVIEW].update_one(
        {"_id": cur}, {"$set": {"decision": decision, "manual": True, "at": _utcnow().isoformat()}}, upsert=True)
    await review_delete_checks(sess)
    if sess.get("manual"):
        queue = [i for i in (sess.get("manual_queue") or []) if i != cur]
        nxt = queue[0] if queue else None
        rest = queue[1:]
    else:
        pending = await review_pending_ids()
        nxt = pending[0] if pending else None
        rest = []
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value.current": nxt, "value.check_msg_ids": [], "value.manual_queue": rest},
         "$push": {"value.history": {"$each": [cur], "$slice": -50}}},
        upsert=True)
    if changed:
        await clean_invalidate("bạn vừa đổi Giữ/Bỏ tay — gõ lại `nw inv export` để lập kế hoạch dọn kho mới")
    sess = await review_get()
    await review_refresh_embed(sess)
    return {"ok": True, "decided": cur, "decision": decision, "next_id": nxt,
            "remaining": len(await review_pending_ids())}, None


# ===================== Tu duyet vu khi (doc bot NeonUtil) =====================
# `,weaponreview auto [N]`: quet kho -> cay khong thuoc dien RAC theo luat cu = GIU luon; cay RAC: app go `owo w <ID>` + bam
# nut "Details" cua NeonUtil, Tom doc Breakdown (cong khai trong kenh) de biet BAC tung chi so VU KHI. Co chi so Mythic+ hoac
# Knowledge > 14% -> GIU, con lai -> BO. Thieu / la du lieu -> GIU. CHUA dismantle gi (buoc do lam sau khi thu nghiem).
AUTO_MAX_FAILS = 3
AUTO_SETTLE_SECONDS = 20
_auto_lock = asyncio.Lock()


async def _auto_set(fields: dict):
    await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {f"value.{k}": v for k, v in fields.items()}}, upsert=True)


async def _auto_write_decision(wid: str, decision: str, reason: str):
    await mdb[COL_WEAPON_REVIEW].update_one(
        {"_id": wid}, {"$set": {"decision": decision, "reason": reason, "auto": True, "at": _utcnow().isoformat()}}, upsert=True)


async def _auto_begin(limit: int = 0):
    """Sau khi quet kho: GIU ngay cay khong can Neon, xep hang doi cac cay RAC can kiem tra."""
    rules = load_weapon_rules(force=True)
    pending = await review_pending_ids()
    rows = {r["_id"]: r for r in await mdb[COL_WEAPON_LIST].find({}).to_list(length=20000)}
    queue = []
    kept_now = 0
    for wid in pending:
        w = {**rows[wid], "id": wid}
        if weapon_auto.needs_neon_check(w, None, rules):
            queue.append(wid)
        else:
            kept_now += 1
            await _auto_write_decision(wid, "keep", weapon_auto.auto_decide(w, None, None, None, rules)[1])
    if limit and limit > 0:
        queue = queue[:limit]
    await _auto_set({"phase": "checking", "auto_queue": queue, "auto_skipped": [], "auto_fails": 0, "auto_cur": {},
                     "current": None, "check_msg_ids": []})
    await review_refresh_embed(await review_get())
    await notify_owner(f"🤖 Tự duyệt: {kept_now} cây giữ ngay theo luật; {len(queue)} cây cần kiểm tra chỉ số bằng NeonUtil. "
                       "**Dừng farm** trong lúc này.", min_gap=60)
    await _auto_advance()


async def _auto_queue_current(wid: str):
    await _auto_set({"current": wid, "check_msg_ids": [], "auto_cur": {"started": time.time()}})
    qid = await queue_automacro_command("weapon_detail_check", {
        "command_text": f"owo w {wid}", "click_label": "details", "click_times": "1",
        "click_wait_ms": "8000", "click_min_ms": "1800", "click_max_ms": "2800"})
    if qid is None:
        await _auto_set({"active": False})
        await review_refresh_embed(await review_get())
        await notify_owner("⚠️ App đang TẮT (`,off`) nên Tom chưa giao việc — bật lại rồi gõ `,weaponreview auto`.", min_gap=60)


async def _auto_advance(skip_id: str = None):
    """Don tin cua cay vua xong, chon cay ke tiep trong hang doi (khong con -> ket thuc)."""
    sess = await review_get()
    await review_delete_checks(sess)
    skipped = list(sess.get("auto_skipped") or [])
    if skip_id:
        skipped.append(skip_id)
    decided = await review_decisions()
    todo = [i for i in (sess.get("auto_queue") or []) if i not in decided and i not in skipped]
    nxt = todo[0] if todo else None
    await _auto_set({"auto_skipped": skipped, "current": nxt, "check_msg_ids": [], "auto_cur": {}})
    if nxt is None:
        await _auto_set({"active": False, "phase": "done"})
        await review_refresh_embed(await review_get())
        keep = sum(1 for d in decided.values() if d == "keep")
        drop = sum(1 for d in decided.values() if d == "drop")
        await notify_owner(f"✅ Tự duyệt xong: Giữ {keep} · Bỏ {drop}" +
                           (f" · bỏ qua {len(skipped)} cây không đọc được (`{' '.join(skipped[:10])}`)" if skipped else "") +
                           ". CHƯA dismantle gì cả — gõ `,weaponreview export` để xem danh sách.", min_gap=60)
        return
    await review_refresh_embed(await review_get())
    await _auto_queue_current(nxt)


async def _auto_session(message):
    sess = await review_get()
    if not (sess.get("active") and sess.get("auto") and sess.get("phase") == "checking" and sess.get("current")):
        return None
    if str(message.channel.id) != str(sess.get("channel_id")):
        return None
    return sess


async def _auto_merge(sess: dict, message, fields: dict):
    upd = {f"value.auto_cur.{k}": v for k, v in fields.items()}
    await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": upd, "$addToSet": {"value.check_msg_ids": message.id}})


async def auto_feed_detail(message, weapon: dict):
    """Tin chi tiet cua OwO cho cay dang kiem tra: lay passive that (Knowledge)."""
    sess = await _auto_session(message)
    if not sess or str(weapon.get("id") or "").upper() != str(sess["current"]).upper():
        return
    await _auto_merge(sess, message, {"has_detail": True, "passive": weapon.get("passive")})
    await auto_try_finish()


async def auto_feed_neon(message):
    """Tin cua NeonUtil: tin gon (so chi so vu khi) hoac embed Breakdown (bac tung chi so)."""
    sess = await _auto_session(message)
    if not sess:
        return
    started = (sess.get("auto_cur") or {}).get("started") or 0
    if message.created_at.timestamp() < started - 2:
        return
    text = flatten_message(message)
    bd = weapon_auto.parse_neon_breakdown(text)
    if bd:
        if bd.get("id") and bd["id"] != str(sess["current"]).upper():
            return
        await record_raw("neon_breakdown", text, bd, message)
        await _auto_merge(sess, message, {"breakdown": bd})
    else:
        cp = weapon_auto.parse_neon_compact(text)
        if not cp:
            return
        await record_raw("neon_compact", text, cp, message)
        await _auto_merge(sess, message, {"n_weapon": cp["n_weapon"]})
    await auto_try_finish()


async def auto_try_finish(force: bool = False):
    async with _auto_lock:
        sess = await review_get()
        if not (sess.get("active") and sess.get("auto") and sess.get("phase") == "checking" and sess.get("current")):
            return
        ac = sess.get("auto_cur") or {}
        complete = bool(ac.get("breakdown") and ac.get("n_weapon") and ac.get("has_detail"))
        if not complete and not force:
            return
        cur = sess["current"]
        row = await mdb[COL_WEAPON_LIST].find_one({"_id": cur})
        rules = load_weapon_rules()
        if row is None:
            decision, reason = "keep", "khong_con_trong_kho"
        elif not ac.get("has_detail"):
            decision, reason = "keep", "thieu_chi_tiet_owo"      # khong biet Knowledge -> khong dam bo
        else:
            decision, reason = weapon_auto.auto_decide({**row, "id": cur}, {"passive": ac.get("passive")},
                                                       ac.get("breakdown"), ac.get("n_weapon"), rules)
        await _auto_write_decision(cur, decision, reason)
        fails = 0 if complete else int(sess.get("auto_fails") or 0) + 1
        await _auto_set({"auto_fails": fails})
        print(f"[tracker][auto-review] {cur}: {decision} ({reason})")
        if fails >= AUTO_MAX_FAILS:
            await _auto_set({"active": False})
            await review_refresh_embed(await review_get())
            await notify_owner(f"⚠️ Tự duyệt dừng: {fails} cây liên tiếp không đọc đủ dữ liệu NeonUtil (kiểm tra Neon có trả lời "
                               "trong kênh farm và nút Details có bấm được không), rồi gõ lại `,weaponreview auto`.", min_gap=60)
            return
        await _auto_advance()


async def _auto_watchdog(wid: str):
    await asyncio.sleep(AUTO_SETTLE_SECONDS)
    sess = await review_get()
    if sess.get("active") and sess.get("auto") and sess.get("phase") == "checking" and sess.get("current") == wid:
        await auto_try_finish(force=True)


async def _auto_on_failed(wid: str):
    async with _auto_lock:
        sess = await review_get()
        if not (sess.get("active") and sess.get("auto") and sess.get("current") == wid):
            return
        fails = int(sess.get("auto_fails") or 0) + 1
        await _auto_set({"auto_fails": fails})
        if fails >= AUTO_MAX_FAILS:
            await _auto_set({"active": False})
            await review_refresh_embed(await review_get())
            await notify_owner("⚠️ Tự duyệt dừng: app báo lỗi nhiều lần liên tiếp (nhớ **dừng farm**, bật Hub nổi), "
                               "rồi gõ lại `,weaponreview auto`.", min_gap=60)
            return
        await _auto_advance(skip_id=wid)


async def _hub_weapon_review():
    sess = await review_get()
    if not sess:
        return None
    decided = await review_decisions()
    return {"active": bool(sess.get("active")), "current_id": sess.get("current"),
            "remaining": len(await review_pending_ids(decided)),
            "kept": sum(1 for d in decided.values() if d == "keep"),
            "dropped": sum(1 for d in decided.values() if d == "drop"),
            "unknown": len((await review_lists())["unknown"])}


async def handle_post_weapon_review(request: web.Request):
    """Hub noi bam Giu/Bo. Body: {"decision": "keep"|"drop"} -> {ok, decided, next_id, remaining}"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "body phai la object JSON"}, status=400)
    res, err = await review_decide(str(body.get("decision") or ""))
    if err:
        return web.json_response({"error": err}, status=409 if "dang duyet" in err else 400)
    return web.json_response(res)


async def handle_post_weapon_review_stop(request: web.Request):
    """POST /weapon-review/stop -> dung duyet vu khi (an nut tren Hub)"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await review_stop())


async def handle_post_weapon_review_autoneon(request: web.Request):
    """POST /weapon-review/autoneon -> tu duyet cac cay 'Chua ro' bang dong gon NeonUtil"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    res, err = await autoneon_start()
    if err:
        return web.json_response({"error": err}, status=400)
    return web.json_response(res)


async def handle_get_weapon_review_lists(request: web.Request):
    """GET /weapon-review/lists -> {keep:[ID], drop:[ID], unknown:[ID], current_id, active}"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await review_lists())


async def handle_post_weapon_review_select(request: web.Request):
    """POST /weapon-review/select {"id": "ABC123"} -> chon cay de kiem tra tay"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "body phai la object JSON"}, status=400)
    res, err = await review_select(str(body.get("id") or ""))
    if err:
        return web.json_response({"error": err}, status=400)
    return web.json_response(res)


AUTH_FAIL_LIMIT = 10        # so lan sai token toi da trong cua so ben duoi
AUTH_FAIL_WINDOW = 300      # giay: vuot qua thi khoa IP do trong chinh khoang nay
_auth_failures = {}         # ip -> [thoi diem sai gan nhat]


def _client_ip(request: web.Request) -> str:
    """IP that cua nguoi goi. Sau Caddy/nginx (chay cung may) thi lay tu X-Forwarded-For."""
    remote = getattr(request, "remote", None) or "?"
    if remote in ("127.0.0.1", "::1"):
        fwd = request.headers.get("X-Forwarded-For", "")
        for part in reversed([p.strip() for p in fwd.split(",")]):
            if part and part not in ("127.0.0.1", "::1"):
                return part   # proxy cua ta them IP that vao CUOI; muc dau co the do nguoi goi gia
    return remote


def _auth_locked(ip: str, now: float = None) -> bool:
    now = time.time() if now is None else now
    recent = [t for t in _auth_failures.get(ip, []) if now - t < AUTH_FAIL_WINDOW]
    if recent:
        _auth_failures[ip] = recent
    else:
        _auth_failures.pop(ip, None)
    return len(recent) >= AUTH_FAIL_LIMIT


def _check_api_token(request: web.Request) -> bool:
    if not AUTOMACRO_API_TOKEN:
        return False
    ip = _client_ip(request)
    if _auth_locked(ip):
        return False   # dang bi khoa vi sai token qua nhieu lan
    got = request.headers.get("Authorization", "").encode("utf-8")
    want = f"Bearer {AUTOMACRO_API_TOKEN}".encode("utf-8")
    ok = hmac.compare_digest(got, want)
    if ok:
        _auth_failures.pop(ip, None)
    else:
        _auth_failures.setdefault(ip, []).append(time.time())
        if len(_auth_failures) > 2000:   # chong day bo nho
            _auth_failures.pop(next(iter(_auth_failures)))
    return ok


async def handle_get_pending_commands(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    if await is_app_off():
        return web.json_response({"commands": [], "off": True})
    stale_cut = (_utcnow() - timedelta(seconds=COMMAND_EXPIRE_SECONDS)).isoformat()
    await mdb[COL_AUTOMACRO_COMMANDS].update_many(
        {"status": "pending", "created_at": {"$lt": stale_cut}},
        {"$set": {"status": "expired", "completed_at": _utcnow().isoformat()}},
    )
    try:
        await clean_queue_batch()   # phien don kho dang chay ma lenh cu het han -> xep lai tu buoc chua xong
    except Exception as e:
        print(f"[tracker][clean] Loi xep buoc don kho: {e!r}")
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
    except ValueError:   # body rong / khong phai JSON (JSONDecodeError la con cua ValueError)
        body = {}
    status = body.get("status", "done") if isinstance(body, dict) else "done"  # "done" hoac "failed"
    if status not in ("done", "failed"):
        return web.json_response({"error": "status phai la done hoac failed"}, status=400)
    # Nguyen tu: chi 1 lan ack duoc chuyen pending -> done/failed; ack lap lai (app thu lai khi mat mang)
    # hoac 2 ack cung luc se KHONG chay lai tac dung phu (tru kho gem, quet vu khi...).
    cmd = await mdb[COL_AUTOMACRO_COMMANDS].find_one_and_update(
        {"_id": cmd_id, "status": "pending"},
        {"$set": {"status": status, "completed_at": _utcnow().isoformat()}},
    )
    if cmd is None:
        return web.json_response({"ok": True, "already": True})
    # Lenh thay gem da go xong -> tru 1 vien moi ma ra khoi kho (ban sao), de lan sau khong
    # chon lai dung ma cu khi chua kip go `owo inv`. `owo inv` that se ghi de lai cho dung.
    if cmd and cmd.get("action") == "swap_gem" and status == "done" and cmd.get("status") == "pending":
        codes = (cmd.get("params") or {}).get("item_codes") or (cmd.get("params") or {}).get("item_code") or ""
        for code in [c.strip() for c in str(codes).split(",") if c.strip()]:
            await mdb[COL_INVENTORY].update_one({"_id": code, "count": {"$gt": 0}}, {"$inc": {"count": -1}})
    action = (cmd or {}).get("action")
    if str(action or "").startswith("clean_"):
        asyncio.create_task(after_clean_ack(status, cmd))
    elif action == "weapon_scan":
        if status == "done":
            asyncio.create_task(_after_weapon_scan())
        else:
            await notify_owner("⚠️ App không quét được danh sách vũ khí (hãy DỪNG farm rồi thử lại bằng `,weaponscan`).", min_gap=60)
    elif action == "weapon_probe":
        asyncio.create_task(_after_weapon_probe())
    elif action == "weapon_detail_check":
        mw = re.search(r"\bw\s+([A-Za-z0-9]{4,8})$", str((cmd.get("params") or {}).get("command_text") or ""))
        if mw:
            if status == "done":
                asyncio.create_task(_auto_watchdog(mw.group(1).upper()))
            else:
                asyncio.create_task(_auto_on_failed(mw.group(1).upper()))
    elif action == "weapon_review_scan":
        if status == "done":
            asyncio.create_task(_after_review_scan())
        else:
            await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.active": False}}, upsert=True)
            await review_refresh_embed(await review_get())
            await notify_owner("⚠️ App không quét được kho vũ khí (hãy DỪNG farm rồi gõ lại `,weaponreview`).", min_gap=60)
    return web.json_response({"ok": True})


async def _after_weapon_scan():
    await asyncio.sleep(6)   # cho tin sua cua trang cuoi kip toi
    n = await mdb[COL_WEAPON_LIST].count_documents({})
    ids, left = await queue_weapon_probe()
    await notify_owner(f"📦 Đã quét {n} vũ khí trong kho. Mình nhờ app gõ `owo w <ID>` cho {len(ids)} cây đại diện "
                       f"(mỗi loại + mỗi passive ít nhất 1 cây)." + (f" Chưa phủ được: {', '.join(left[:8])}" if left else ""), min_gap=60)


async def _after_weapon_probe():
    await asyncio.sleep(8)   # cho tin chi tiet cuoi kip toi
    pending = await mdb[COL_AUTOMACRO_COMMANDS].count_documents({"action": "weapon_probe", "status": "pending"})
    if pending == 0:
        await send_weapon_knowledge()


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


def _age_seconds(value, now):
    t = _parse_utc(value)
    if t is None:
        return None
    return max(0, int((now - t).total_seconds()))


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
            "slot": r["_id"], "type_name": gem_type_name(r["_id"]), "tier": r.get("tier"),
            "current": r.get("current"), "max": mx, "percent": pct, **icon,
        }, r.get("updated_at"), now))
    spare = sorted(
        ({"code": r["_id"], "slot": r.get("gem_slot"), "type_name": gem_type_name(r.get("gem_slot")),
          "tier": r.get("gem_tier"),
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


async def _hub_weapon_shards(now):
    doc = await mdb[COL_WEAPON_SHARDS].find_one({"_id": "latest"})
    if not doc:
        return None
    return _with_age({"amount": doc.get("amount"), **resolve_emoji("weaponshard")}, doc.get("updated_at"), now)


async def _hub_event(now):
    counters = await mdb[COL_EVENT].find({"type": "counter"}).sort("updated_at", -1).to_list(length=20)
    if not counters:
        return None
    logs = await mdb[COL_EVENT].find({"type": "log"}).sort("updated_at", -1).to_list(length=10)

    def pack(r):
        d = {"kind": r.get("kind"), "current": r.get("current"), "max": r.get("max"),
             "text": r.get("text"), "rewards": r.get("rewards") or []}
        return _with_age(d, r.get("updated_at"), now)

    return _with_age({"counters": [pack(r) for r in counters], "recent": [pack(r) for r in logs]},
                     counters[0].get("updated_at"), now)


SLOWDOWN_KEEP = 30


async def record_slowdown():
    """OwO bao '⏱ | Ruby! Slow down and try the command again <t:...:R>' = gui lenh qua day. Luu moc thoi gian (30 gan nhat)."""
    doc = await mdb[COL_ALERTS].find_one({"_id": "slowdown"}) or {}
    ts = [float(x) for x in doc.get("ts", [])][-(SLOWDOWN_KEEP - 1):] + [time.time()]
    await mdb[COL_ALERTS].update_one({"_id": "slowdown"}, {"$set": {"ts": ts, "updated_at": _utcnow().isoformat()}}, upsert=True)


async def _hub_slowdown(now):
    doc = await mdb[COL_ALERTS].find_one({"_id": "slowdown"})
    if not doc or not doc.get("ts"):
        return None
    t_now = time.time()
    recent = [t for t in doc["ts"] if t_now - float(t) <= 1800]
    if not recent:
        return None
    return {"count_30m": len(recent), "age_seconds": int(t_now - max(float(t) for t in recent))}


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
    if len(_notify_recent) > 200:   # khong de dict phinh mai (moi noi dung khac nhau la 1 khoa)
        for k in [k for k, t in _notify_recent.items() if now - t > 3600]:
            _notify_recent.pop(k, None)
    if target == "alt":
        alt_id = await get_config("alt_user_id", ALT_USER_ID_DEFAULT)
        if await dm_user(alt_id, text, images):
            return True
        print("[tracker][notify] Khong DM duoc acc phu - chuyen sang bao acc chinh")
        text = "(Không DM được acc phụ) " + text
        if images:
            text += "\n🖼️ " + "  ".join(images)
    tid = await get_config("tracked_user_id")
    cid = await notify_channel_id()
    sent = False
    if cid:
        try:
            ch = bot.get_channel(int(cid)) or await bot.fetch_channel(int(cid))
            mention = f"<@{tid}> " if tid else ""
            # Chi cho ping dung tai khoan duoc theo doi; chu tu app gui (co the chua @everyone / <@&role>) khong ping ai
            allowed = discord.AllowedMentions(everyone=False, roles=False,
                                              users=[discord.Object(id=int(tid))] if tid else False)
            await ch.send(f"{mention}{text}", allowed_mentions=allowed)
            sent = True
        except Exception as e:
            print(f"[tracker][notify] Khong nhan duoc vao kenh: {e!r}")
    if dm and tid:
        try:
            user = bot.get_user(int(tid)) or await bot.fetch_user(int(tid))
            await user.send(text, allowed_mentions=discord.AllowedMentions.none())
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
    except ValueError:   # body rong / khong phai JSON (JSONDecodeError la con cua ValueError)
        body = {}
    if not isinstance(body, dict):
        return web.json_response({"error": "body phai la object JSON"}, status=400)
    text = str(body.get("text") or "").strip()[:400]
    if not text:
        return web.json_response({"error": "empty"}, status=400)
    target = "alt" if str(body.get("target") or "") == "alt" else "owner"
    ok = await notify_owner("📱 " + text, dm=True, target=target)
    return web.json_response({"ok": bool(ok)})


async def handle_post_weapon_advice(request: web.Request):
    """App gui ket qua go `?tag <vu khi>`. Body: {"tags": {"orb": "<chu tren man hinh>", ...}}"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except ValueError:   # body rong / khong phai JSON (JSONDecodeError la con cua ValueError)
        body = {}
    tags = body.get("tags") if isinstance(body, dict) else None
    if not isinstance(tags, dict) or not tags or len(tags) > 80:
        return web.json_response({"error": "tags phai la object khong rong, toi da 80 muc"}, status=400)
    docs = await store_weapon_advice(tags)
    if not docs:
        return web.json_response({"error": "khong co muc hop le"}, status=400)
    asyncio.create_task(send_weapon_advice_file(docs))
    return web.json_response({"stored": len(docs)})


async def handle_post_event_mode(request: web.Request):
    """App bat/tat che do Event. Body: {"enabled": true|false}"""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except ValueError:   # body rong / khong phai JSON (JSONDecodeError la con cua ValueError)
        body = {}
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return web.json_response({"error": "enabled phai la true/false"}, status=400)
    await set_event_mode(body["enabled"])
    return web.json_response({"event_mode": body["enabled"]})


async def handle_post_power(request: web.Request):
    """App bao Hub noi BAT/TAT. Body: {"on": true|false}. Hub TAT = bot khong giao viec cho app (nhu `,off`);
    Hub BAT = bo `,off`. Luu trong Mongo nen khong mat khi Railway deploy lai."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except ValueError:   # body rong / khong phai JSON
        body = {}
    if not isinstance(body, dict) or not isinstance(body.get("on"), bool):
        return web.json_response({"error": "on phai la true/false"}, status=400)
    await set_app_off(not body["on"])
    cancelled = 0
    if not body["on"]:
        # Hub tat = bot ngung giao viec cho app. Viec da xep hang cho thi huy (nhu `,off`), khong de no tu chay
        # bat ngo luc Ruby bat Hub lai. Bot VAN theo doi / doc tin OwO binh thuong.
        res = await mdb[COL_AUTOMACRO_COMMANDS].update_many(
            {"status": "pending"}, {"$set": {"status": "cancelled", "completed_at": _utcnow().isoformat()}})
        cancelled = getattr(res, "modified_count", 0)
        hb_pending["at"] = 0.0   # huy cua so cho ma huntbot (app khong con de go ma)
    print(f"[tracker][power] Hub noi {'BAT' if body['on'] else 'TAT'} -> app {'ON' if body['on'] else 'OFF'}"
          + (f" (huy {cancelled} lenh dang cho)" if cancelled else ""))
    return web.json_response({"on": body["on"], "off": not body["on"], "cancelled": cancelled})


# ---- v30: cai dat / ghi chu / captcha cho man "Cong cu" cua app (cung hanh vi voi ,autocheck ,hbauto ,hbalert ,note ,captcha clear) ----
APP_TOGGLES = {   # ten gui tu app -> (khoa trong config, mac dinh khi chua dat)
    "auto_check": ("auto_check", "on"),
    "hb_auto": ("hb_auto", "on"),
    "hb_alert": ("hb_alert", "off"),
}


async def settings_snapshot():
    out = {name: (await get_config(key, default)) == "on" for name, (key, default) in APP_TOGGLES.items()}
    out["event_mode"] = await get_event_mode()
    out["app_on"] = not await is_app_off()
    out["captcha_active"] = bool((await get_captcha_state())["active"])
    return out


async def _read_json_body(request: web.Request):
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def handle_get_settings(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await settings_snapshot())


async def handle_post_settings(request: web.Request):
    """App bat/tat 1 cong tac. Body: {"key": "auto_check"|"hb_auto"|"hb_alert", "enabled": true|false}. Tra ve toan bo cai dat moi."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    body = await _read_json_body(request)
    key, enabled = body.get("key"), body.get("enabled")
    if key not in APP_TOGGLES or not isinstance(enabled, bool):
        return web.json_response({"error": "key phai la " + "/".join(APP_TOGGLES) + ", enabled phai la true/false"}, status=400)
    await set_config(APP_TOGGLES[key][0], "on" if enabled else "off")
    return web.json_response(await settings_snapshot())


async def notes_snapshot():
    rows = await mdb[COL_NOTES].find().sort([("done", 1), ("_id", 1)]).to_list(length=100)
    return {"notes": [{"id": r["_id"], "text": r.get("text", ""), "done": bool(r.get("done"))} for r in rows]}


async def handle_get_notes(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await notes_snapshot())


async def handle_post_notes(request: web.Request):
    """Body: {"action": "add", "text": "..."} hoac {"action": "done", "id": 3}. Tra ve danh sach ghi chu moi."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    body = await _read_json_body(request)
    action = body.get("action")
    if action == "add":
        text = str(body.get("text") or "").strip()[:500]
        if not text:
            return web.json_response({"error": "text khong duoc rong"}, status=400)
        nid = await next_note_id()
        await mdb[COL_NOTES].insert_one({"_id": nid, "text": text, "done": False, "created_at": _utcnow().isoformat()})
    elif action == "done":
        nid = body.get("id")
        if not isinstance(nid, int) or isinstance(nid, bool):
            return web.json_response({"error": "id phai la so"}, status=400)
        await mdb[COL_NOTES].update_one({"_id": nid}, {"$set": {"done": True}})
    else:
        return web.json_response({"error": "action phai la add hoac done"}, status=400)
    return web.json_response(await notes_snapshot())


async def handle_post_captcha_clear(request: web.Request):
    """App bao da giai captcha xong (giong `,captcha clear`)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    await mdb[COL_ALERTS].update_one(
        {"_id": "captcha"}, {"$set": {"active": False, "cleared_at": _utcnow().isoformat()}}, upsert=True)
    return web.json_response({"captcha_active": False})


# --- Màn "Công cụ" của app: các lệnh chỉ-đọc ,teamcheck ,zoodiff ,unlocked và acc phụ ,setalt ,testalt ---
# Chữ trả về đã bỏ ký hiệu Discord (**đậm**, `mã`, <:emoji:id>) để app hiện thẳng. Logic thuần ở tools_api.py.

async def handle_get_teamcheck(request: web.Request):
    """Như `,teamcheck`. Trả {"text": ..., "members": số thành viên đã chấm} (chưa có đội hình -> members 0 + text hướng dẫn)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        text, results = await build_team_check()
    except Exception as e:  # thiếu file luật vũ khí... — không để app nhận trang lỗi khó hiểu
        print(f"[tracker] Loi khi cham doi hinh cho app: {e!r}")
        return web.json_response({"error": "teamcheck_failed"}, status=500)
    return web.json_response({"text": tools_api.plain_text(text), "members": len(results)})


async def handle_get_zoodiff(request: web.Request):
    """Như `,zoodiff [d|now]`: ?kind=d|all|now|current (bỏ trống = loại ghi gần nhất).
    Trả {"ok": đã có kết quả so, "kind": "current"|"all"|null, "text": ...}; kind sai -> 400."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    state, text, kind = await zoodiff_report(request.query.get("kind", ""))
    if state == "bad_kind":
        return web.json_response({"error": "kind phai la d, all, now hoac current"}, status=400)
    return web.json_response({"ok": state == "ok", "kind": kind, "text": tools_api.plain_text(text)})


async def handle_get_unlocked(request: web.Request):
    """Như `,unlocked [tier]`: pet đã mở khóa theo tier (không kèm số lượng).
    Trả {"total": n, "tiers": [{"tier", "count", "pets": [tên]}]}; ?tier= sai -> 400 kèm danh sách tier có."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    rows = await _zoo_unlocked_rows()
    grouped = tools_api.group_unlocked(rows, request.query.get("tier", ""))
    if grouped is None:
        known = list(dict.fromkeys(str(r.get("tier")) for r in rows if r.get("name")))
        return web.json_response({"error": "khong co tier do", "tiers": known}, status=400)
    return web.json_response(grouped)


async def alt_snapshot():
    return {"alt_user_id": str(await get_config("alt_user_id", ALT_USER_ID_DEFAULT) or "")}


async def handle_get_alt(request: web.Request):
    """Acc phụ đang nhận DM nhắc huntbot (như `,setalt` không tham số). alt_user_id rỗng = đã tắt (tin nhắc gửi acc chính)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await alt_snapshot())


async def handle_post_alt(request: web.Request):
    """Như `,setalt <id>` / `,setalt xoa`. Body: {"user_id": "<dãy 15-25 chữ số>"} hoặc {"user_id": ""} để tắt. Sai -> 400."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    body = await _read_json_body(request)
    ok, uid = tools_api.parse_alt_id(body.get("user_id"))
    if not ok:
        return web.json_response({"error": "user_id phai la day so 15-25 chu so (hoac rong de tat)"}, status=400)
    await set_config("alt_user_id", uid)
    return web.json_response(await alt_snapshot())


async def handle_post_alt_test(request: web.Request):
    """Như `,testalt`: thử DM 1 tin vào acc phụ. Luôn 200, trả {"ok", "alt_user_id", "reason"}:
    reason = "" (ổn) | "no_alt" (chưa đặt acc phụ) | "dm_failed" (không DM được: khác server / tắt nhận tin riêng)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    alt_id = (await alt_snapshot())["alt_user_id"]
    if not alt_id:
        return web.json_response({"ok": False, "alt_user_id": "", "reason": "no_alt"})
    sent = await dm_user(alt_id, "🧪 Tin thử từ owo-tracker (bấm từ app Star Hub): acc phụ nhận được DM là ổn rồi.")
    return web.json_response({"ok": bool(sent), "alt_user_id": alt_id, "reason": "" if sent else "dm_failed"})


async def gemtier_snapshot():
    """Cài đặt tier gem cho app: mỗi loại có các tier được phép (✅), ưu tiên và gem còn trong kho."""
    slots = []
    for slot in GEM_SLOTS:
        allowed = await get_gem_allowed(slot)
        rows = await mdb[COL_INVENTORY].find(
            {"is_gem": True, "gem_slot": slot, "count": {"$gt": 0}}).sort("gem_tier_rank", -1).to_list(length=10)
        slots.append({
            "slot": slot, "name": gem_type_name(slot),
            "allowed": [t for t in GEM_TIERS if allowed is None or t in allowed],
            "pref": await get_gem_tier_pref(slot),
            "stock": [{"tier": r.get("gem_tier"), "count": r.get("count")} for r in rows],
        })
    return {"tiers": list(GEM_TIERS), "slots": slots}


async def handle_get_gemtier(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response(await gemtier_snapshot())


async def handle_post_gemtier(request: web.Request):
    """App lưu cài đặt tier. Body (có ít nhất 1 trong 2 khóa, chỉ đổi các loại có trong body):
      {"allowed": {"1": ["Common","Rare"], "4": []},      # tier được phép; rỗng = tắt hết
       "pref":    {"1": "highest", "4": "lowest", "3": "Rare"}}   # ưu tiên: highest | lowest | 1 tên tier
    Tier/loại lạ -> 400 (không đổi gì)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        body = await request.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    allowed, pref = body.get("allowed"), body.get("pref")
    if not (isinstance(allowed, dict) and allowed) and not (isinstance(pref, dict) and pref):
        return web.json_response({"error": "can allowed {loai: [tier,...]} va/hoac pref {loai: tier}"}, status=400)
    parsed_allowed, parsed_pref = {}, {}
    for slot, tiers in (allowed or {}).items() if isinstance(allowed, (dict, type(None))) else []:
        if slot not in GEM_SLOTS or not isinstance(tiers, list) or any(t not in GEM_TIERS for t in tiers):
            return web.json_response({"error": "loai gem hoac tier khong hop le", "slot": str(slot)}, status=400)
        parsed_allowed[slot] = set(tiers)
    if allowed is not None and not isinstance(allowed, dict):
        return web.json_response({"error": "allowed phai la object"}, status=400)
    if pref is not None and not isinstance(pref, dict):
        return web.json_response({"error": "pref phai la object"}, status=400)
    for slot, value in (pref or {}).items():
        if slot not in GEM_SLOTS or value not in ("highest", "lowest") + tuple(GEM_TIERS):
            return web.json_response({"error": "loai gem hoac uu tien khong hop le", "slot": str(slot)}, status=400)
        parsed_pref[slot] = value
    for slot, tiers in parsed_allowed.items():          # chi ghi khi TAT CA hop le
        await set_gem_allowed(slot, tiers)
    for slot, value in parsed_pref.items():
        await set_config(f"gem_tier_{slot}", value)
    print(f"[tracker][gemtier] App luu: duoc phep { {s: sorted(t) for s, t in parsed_allowed.items()} }, uu tien {parsed_pref}")
    return web.json_response(await gemtier_snapshot())


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
# HUNTBOT: nhac con 10 phut + tu chen lenh check khi app dang farm
# ----------------------------------------------------------------------
AUTO_REFRESH_TICK = 30        # giay giua 2 lan vong nen kiem tra
AUTO_EVAL_GAP = 90            # giay toi thieu giua 2 lan tinh "du lieu nao cu" (do ton truy van DB)
SLOWDOWN_BACKOFF = 300        # vua bi "Slow down" trong ngan nay thi KHONG chen them lenh
_auto_check_state = {"last_auto": 0.0, "last_eval": 0.0, "requested": {}}


def _epoch(dt) -> float:
    """datetime UTC khong mui gio -> so giay tu 1970."""
    return (dt - datetime(1970, 1, 1)).total_seconds()


async def _huntbot_timing(now):
    """Gio xong cua huntbot tu ban ghi moi nhat: {hunting, seconds_left, ready_epoch, observed_epoch}.
    ready_epoch (giay tu 1970) la gio huntbot ve; None neu khong dang san hoac chua biet."""
    row = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])
    out = {"hunting": False, "seconds_left": None, "ready_epoch": None, "observed_epoch": None}
    if not row:
        return out
    observed = _parse_utc(row.get("status_at") or row.get("created_at"))
    out["hunting"] = bool(row.get("hunting"))
    out["observed_epoch"] = _epoch(observed) if observed else None
    secs = duration_to_seconds(row.get("time_remaining")) if out["hunting"] else None
    if secs is not None and observed is not None:
        ready = observed + timedelta(seconds=secs)
        out["ready_epoch"] = int(_epoch(ready))
        out["seconds_left"] = max(0, int((ready - now).total_seconds()))
    return out


async def hb_reminder_tick(now):
    """Con <= 10 phut nua huntbot ve -> DM acc phu (CHI khi Ruby bat `,hbalert on`). Thong bao tren dien thoai
    do AutoMacro tu lam (hoi /alerts), nen day chi la ban du phong khi app khong chay."""
    if (await get_config("hb_alert", "off")) != "on":
        return None
    t = await _huntbot_timing(now)
    last = float(await get_config("hb_alert_ready", "0") or 0) or None
    if not auto_refresh.huntbot_alert_due(t["hunting"], t["seconds_left"], t["ready_epoch"], last):
        return None
    await set_config("hb_alert_ready", str(t["ready_epoch"]))   # danh dau TRUOC khi gui: loi gui cung khong lap lai
    mins = max(1, round(t["seconds_left"] / 60))
    await notify_owner(f"⏰ Huntbot còn khoảng {mins} phút nữa là về.", target="alt", min_gap=300)
    return mins


async def _slowdown_recent(now_ts, within=SLOWDOWN_BACKOFF) -> bool:
    doc = await mdb[COL_ALERTS].find_one({"_id": "slowdown"})
    ts = [float(x) for x in (doc or {}).get("ts", [])]
    return bool(ts) and now_ts - max(ts) <= within


async def _section_ages(now):
    """Tuoi (giay) cua tung muc tren Hub, dung dung ham dung Hub nen khop voi cai Ruby nhin thay."""
    await load_emoji_cache()
    builders = {"cowoncy": _hub_cowoncy, "inventory": _hub_inventory, "quest": _hub_quest,
                "weapon_shards": _hub_weapon_shards, "zoo": _hub_zoo}
    ages = {}
    for key, fn in builders.items():
        d = await fn(now)
        ages[key] = d.get("age_seconds") if d else None
    return ages


async def app_disabled_cmds():
    """Id các lệnh Ruby đang TẮT trong app (tab Setting -> Lệnh trong farm), đã lọc chỉ giữ id bot biết."""
    raw = await get_config("app_disabled_cmds", "")
    return sorted({x for x in str(raw or "").split(",") if x in auto_refresh.APP_CMD_TO_CHECK_KEY})


async def app_skipped_check_keys():
    return {auto_refresh.APP_CMD_TO_CHECK_KEY[x] for x in await app_disabled_cmds()}


async def handle_get_app_config(request: web.Request):
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({"disabled": await app_disabled_cmds()})


async def handle_post_app_config(request: web.Request):
    """App báo các lệnh farm đang TẮT. Body: {"disabled": ["zoo","inv",...]}. Id lạ bị bỏ qua; không phải danh sách chuỗi -> 400.
    Bot dùng để không xin app gõ xen những lệnh check đó (auto_check)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    body = await _read_json_body(request)
    lst = body.get("disabled")
    if not isinstance(lst, list) or not all(isinstance(x, str) for x in lst):
        return web.json_response({"error": "disabled phai la danh sach chuoi"}, status=400)
    keep = sorted({x.strip() for x in lst if x.strip() in auto_refresh.APP_CMD_TO_CHECK_KEY})
    await set_config("app_disabled_cmds", ",".join(keep))
    return web.json_response({"disabled": keep})


async def auto_check_tick(now_ts, now):
    """App DANG FARM -> du lieu nao cu thi xep 1 lenh check (app go xen vao giua luc farm, nhu lenh doi gem).
    App dang tat / khong farm -> KHONG tu go gi: Hub chi cap nhat theo nhung lenh Ruby tu go (bot doc moi tin OwO)."""
    if (await get_config("auto_check", "on")) != "on":
        return None
    if not farm_watch["active"] or farm_watch["resting"] or now_ts - farm_watch["last_seen"] > 60:
        return None
    if now_ts - _auto_check_state["last_auto"] < auto_refresh.AUTO_MIN_GAP:
        return None
    if now_ts - _auto_check_state["last_eval"] < AUTO_EVAL_GAP:
        return None
    if await is_app_off() or (await get_captcha_state(now))["active"]:
        return None
    fresh_cut = (now - timedelta(seconds=COMMAND_EXPIRE_SECONDS)).isoformat()
    if await mdb[COL_AUTOMACRO_COMMANDS].count_documents({"status": "pending", "created_at": {"$gte": fresh_cut}}):
        return None            # app con viec chua lam: dung chong them
    if await _slowdown_recent(now_ts):
        return None            # OwO vua bao gui qua day: lui lai, khong them lenh
    _auto_check_state["last_eval"] = now_ts
    t = await _huntbot_timing(now)
    pick = auto_refresh.pick_check(
        now_ts, {"hunting": t["hunting"], "ready_epoch": t["ready_epoch"], "observed_epoch": t["observed_epoch"]},
        await _section_ages(now), _auto_check_state["last_auto"], _auto_check_state["requested"],
        skip=await app_skipped_check_keys())
    if not pick:
        return None
    key, command = pick
    cid = await queue_automacro_command("auto_check", {"command_text": command, "kind": key})
    if cid is None:
        return None
    _auto_check_state["last_auto"] = now_ts
    _auto_check_state["requested"][key] = now_ts
    print(f"[tracker][auto_check] Xep lenh check '{command}' (muc {key} da cu)")
    return command


async def auto_refresh_loop():
    """Chay nen: moi 30 giay xem co can nhac huntbot / chen lenh check khong. Moi viec bat loi rieng."""
    while True:
        try:
            await asyncio.sleep(AUTO_REFRESH_TICK)
            if mdb is None:
                continue
            now, now_ts = _utcnow(), time.time()
            for name, coro in (("nhac huntbot", hb_reminder_tick(now)), ("auto_check", auto_check_tick(now_ts, now))):
                try:
                    await coro
                except Exception as e:
                    print(f"[tracker][{name}] Loi: {e!r}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[tracker][auto_refresh] Loi: {e!r}")


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
        now_iso = _utcnow().isoformat()
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
                {"$set": {"active": False, "cleared_at": _utcnow().isoformat()}})
            print("[tracker][captcha] OwO xac nhan da giai captcha - het canh bao")


async def get_captcha_state(now=None):
    """{'active': bool, 'at': iso, 'age_seconds': n}. Qua CAPTCHA_ACTIVE_SECONDS thi tu het hieu luc."""
    now = now or _utcnow()
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
    try:
        hb = await _huntbot_timing(_utcnow())
        huntbot = {k: hb[k] for k in ("hunting", "seconds_left", "ready_epoch")}
    except Exception as e:   # /alerts phai luon tra duoc (app dung no de canh captcha)
        print(f"[tracker] /alerts: khong doc duoc gio huntbot ({type(e).__name__}: {e})")
        huntbot = None
    return web.json_response({
        "captcha": await get_captcha_state(),
        "activity": {"last_reply_age_seconds": reply_age, "last_command_age_seconds": cmd_age},
        "off": await is_app_off(),
        "huntbot": huntbot,
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
    scope_guild, cid = await tracking_scope()
    if scope_guild:
        # Theo doi ca SERVER: mo Discord vao kenh Ruby farm gan nhat (neu biet), khong thi vao server
        last = await get_config("last_farm_channel_id")
        out = {"id": str(last or scope_guild), "name": None, "server": True,
               "link": f"https://discord.com/channels/{scope_guild}" + (f"/{last}" if last else "")}
        try:
            ch = bot.get_channel(int(last)) if last else None
            if ch is not None:
                out["name"] = getattr(ch, "name", None)
        except Exception as e:
            print(f"[tracker] Khong lay duoc ten kenh: {e!r}")
        return out
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
    now = now or _utcnow()
    await load_emoji_cache()
    return {
        "hub_version": 1,
        "bot_version": bot_version_text(),
        "server_time": now.isoformat() + "Z",
        "daily": await _hub_daily(now),
        "cowoncy": await _hub_cowoncy(now),
        "weapon_shards": await _hub_weapon_shards(now),
        "event": await _hub_event(now),
        "event_mode": await get_event_mode(),
        "slowdown": await _hub_slowdown(now),
        "gems": await _hub_gems(now),
        "huntbot": await _hub_huntbot(now),
        "quest": await _hub_quest(now),
        "team": await _hub_team(now),
        "zoo": await _hub_zoo(now),
        "inventory": await _hub_inventory(now),
        "weapons": await _hub_weapons(now),
        "weapon_review": await _hub_weapon_review(),
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
    app.router.add_post("/event-mode", handle_post_event_mode)
    app.router.add_post("/power", handle_post_power)
    app.router.add_get("/gemtier", handle_get_gemtier)
    app.router.add_post("/gemtier", handle_post_gemtier)
    app.router.add_post("/weapon-advice", handle_post_weapon_advice)
    app.router.add_post("/weapon-review", handle_post_weapon_review)
    app.router.add_post("/weapon-review/autoneon", handle_post_weapon_review_autoneon)
    app.router.add_post("/weapon-review/stop", handle_post_weapon_review_stop)
    app.router.add_get("/weapon-review/lists", handle_get_weapon_review_lists)
    app.router.add_post("/weapon-review/select", handle_post_weapon_review_select)
    app.router.add_get("/settings", handle_get_settings)
    app.router.add_post("/settings", handle_post_settings)
    app.router.add_get("/notes", handle_get_notes)
    app.router.add_post("/notes", handle_post_notes)
    app.router.add_post("/captcha/clear", handle_post_captcha_clear)
    app.router.add_get("/app-config", handle_get_app_config)
    app.router.add_post("/app-config", handle_post_app_config)
    app.router.add_get("/clean", handle_get_clean)
    app.router.add_get("/teamcheck", handle_get_teamcheck)
    app.router.add_get("/zoodiff", handle_get_zoodiff)
    app.router.add_get("/unlocked", handle_get_unlocked)
    app.router.add_get("/alt", handle_get_alt)
    app.router.add_post("/alt", handle_post_alt)
    app.router.add_post("/alt/test", handle_post_alt_test)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, AUTOMACRO_API_HOST, AUTOMACRO_API_PORT)
    try:
        await site.start()
    except OSError as e:   # cong dang bi chiem / khong co quyen: bao ro thay vi de task chet im lang
        print(f"[tracker] ❌ Khong mo duoc API AutoMacro o {AUTOMACRO_API_HOST}:{AUTOMACRO_API_PORT}: {e!r}")
        await runner.cleanup()
        return
    print(f"[tracker] API cho AutoMacro dang chay o {AUTOMACRO_API_HOST}:{AUTOMACRO_API_PORT}")


async def save_pet_species(p, source_id=None):
    key = p["name"].lower()
    hp, att, pr, wp, mag, mr = p["stats"]
    old = await mdb[COL_PET_SPECIES].find_one({"_id": key}) or {}
    aliases = list(p.get("aliases") or [p["name"]])
    for a in old.get("aliases") or []:      # giu bi danh da hoc truoc do (vd ten emoji trong zoo)
        if str(a).lower() not in {x.lower() for x in aliases}:
            aliases.append(a)
    await mdb[COL_PET_SPECIES].update_one(
        {"_id": key},
        {"$set": {
            "display_name": p["name"], "aliases": aliases,
            "rank": p["rank"], "rank_vi": p.get("rank_vi"),
            "hp": hp, "att": att, "pr": pr, "wp": wp, "mag": mag, "mr": mr,
            "count_seen": p["count"], "flavor_text": p.get("flavor_text"),
            "rarity_caught": p.get("rarity_caught"), "points": p.get("points"),
            "sell_cowoncy": p.get("sell_cowoncy"), "sell_sold_count": p.get("sell_sold_count"),
            "sacrifice_essence": p.get("sacrifice_essence"),
            "sacrifice_killed_count": p.get("sacrifice_killed_count"),
            "confirmed_at": _utcnow().isoformat(),
            "confirmed_by": source_id, "source": "owodex",
        }},
        upsert=True,
    )


async def save_weapon_type(w, source_id=None):
    key = w["type_name"].lower()
    update = {
        "display_name": w["type_name"],
        "confirmed_at": _utcnow().isoformat(),
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
            "effects": w.get("effects") or [],
            "wp_cost": w.get("wp_cost"), "sell_cowoncy": w.get("sell_cowoncy"), "sell_ws": w.get("sell_ws"),
            "rarity": w.get("rarity"), "wear": w.get("wear"),
            "owner_id": source_id, "updated_at": _utcnow().isoformat(),
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
                  "confirmed_at": _utcnow().isoformat(), "confirmed_by": source_id}},
        upsert=True,
    )


async def save_team(team):
    await mdb[COL_TEAM].delete_many({})
    if team:
        docs = []
        for m in team:
            d = dict(m)
            d["_id"] = d["pos"]
            d["updated_at"] = _utcnow().isoformat()
            docs.append(d)
        await mdb[COL_TEAM].insert_many(docs)


async def save_huntbot(h):
    """OwO tra 2 tin cho `owo hb`: (1) trang THONG TIN co chi so nang cap + essence (hunting=False vi
    khong noi gi ve dang san), (2) tin TRANG THAI ('STILL HUNTING... BACK IN 19H 41M'). Truoc day moi tin la
    1 dong rieng nen Hub nhay qua lai giua 2 loai. Gio gop thanh 1 ban ghi: tin nao den thi chi cap nhat
    phan cua minh, phan con lai giu nguyen tu ban ghi truoc."""
    h = dict(h)
    now_iso = _utcnow().isoformat()
    prev = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)]) or {}
    row = {k: v for k, v in prev.items() if k != "_id"}
    traits = h.get("traits")
    if h.get("essence") is not None:
        row["essence"] = h["essence"]
    if traits:                       # trang thong tin: cap nhat chi so + essence
        row["traits"] = traits
    # Tin trang thai: cap nhat dang san / tien do / thoi gian con lai. Truoc day OwO tach 2 tin nen tin co
    # chi so (traits) khong co trang thai; nay OwO GOP 1 tin -> neu tin co traits MA co ca phan trang thai
    # (status_seen) thi van phai cap nhat trang thai, neu khong Hub cu bao "khong chay" khi huntbot dang san.
    # v29: huntbot DA XONG / RANH: (a) tin co chu "I AM BACK WITH" (hunting=False + status_seen), hoac (b) trang
    # thong tin KHONG con chu trang thai nao trong khi truoc do dang san va da qua gio xong (OwO gop 1 tin: khi
    # huntbot khong san thi khong con muc "currently hunting"). Dung (b) chi khi truoc do bao dang san + da qua gio.
    finished_prev = False
    if prev.get("hunting"):
        obs = _parse_utc(prev.get("status_at") or prev.get("created_at"))
        secs = duration_to_seconds(prev.get("time_remaining"))
        finished_prev = obs is not None and secs is not None and _utcnow() >= obs + timedelta(seconds=secs)
    idle_by_absence = bool(traits) and not h.get("status_seen") and finished_prev
    idle = idle_by_absence or (bool(h.get("status_seen")) and h.get("hunting") is False)
    if (not traits) or h.get("status_seen") or idle_by_absence:
        for k in ("hunting", "progress_pct", "animals_captured", "time_remaining"):
            row[k] = h.get(k) if not idle_by_absence else (False if k == "hunting" else None)
        row["status_at"] = now_iso   # thoi diem QUAN SAT trang thai (de tinh gio xong cho dung)
    row["created_at"] = now_iso
    await mdb[COL_HUNTBOT].insert_one(row)
    return "idle" if idle else None


HB_AUTO_MIN_GAP = 1800   # giay: toi thieu giua 2 lan TU nho app chay lai huntbot


async def maybe_auto_hb_restart(source_id=None):
    """Huntbot vua ve/ranh -> tu nho app go `owo hb <thoi gian>` de OwO dua mat khau, bot chuyen anh sang acc phu,
    Ruby chi viec doc ma va nhan lai (khong tu giai). Bat/tat: `,hbauto on|off` (mac dinh BAT)."""
    if (await get_config("hb_auto", "on")) != "on":
        return False
    if await is_app_off():
        return False  # công tắc tổng `,off`: không nhờ app gõ gì cả
    now = time.time()
    try:
        last = float(await get_config("hb_auto_last", "0") or 0)
    except ValueError:
        last = 0.0
    if now - last < HB_AUTO_MIN_GAP or (now - hb_pending["at"]) <= HB_PENDING_SECONDS:
        return False
    amount = await get_config("hb_last_amount", "24h")
    await set_config("hb_auto_last", str(now))
    open_hb_window(amount)
    await queue_automacro_command("hb_start", {"command_text": f"owo hb {amount}"})
    await notify_owner(
        f"🤖 Huntbot vừa về. Mình đã nhờ app gõ `owo hb {amount}`. OwO sẽ đưa mật khẩu — mình chuyển ảnh sang acc phụ, "
        f"bạn đọc rồi nhắn lại đúng mã (tắt tự động: `,hbauto off`).", target="alt", min_gap=60)
    return True


async def save_quest(q):
    q = dict(q)
    q["created_at"] = _utcnow().isoformat()
    await mdb[COL_QUEST].insert_one(q)


async def save_daily(d):
    """Daily la 1 ban chup duy nhat, ghi de. Streak/phan thuong chi co trong tin
    "da nhan" — lan sau thay tin "chua toi gio" thi giu nguyen, khong xoa."""
    now = _utcnow()
    fields = {"state": d["state"], "updated_at": now.isoformat()}
    if d.get("seconds_until_next") is not None:
        fields["ready_at"] = (now + timedelta(seconds=d["seconds_until_next"])).isoformat()
    if d.get("streak") is not None:
        fields["streak"] = d["streak"]
    if d.get("reward") is not None:
        fields["last_reward"] = d["reward"]
    await mdb[COL_DAILY].update_one({"_id": "latest"}, {"$set": fields}, upsert=True)


async def save_weapon_shards(c, source_id=None):
    await mdb[COL_WEAPON_SHARDS].update_one(
        {"_id": "latest"},
        {"$set": {"amount": c["amount"], "updated_at": _utcnow().isoformat(),
                  "updated_by": source_id}},
        upsert=True,
    )


EVENT_LOG_KEEP = 40


async def save_event_hunt(events, message_id=None, source_id=None):
    """Moi loai su kien (theo bieu tuong dau dong) giu 1 bo dem moi nhat `counter:` + nhat ky `log:`
    (giu EVENT_LOG_KEEP dong gan nhat)."""
    now_iso = _utcnow().isoformat()
    for i, ev in enumerate(events):
        base = {"kind": ev["kind"], "current": ev["current"], "max": ev["max"], "text": ev["text"],
                "rewards": ev["rewards"], "updated_at": now_iso, "updated_by": source_id}
        await mdb[COL_EVENT].update_one({"_id": f"counter:{ev['kind']}"},
                                        {"$set": {**base, "type": "counter"}}, upsert=True)
        await mdb[COL_EVENT].update_one({"_id": f"log:{message_id or now_iso}:{i}"},
                                        {"$set": {**base, "type": "log"}}, upsert=True)
    logs = await mdb[COL_EVENT].find({"type": "log"}).sort("updated_at", -1).to_list(length=500)
    for old in logs[EVENT_LOG_KEEP:]:
        await mdb[COL_EVENT].delete_one({"_id": old["_id"]})
    cutoff = (_utcnow() - timedelta(days=3)).isoformat()
    await mdb[COL_EVENT].delete_many({"type": "counter", "updated_at": {"$lt": cutoff}})


async def save_cowoncy(c, source_id=None):
    await mdb[COL_COWONCY].update_one(
        {"_id": "latest"},
        {"$set": {"amount": c["amount"], "updated_at": _utcnow().isoformat(),
                  "updated_by": source_id}},
        upsert=True,
    )


# ----------------------------------------------------------------------
# LẮNG NGHE
# ----------------------------------------------------------------------
def bot_profile_text() -> str:
    """Mô tả bot hiện trên hồ sơ Discord (tối đa 400 ký tự), có số phiên bản."""
    return ("OwO Tracker " + bot_version_text() + " — theo dõi tài khoản chơi OwO, lưu vào MongoDB và trả lời qua lệnh Discord. "
            "Gõ ,help để xem danh sách lệnh.")[:400]


_profile_synced = {"done": False}


async def update_bot_profile():
    """Ghi số phiên bản vào TRẠNG THÁI bot và MÔ TẢ (About me) của ứng dụng. Chạy 1 lần mỗi lần bot khởi động;
    mỗi bước lỗi riêng thì chỉ in cảnh báo, không làm hỏng bot."""
    if _profile_synced["done"]:
        return
    _profile_synced["done"] = True
    try:
        await bot.change_presence(activity=discord.CustomActivity(name=bot_version_text() + " · ,help"))
    except Exception as e:
        print(f"[tracker] Không đặt được trạng thái bot: {e!r}")
    try:
        await bot.http.request(discord.http.Route("PATCH", "/applications/@me"), json={"description": bot_profile_text()})
        print("[tracker] Đã cập nhật mô tả bot: " + bot_profile_text())
    except Exception as e:
        print(f"[tracker] Không cập nhật được mô tả bot (không sao, vẫn chạy bình thường): {e!r}")


@bot.event
async def on_ready():
    print(f"[tracker] Đăng nhập: {bot.user} · bot {bot_version_text()} (discord.py {discord.__version__})")
    await update_bot_profile()
    if mdb is None:
        print("[tracker] CẢNH BÁO: chưa có MONGODB_URI — bot sẽ lỗi khi cố lưu/đọc dữ liệu.")
        return
    tracked = await get_config("tracked_user_id")
    print(f"[tracker] Đang theo dõi user ID: {tracked or '(chưa đặt — dùng ,track)'}")

    global _farm_watchdog_task
    if _farm_watchdog_task is None or _farm_watchdog_task.done():
        _farm_watchdog_task = asyncio.create_task(farm_watchdog())

    global _auto_refresh_task
    if _auto_refresh_task is None or _auto_refresh_task.done():
        _auto_refresh_task = asyncio.create_task(auto_refresh_loop())

    global _automacro_api_started
    if AUTOMACRO_API_TOKEN:
        if not _automacro_api_started:
            _automacro_api_started = True
            if len(AUTOMACRO_API_TOKEN) < 24:
                print("[tracker] ❌ AUTOMACRO_API_TOKEN ngắn (<24 ký tự) — API cho AutoMacro KHÔNG chạy. "
                      "Hãy dùng chuỗi ngẫu nhiên dài hơn (vd `openssl rand -hex 24`), vì API này mở ra internet "
                      "và chỉ được bảo vệ bằng token.")
            else:
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


_TYPED_DEX_RE = re.compile(r"(?:^|\s)(?:dex|owodex|odex)\s+([A-Za-z0-9_]{1,32})\s*$")


def typed_dex_name(message, tracked_id=None):
    """Ten pet ma ban/app DA GO trong `owo dex <ten>` de ra embed nay: uu tien tin OwO reply toi
    (message.reference.resolved.content); khong co thi lay lenh dex gan day trong kenh NEU chi co dung 1 lenh.
    Ten nay co the la ten emoji trong zoo (khong nam trong dong Alias cua dex) nen can ghi nhan lam bi danh."""
    ref = getattr(message, "reference", None)
    resolved = getattr(ref, "resolved", None) if ref else None
    content = (getattr(resolved, "content", None) or "").strip().lower()
    m = _TYPED_DEX_RE.search(content) if content else None
    if m:
        return m.group(1)
    now = time.time()
    names = {mm.group(1) for ts, body in recent_owo_commands.get(message.channel.id, []) if now - ts < 120
             for mm in [_TYPED_DEX_RE.search(body)] if mm}
    return next(iter(names)) if len(names) == 1 else None


async def dex_wanted_names() -> set:
    """Ten pet (thuong) ma Tom dang CAN dex: pet dang giu trong zoo, pet vua nho app tra, lenh dex dang cho."""
    wanted = set(_dex_requested)
    zoo = await mdb[COL_ZOO].find_one({"_id": "latest"})
    for p in (zoo or {}).get("pets", []):
        if p.get("name"):
            wanted.add(str(p["name"]).lower())
    async for c in mdb[COL_AUTOMACRO_COMMANDS].find({"status": "pending", "action": "dex_pet"}):
        wanted.add(str((c.get("params") or {}).get("pet", "")).lower())
    wanted.discard("")
    return wanted


async def accept_dex_by_alias(message, tracked_id) -> bool:
    """Embed owodex do OwO tra ve TRE (qua cua so doi lenh) hoac duoc SUA sau van duoc nhan, miễn là
    alias trong embed khop ten/id cua 1 pet Tom dang can. Dex la thong tin chung cua game nen khong can
    biet ai go lenh; rieng 'Count' la so cua nguoi go, nen tin cua nguoi khac thi bo Count.
    Tra ve True neu da luu."""
    text = flatten_message(message)
    pet = parse_owodex(text)
    if not pet:
        return False
    wanted = await dex_wanted_names()
    names = [str(a).lower() for a in (pet.get("aliases") or [pet["name"]])]
    typed = typed_dex_name(message, tracked_id)
    if typed and typed.lower() in wanted and typed.lower() not in names:
        # Ten dang go (vd ten emoji zoo) khong co trong dong Alias -> hoc lam bi danh, de lan sau zoo khop duoc dex
        pet = dict(pet, aliases=list(pet.get("aliases") or [pet["name"]]) + [typed.lower()])
        names.append(typed.lower())
    if not wanted.intersection(names):
        return False
    verdict, _who = owner_verdict(text, tracked_id, await tracked_name_set(tracked_id))
    if verdict == "other":
        pet = dict(pet, count="")
    await save_pet_species(pet, tracked_id)
    await record_raw("owodex", text, pet, message)
    for a in pet.get("aliases") or [pet["name"]]:
        _dex_requested.pop(str(a).lower(), None)
    _dex_requested.pop(str(typed or "").lower(), None)
    print(f"[tracker] Đã nhận dex {pet['name']} theo alias (embed có thể đến trễ).")
    return True


@bot.event
async def on_raw_message_edit(payload):
    """Bam tab Daily/Weekly/Quests trong Quest Log la SUA tin cu chu khong gui tin moi. Doc lai tin da sua
    de co du lieu checklist Weekly va tab Quests (khong can ban go lai owo quest)."""
    try:
        if mdb is None:
            return
        data = payload.data or {}
        author_id = (data.get("author") or {}).get("id")
        if str(author_id) != str(OWO_BOT_ID):   # khong doc tin bot NeonUtil (xem NEON_BOT_ID)
            return
        scope_guild, scope_channel = await tracking_scope()
        if not scope_allows(scope_guild, scope_channel, getattr(payload, "guild_id", None), payload.channel_id,
                            parse_id_list(await get_config("ignored_channel_ids"))):
            return
        channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        if await accept_dex_by_alias(message, await get_config("tracked_user_id")):
            return
        text = flatten_message(message)
        wlist = parse_weapon_list(text)
        if wlist:
            tid = await get_config("tracked_user_id")
            if await weapon_list_accepted(text, tid):
                await save_weapon_list(wlist, tid)
            return
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
    scope_guild, scope_channel = await tracking_scope()
    if not scope_allows(scope_guild, scope_channel, getattr(message.guild, "id", None) if message.guild else None, message.channel.id,
                        parse_id_list(await get_config("ignored_channel_ids"))):
        await bot.process_commands(message)
        return
    scoped = bool(scope_guild or scope_channel)

    tracked_id = await get_config("tracked_user_id")
    prefixes = await get_owo_prefixes()
    content_lower = message.content.lower()

    if tracked_id and str(message.author.id) == str(tracked_id) \
            and any(content_lower.startswith(p) for p in prefixes):
        pending_commands[message.channel.id] = time.time()
        farm_watch["last_command_at"] = time.time()
        if scope_guild:
            await remember_farm_channel(message.channel.id)
        mt = _HB_TYPED_RE.match(content_lower.strip())
        if mt:
            open_hb_window(mt.group(1))
        last_owo_command[message.channel.id] = content_lower
        record_recent_command(message.channel.id, content_lower, prefixes)
        mw = re.match(r"^\S+\s+w\s+([a-z0-9]{4,8})$", content_lower.strip())
        if mw:
            await review_note_message(message, mw.group(1))
        author = message.author
        tracked_names[str(author.id)] = {
            n for n in (getattr(author, "display_name", None), getattr(author, "global_name", None),
                        getattr(author, "nick", None), getattr(author, "name", None)) if n
        }
        await bot.process_commands(message)
        return

    if message.author.id == NEON_BOT_ID:
        try:
            await autoneon_handle_neon(message)   # dong gon Neon tu tra loi `owo w` (chi khi dang tu duyet)
        except Exception as e:
            print(f"[tracker][autoneon] Loi doc tin Neon: {e!r}")
        # Chi nhan DUNG file `nw inv export` Neon tra loi lenh cua chinh Ruby (tat bang `,neonauto off`); tin khac cua Neon bo qua
        try:
            await handle_neon_export_reply(message)
        except Exception as e:
            print(f"[tracker][neon] Loi nhan file export: {e!r}")
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

    if message.author.id == OWO_BOT_ID:
        try:
            if await accept_dex_by_alias(message, tracked_id):
                await bot.process_commands(message)
                return
        except Exception as e:
            print(f"[tracker][dex] Loi nhan dex theo alias: {e!r}")

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
        elif scoped and await tracked_name_set(tracked_id):
            # v29: da chon kenh (,setchannel) hoac ca server (,setserver) -> doc MOI tin OwO, khong can cho lenh
            # (tin su kien tu bung ra, lenh go tat nhu Oah/Oq...). Tin cua nguoi khac van bi loc
            # theo ten/<@id>/reply. CHI khi bot da biet ten cua ban (tracked_names nam trong RAM,
            # mat sau moi lan khoi dong lai): chua biet ten thi khong loc duoc tin nguoi khac,
            # nen quay ve cach cu (chi doc trong cua so sau lenh) cho den khi ban nhan tin 1 lan.
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
    "weapon_shards": "owo ws",
    "event_hunt": "owo hunt (khi dang co su kien — dong [x/10])",
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
        "at": _utcnow().isoformat() + "Z",
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
        "at": _utcnow().isoformat() + "Z",
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
    # Nhan dien chu bang <@id> (tieu de "<@id>'s Quest Log", ping dau tin) roi toi ten o dong dau / tieu de.
    names = await tracked_name_set(source_id)
    verdict, who = owner_verdict(text, source_id, names)
    if verdict == "other":
        print(f"[tracker] Bo qua tin cua '{who}' (khong khop {sorted(names) or source_id})")
        skipped_foreign["name"] = who
        skipped_foreign["count"] += 1
        await record_raw("foreign_skipped", text, {"ten_trong_tin": who, "ten_chap_nhan": sorted(names)}, message)
        return

    await remember_emojis(text)
    recognized = False  # co loai nao nhan ra tin nay khong (neu khong -> ghi vao "unrecognized")

    if re.search(r"Slow down and try the command again", text):
        await record_slowdown()
        await record_raw("slowdown", text, {"slowdown": True}, message)
        recognized = True

    event_lines = parse_event_hunt(text, source_id)
    if event_lines:
        await save_event_hunt(event_lines, getattr(message, "id", None), source_id)
        await record_raw("event_hunt", text, {"events": event_lines}, message)
        recognized = True

    pet = parse_owodex(text)
    if pet:
        await save_pet_species(pet, source_id)
        await record_raw("owodex", text, pet, message)
        recognized = True

    wlist = parse_weapon_list(text)
    if wlist:
        # chi nhan danh sach CUA MINH: tieu de "<@id>'s Weapons" (khi quet cho duyet vu khi thi BAT BUOC co mention dung)
        if await weapon_list_accepted(text, source_id):
            await save_weapon_list(wlist, source_id)
            await record_raw("weapon_list", text, {"so_cay_trang_nay": len(wlist)}, message)
            recognized = True

    if _WEAPON_NOT_FOUND_RE.search(text):
        recognized = True
        await record_raw("weapon_not_found", text, {"not_found": True}, message)
        await review_skip_missing(message)

    weapon = parse_weapon_detail(text)
    if weapon:
        # Chỉ ghi vũ khí của CHÍNH người đang theo dõi: owo weapon <ID> xem được cả
        # vũ khí của người khác (tiêu đề ghi tên chủ) — không được lẫn vào dữ liệu của bạn.
        names = set(tracked_names.get(str(source_id), set()))
        aliases = await get_config("weapon_owner_aliases", "") or ""
        names |= {a.strip() for a in aliases.split(",") if a.strip()}
        owner_ok = weapon_owner_matches(weapon.get("owner"), names)
        recognized = True
        await review_note_message(message, weapon.get("id") or "")
        await auto_feed_detail(message, weapon)
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
    if hunt and verdict != "mine" and reply_target(message, source_id) != "ban" \
            and not command_recent(message.channel.id, HB_COMMAND_RE):
        # Tin huntbot KHONG co ten nguoi choi: chi nhan khi chac la cua ban (ping/reply cho ban) hoac ban vua go
        # lenh hb. Neu khong, do la `owo hb` cua nguoi khac trong server va se ghi de gio huntbot cua ban.
        print("[tracker] Bo qua tin huntbot khong gan duoc voi lenh/ten cua ban (co the cua nguoi khac)")
        await record_raw("foreign_skipped", text, {"ten_trong_tin": None, "ly_do": "huntbot khong ro chu"}, message)
        recognized = True
        hunt = None
    if hunt:
        hb_state = await save_huntbot(hunt)
        await record_raw("huntbot", text, hunt, message)
        if hb_state == "idle":
            try:
                await maybe_auto_hb_restart(source_id)
            except Exception as e:
                print(f"[tracker][hb] Loi tu chay lai huntbot: {e!r}")
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

    shards = parse_weapon_shards(text)
    if shards:
        await save_weapon_shards(shards, source_id)
        await record_raw("weapon_shards", text, shards, message)
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
    now = _utcnow()
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
    if "star" in todo and not await get_event_mode():
        # Gem Special chi dung duoc khi dang co su kien -> chi khi Ruby da BAT che do Event
        todo.discard("star")
        print("[tracker][gem] bo qua gem Special: che do Event dang TAT")
    if not todo:
        print(f"[tracker][gem] bo qua nhac slot {sorted(slots)}: vua co lenh thay trong {SWAP_COOLDOWN_SECONDS}s")
        return

    picks = []  # (slot, vien duoc chon)
    for slot in sorted(todo):
        # Luon liet ke tier CAO -> THAP; viec chon vien nao do `,gemtier` quyet dinh (pick_gem_option).
        options = await mdb[COL_INVENTORY].find(
            {"is_gem": True, "gem_slot": slot, "count": {"$gt": 0}}
        ).sort("gem_tier_rank", -1).to_list(length=10)
        in_stock = options
        # Chi dung tier da BAT cho loai gem nay (`,gemtier bat/tat`); mac dinh bat het
        options = filter_allowed_gems(options, await get_gem_allowed(slot))
        if slot in slots:  # chi nhac trong kenh cho slot MOI het, khong nhac lai slot cu
            if in_stock and not options:
                stock_text = ", ".join("%s ×%s" % (o["gem_tier"], o["count"]) for o in in_stock)
                await message.channel.send(
                    f"<@{source_id}> ⚠️ Gem {gem_type_name(slot)} vừa hết độ bền, kho còn {stock_text} "
                    f"nhưng các tier này đang TẮT (`,gemtier bat {slot} <tier>` để cho phép). Bot không tự thay.")
            elif not options:
                await message.channel.send(
                    f"<@{source_id}> ⚠️ Gem {gem_type_name(slot)} vừa hết, và trong kho không còn viên nào cùng loại để thay. "
                    f"Cần farm/mua thêm.")
            else:
                lines = [f"`owo use {o['_id']}` — {o['gem_tier']} (còn {o['count']})" for o in options]
                await message.channel.send(
                    f"<@{source_id}> ⚠️ Gem {gem_type_name(slot)} vừa hết độ bền! Chọn 1 trong các lựa chọn còn lại:\n" + "\n".join(lines))
        if options:
            # Tier chi con rat it vien thi giu lai (neu con tier khac), roi chon theo so thich tier cua loai gem nay
            usable = [o for o in options if (o.get("count") or 0) > GEM_KEEP_IF_COUNT_AT_MOST] or options
            picks.append((slot, pick_gem_option(usable, await get_gem_tier_pref(slot))))

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


@bot.command(name="autocheck")
@is_owner()
async def autocheck_cmd(ctx, state: str = ""):
    """`,autocheck` = xem · `,autocheck on` / `off`: khi app dang farm, bot nho app go xen cac lenh check
    (owo hb/cash/inv/quest/ws/zoo/team) cho muc nao da cu, de Hub luon moi."""
    st = state.strip().lower()
    if st in ("on", "bat", "bật"):
        await set_config("auto_check", "on")
    elif st in ("off", "tat", "tắt"):
        await set_config("auto_check", "off")
    elif st not in ("", "status", "xem"):
        await ctx.send("Dùng: `,autocheck on` · `,autocheck off` · `,autocheck` (xem trạng thái)")
        return
    on = (await get_config("auto_check", "on")) == "on"
    farming = farm_watch["active"] and not farm_watch["resting"]
    plan = ", ".join(f"{cmd} ({age // 60 if age < 3600 else age // 3600}{'p' if age < 3600 else 'h'})"
                     for _, cmd, age in auto_refresh.CHECK_PLAN)
    await ctx.send(("🟢 Tự chen lệnh check: **BẬT**" if on else "🔴 Tự chen lệnh check: **TẮT**")
                   + f" · app {'đang farm' if farming else 'không farm (bot chỉ đọc theo lệnh bạn tự gõ)'}.\n"
                   f"Chỉ chen khi app **đang farm**, tối đa 1 lệnh mỗi {auto_refresh.AUTO_MIN_GAP // 60} phút, "
                   f"lùi lại khi OwO báo Slow down / captcha. Lệnh & tuổi dữ liệu tối đa: `owo hb` (đến hạn / 3h), {plan}.")


@bot.command(name="hbalert")
@is_owner()
async def hbalert_cmd(ctx, state: str = ""):
    """`,hbalert on` = DM acc phu khi huntbot con 10 phut nua ve (ban du phong cho thong bao tren app)."""
    st = state.strip().lower()
    if st in ("on", "bat", "bật"):
        await set_config("hb_alert", "on")
    elif st in ("off", "tat", "tắt"):
        await set_config("hb_alert", "off")
    elif st not in ("", "status", "xem"):
        await ctx.send("Dùng: `,hbalert on` · `,hbalert off` · `,hbalert` (xem trạng thái)")
        return
    on = (await get_config("hb_alert", "off")) == "on"
    await ctx.send(("🟢 Nhắc huntbot qua DM: **BẬT**" if on else "🔴 Nhắc huntbot qua DM: **TẮT**")
                   + " (thông báo trên điện thoại do app AutoMacro tự gửi, không phụ thuộc lệnh này).")


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
        "tao_luc": _utcnow().isoformat() + "Z",
        "kenh_gioi_han": await get_config("tracked_channel_id") or None,
        "server_gioi_han": await get_config("tracked_guild_id") or None,
        "kenh_bo_qua": parse_id_list(await get_config("ignored_channel_ids")),
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
    await set_config("tracked_guild_id", "")   # gioi han 1 kenh thay cho gioi han ca server
    await ctx.send(f"Đã giới hạn: owo-tracker giờ CHỈ xử lý lệnh/tin nhắn OwO trong <#{channel_id}>.")


# ----------------------------------------------------------------------
# ZOO -> DEX: pet nao dang giu ma chua co thong tin dex thi nho app go `owo dex <pet>`
# ----------------------------------------------------------------------
DEX_BATCH_MAX = 20                 # toi da bay nhieu pet moi lan (app go cach nhau 2,5-5,5 giay, lenh het han sau 10 phut)
DEX_RETRY_SECONDS = 15 * 60        # da nho app tra 1 pet ma chua thay dex -> cho bay nhieu giay moi nho lai
ZOO_STALE_SECONDS = 6 * 3600       # zoo cu hon thi nhac nen `owo zoo` lai truoc
_dex_requested = {}                # ten pet (thuong) -> time.time() luc nho app tra dex


def _dex_name_ok(name) -> bool:
    """Ten pet se duoc GO vao Discord nen chi nhan chu/so/gach duoi (ten emoji cua OwO)."""
    return bool(re.fullmatch(r"[A-Za-z0-9_]{1,32}", str(name)))


def dex_gaps(row) -> list:
    """Dex cua 1 loai pet con THIEU gi? Tra ve danh sach ten truong thieu ([] = day du).
    Ban ghi co ton tai nhung thieu rank / chi so / nguon owodex (vd nhap tay bang ,petset) van tinh la thieu,
    vi `owo dex` moi cho du chi so, flavor, diem, gia ban..."""
    gaps = []
    if not str(row.get("rank") or "").strip():
        gaps.append("rank")
    if any(not isinstance(row.get(k), int) for k in ("hp", "att", "pr", "wp", "mag", "mr")):
        gaps.append("chỉ số")
    if row.get("source") not in ("owodex", "manual"):
        gaps.append("không rõ nguồn")
    elif row.get("source") == "manual":
        gaps.append("nhập tay, chưa tra owodex")
    return gaps


async def zoo_pets_missing_dex():
    """Tu ZOO HIEN TAI: pet nao dang giu (so luong > 0) ma chua co dex HOAC dex con thieu thong tin.
    Khop theo ten HOAC bi danh trong dex. Tra ve None neu chua co zoo; nguoc lai
    {"missing": [ten...], "incomplete": {ten: [truong thieu]}, "held": so_pet_dang_giu, "updated_at": ...}.
    `missing` gom ca pet chua co dex lan pet co dex thieu (de nho app tra lai)."""
    zoo = await mdb[COL_ZOO].find_one({"_id": "latest"})
    if not zoo or not zoo.get("pets"):
        return None
    known = {}      # ten/bi danh (thuong) -> ban ghi dex
    async for r in mdb[COL_PET_SPECIES].find({}):
        known[str(r["_id"]).lower()] = r
        known.setdefault(str(r.get("display_name") or "").lower(), r)
        for a in r.get("aliases") or []:
            known.setdefault(str(a).lower(), r)
    held, tier_of = {}, {}
    for p in zoo["pets"]:
        # KE CA pet so luong 0 (da hy sinh het): van la loai pet that, dex van tra duoc va can co
        if p.get("name"):
            held.setdefault(str(p["name"]).lower(), str(p["name"]))
            tier_of.setdefault(str(p["name"]).lower(), p.get("tier") or "?")
    absent, incomplete = [], {}
    for k, n in held.items():
        row = known.get(k)
        if row is None:
            absent.append(n)
        else:
            gaps = dex_gaps(row)
            if gaps:
                incomplete[n] = gaps
    missing = sorted(absent + list(incomplete), key=str.lower)
    by_tier = {}
    for n in missing:
        by_tier.setdefault(tier_of.get(n.lower(), "?"), []).append(n)
    # Tier ma OwO bao co pet (dong tong ket cuoi zoo) nhung bot khong doc duoc ten pet nao -> khong the check dex
    read_tiers = set(tier_of.values())
    unread = sorted(t for t, c in parse_zoo_breakdown(zoo.get("breakdown_raw")).items() if c > 0 and t not in read_tiers)
    return {"missing": missing, "absent": sorted(absent, key=str.lower), "incomplete": incomplete,
            "held": len(held), "updated_at": zoo.get("updated_at"), "by_tier": by_tier, "unread_tiers": unread}


@bot.command(name="zoodex", aliases=["dexzoo"])
@is_owner()
async def zoodex_cmd(ctx, mode: str = ""):
    """Check zoo hien tai: pet nao CHUA co thong tin dex thi nho app go `owo dex <pet>` cho tung con.
    `,zoodex` = nho app tra (toi da 20 con moi lan, gõ lai de lam tiep) · `,zoodex xem` = chi liet ke, khong nho app."""
    info = await zoo_pets_missing_dex()
    if info is None:
        await ctx.send("Chưa có dữ liệu zoo. Gõ `owo zoo` trong Discord để bot đọc zoo, rồi thử lại `,zoodex`.")
        return
    stale = ""
    updated = _parse_utc(info["updated_at"])
    if updated and (_utcnow() - updated).total_seconds() > ZOO_STALE_SECONDS:
        stale = f"\n⚠️ Zoo đọc lần cuối cách đây {int((_utcnow() - updated).total_seconds() // 3600)} giờ — nên gõ `owo zoo` lại cho đúng."
    if info["unread_tiers"]:
        stale += ("\n⚠️ Chưa đọc được tên pet của tier: " + ", ".join(info["unread_tiers"])
                  + " — các pet đó chưa check dex được; gõ lại `owo zoo` (đủ các trang).")
    missing = info["missing"]
    if not missing:
        await ctx.send(f"✅ Cả {info['held']} loại pet đang giữ trong zoo đều đã có dex đầy đủ.{stale}")
        return
    inc = info["incomplete"]
    if mode.strip().lower() in ("xem", "list", "ds"):
        absent = info["absent"]
        parts = [f"📖 {len(missing)}/{info['held']} loại pet trong zoo cần tra dex "
                 f"({len(absent)} chưa có, {len(inc)} có nhưng thiếu)."]
        if absent:
            parts.append("Chưa có: " + ", ".join(f"`{n}`" for n in absent[:40]) + (f" … (+{len(absent) - 40})" if len(absent) > 40 else ""))
        if inc:
            items = list(inc.items())
            parts.append("Thiếu: " + ", ".join(f"`{n}` ({'/'.join(g)})" for n, g in items[:25]) + (f" … (+{len(items) - 25})" if len(items) > 25 else ""))
        if info["by_tier"]:
            parts.append("Theo tier: " + " · ".join(f"{t} {len(v)}" for t, v in sorted(info["by_tier"].items())))
        if info["unread_tiers"]:
            parts.append("⚠️ Tier OwO báo có pet nhưng bot CHƯA đọc được tên pet nào: " + ", ".join(info["unread_tiers"])
                         + " — gõ lại `owo zoo` (đủ các trang) để bot đọc.")
        parts.append("Gõ `,zoodex` để nhờ app tra." + stale)
        await ctx.send("\n".join(parts)[:1900])
        return

    now_ts = time.time()
    pending = set()
    async for c in mdb[COL_AUTOMACRO_COMMANDS].find({"status": "pending", "action": "dex_pet"}):
        pending.add(str((c.get("params") or {}).get("pet", "")).lower())
    bad = [n for n in missing if not _dex_name_ok(n)]
    recent = [n for n in missing if _dex_name_ok(n)
              and (n.lower() in pending or now_ts - _dex_requested.get(n.lower(), 0) < DEX_RETRY_SECONDS)]
    todo = [n for n in missing if _dex_name_ok(n) and n not in recent]
    batch = todo[:DEX_BATCH_MAX]
    queued = []
    for n in batch:
        cid = await queue_automacro_command("dex_pet", {"command_text": f"owo dex {n}", "pet": n})
        if cid is None:
            break
        _dex_requested[n.lower()] = now_ts
        queued.append(n)
    lines = [f"📖 Zoo có {info['held']} loại pet, **{len(missing)}** cần tra dex ({len(info['absent'])} chưa có, {len(inc)} có nhưng thiếu thông tin)."]
    if queued:
        secs = len(queued) * 7
        lines.append(f"Đã nhờ app gõ `owo dex` cho **{len(queued)}** pet: " + ", ".join(f"`{n}`" for n in queued[:30])
                     + f" (khoảng {secs // 60} phút {secs % 60} giây; cần Hub nổi đang BẬT).")
    elif todo:
        lines.append("Không xếp được lệnh nào cho app (app đang TẮT?).")
    not_queued = len(todo) - len(queued)   # vuot gioi han moi luot (hoac khong xep duoc)
    if queued and not_queued:
        lines.append(f"Còn {not_queued} pet chưa xếp — gõ lại `,zoodex` sau khi app xong lượt này.")
    if recent:
        lines.append(f"{len(recent)} pet đã nhờ app tra gần đây mà chưa thấy dex (chờ hoặc tên không tra được): "
                     + ", ".join(f"`{n}`" for n in recent[:15]) + ".")
    if bad:
        lines.append(f"Bỏ qua {len(bad)} tên lạ (không an toàn để gõ): " + ", ".join(f"`{n}`" for n in bad[:5]) + ".")
    await ctx.send("\n".join(lines) + stale)


@bot.command(name="setserver")
@is_owner()
async def setserver_cmd(ctx, *, arg: str = ""):
    """Gioi han owo-tracker theo doi CA 1 SERVER (moi kenh trong server do) thay vi 1 kenh duy nhat.
    Bot doc moi tin OwO + lenh owo cua ban o MOI kenh cua server nay; server khac / tin rieng bi bo qua.
    Dung: ,setserver here (server dang go lenh) · ,setserver <ID server> · ,setserver xoa (bo gioi han).
    Khong kem gi: xem trang thai. Dat server se bo gioi han 1 kenh (,setchannel), va nguoc lai."""
    arg = arg.strip()
    current = await get_config("tracked_guild_id")
    if not arg:
        if current:
            g = bot.get_guild(int(current)) if str(current).isdigit() else None
            await ctx.send(f"Đang theo dõi cả server **{g.name if g else current}** (`{current}`) — mọi kênh trong server.\n"
                           f"Đổi: `,setserver here` · Bỏ giới hạn: `,setserver xoa`")
        else:
            await ctx.send("Chưa giới hạn server nào. Theo dõi cả server: `,setserver here` (gõ trong server đó)")
        return
    if arg.lower() in ("xoa", "xóa", "clear"):
        await set_config("tracked_guild_id", "")
        await ctx.send("Đã bỏ giới hạn server.")
        return
    if arg.lower() in ("here", "day", "đây", "nay"):
        if ctx.guild is None:
            await ctx.send("Lệnh này phải gõ trong một server (không phải tin nhắn riêng), hoặc dùng `,setserver <ID server>`.")
            return
        gid = str(ctx.guild.id)
    else:
        gid = arg.strip()
        if not gid.isdigit():
            await ctx.send("Không đọc được server. Dùng: `,setserver here` hoặc dán ID server.")
            return
    await set_config("tracked_guild_id", gid)
    await set_config("tracked_channel_id", "")   # theo doi ca server thay cho gioi han 1 kenh
    g = bot.get_guild(int(gid))
    await ctx.send(f"Đã chuyển sang theo dõi cả server **{g.name if g else gid}** — bot giờ đọc lệnh owo và tin OwO ở MỌI kênh "
                   f"của server này (server khác bị bỏ qua).")


@bot.command(name="ignorechannel", aliases=["boqua"])
@is_owner()
async def ignorechannel_cmd(ctx, *, arg: str = ""):
    """Bo qua 1 kenh trong server dang theo doi: Tom khong doc lenh owo cua ban va tin OwO o kenh do.
    Dung: ,ignorechannel here (kenh dang go) · ,ignorechannel #kenh (hoac ID) · ,ignorechannel xoa #kenh (bo bo qua)
    · ,ignorechannel xoa (bo het) · khong kem gi: xem danh sach. Lenh cua chinh Tom van dung duoc o moi kenh."""
    arg = arg.strip()
    current = parse_id_list(await get_config("ignored_channel_ids"))
    low = arg.lower()
    if not arg or low in ("list", "ds", "xem"):
        if current:
            await ctx.send("🙈 Tom đang BỎ QUA các kênh: " + ", ".join(f"<#{c}>" for c in current)
                           + "\nBỏ qua thêm: `,ignorechannel here` · Bỏ bớt: `,ignorechannel xoa #kênh`")
        else:
            await ctx.send("Chưa bỏ qua kênh nào. Bỏ qua kênh này: `,ignorechannel here` (gõ ngay trong kênh đó).")
        return
    remove = False
    for w in ("xoa", "xóa", "clear", "bo", "bỏ"):
        if low == w or low.startswith(w + " "):
            remove, arg = True, arg[len(w):].strip()
            break
    if remove and not arg:
        await set_config("ignored_channel_ids", "")
        await ctx.send("Đã bỏ danh sách kênh bị bỏ qua — Tom theo dõi lại mọi kênh trong phạm vi.")
        return
    if arg.lower() in ("here", "day", "đây", "nay"):
        cid = str(ctx.channel.id)
    else:
        cid = arg.strip("<#>").strip()
    if not cid.isdigit():
        await ctx.send("Không đọc được kênh. Dùng: `,ignorechannel here`, `,ignorechannel #kênh` hoặc dán ID kênh.")
        return
    if remove:
        if cid not in current:
            await ctx.send(f"<#{cid}> vốn không nằm trong danh sách bỏ qua.")
            return
        current.remove(cid)
        await set_config("ignored_channel_ids", ",".join(current))
        await ctx.send(f"Đã theo dõi lại <#{cid}>.")
        return
    scope_guild, scope_channel = await tracking_scope()
    if scope_channel and scope_channel == cid:
        await ctx.send(f"<#{cid}> đang là kênh duy nhất được theo dõi (`,setchannel`). Muốn tắt hẳn thì dùng `,setchannel xoa`.")
        return
    if cid not in current:
        current.append(cid)
    await set_config("ignored_channel_ids", ",".join(current))
    note = "" if (scope_guild or scope_channel) else "\n(Chưa đặt giới hạn server/kênh nên Tom vẫn theo dõi mọi nơi khác.)"
    await ctx.send(f"🙈 Tom sẽ BỎ QUA <#{cid}>: không đọc lệnh owo của bạn và tin OwO ở đó. Lệnh `,` của Tom vẫn dùng được.{note}")


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
@is_owner()
async def status(ctx):
    tracked = await get_config("tracked_user_id")
    last_hunt = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])

    embed = discord.Embed(title="Trạng thái theo dõi", color=0xD9A227)
    embed.add_field(name="Phiên bản bot", value=f"`{bot_version_text()}`", inline=False)
    embed.add_field(name="Đang theo dõi", value=f"<@{tracked}>" if tracked else "Chưa đặt — dùng `,track`", inline=False)
    scope_guild, tracked_channel = await tracking_scope()
    if scope_guild:
        scope_text = f"Cả server `{scope_guild}` (mọi kênh)"
    elif tracked_channel:
        scope_text = f"<#{tracked_channel}>"
    else:
        scope_text = "Không giới hạn — mọi nơi bot nhìn thấy"
    embed.add_field(name="Phạm vi theo dõi", value=scope_text, inline=False)
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
@is_owner()
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
@is_owner()
async def quests_cmd(ctx):
    row = await mdb[COL_QUEST].find_one(sort=[("_id", -1)])
    if not row:
        await ctx.send("Chưa có dữ liệu quest.")
        return
    status_text = "Đã xong hết hôm nay" if row["all_done"] else "Còn quest chưa xong"
    await ctx.send(f"**Quest:** {status_text} · Seals: {row['seals']} · Kế tiếp: {row['next_quest'] or '—'}")


@bot.command(name="team")
@is_owner()
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
@is_owner()
async def myweapons_cmd(ctx, *, search: str = ""):
    q = {"type_name": {"$regex": re.escape(search), "$options": "i"}} if search else {}
    cursor = mdb[COL_WEAPON_INSTANCES].find(q).sort("updated_at", -1).limit(15)
    rows = await cursor.to_list(length=15)
    if not rows:
        await ctx.send("Chưa có vũ khí nào được ghi nhận.")
        return
    lines = [f"`{r['_id']}` **{r['type_name']}** {r['quality']}% — {r.get('passive_name') or 'chưa rõ passive'}"
             for r in rows]
    await ctx.send("\n".join(lines))


@bot.command(name="zoo")
@is_owner()
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
@is_owner()
async def inv_cmd(ctx, *, search: str = ""):
    q = {"name": {"$regex": re.escape(search), "$options": "i"}} if search else {}
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
@is_owner()
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


GEMTIER_USAGE = (
    "Dùng:\n"
    "`,gemtier` — xem tier đang ưu tiên của từng loại gem (kèm gem còn trong kho)\n"
    "`,gemtier <loại> <tier>` — vd `,gemtier hunting rare`, `,gemtier lucky epic`\n"
    "`,gemtier <loại> cao` / `thấp` — luôn lấy tier cao nhất / thấp nhất còn viên\n"
    "`,gemtier all <tier>` — đặt cho cả 4 loại · `,gemtier <loại|all> reset` — về mặc định (ưu tiên cao nhất, bật mọi tier)\n"
    "`,gemtier tat <loại|all> <tier...>` — TẮT tier (không bao giờ dùng), vd `,gemtier tat lucky common uncommon`\n"
    "`,gemtier bat <loại|all> <tier...>` — BẬT lại; `all` ở chỗ tier = mọi tier, vd `,gemtier bat hunting all`\n"
    "Loại: `hunting` (1) · `empowering` (3) · `lucky` (4) · `special` (sao). "
    "Tier: `common` `uncommon` `rare` `epic` `mythical` `legendary` `fabled` (hoặc chữ cái đầu `c u r e m l f`).")


async def _gem_stock_text(slot) -> str:
    rows = await mdb[COL_INVENTORY].find(
        {"is_gem": True, "gem_slot": slot, "count": {"$gt": 0}}).sort("gem_tier_rank", -1).to_list(length=10)
    return ", ".join(f"{r['gem_tier']} ×{r['count']}" for r in rows) if rows else "hết"


@bot.command(name="gemtier")
@is_owner()
async def gemtier_cmd(ctx, *args):
    """Chọn tier gem sẽ dùng khi thay gem hết độ bền, riêng cho từng loại (Hunting/Empowering/Lucky/Special).
    Đúng tier mong muốn hết viên thì bot lấy tier gần nhất THẤP hơn, không còn mới lấy tier cao hơn."""
    first = _fold(args[0]) if args else ""
    if not args or first in ("xem", "status", "list"):
        lines = []
        for slot in GEM_SLOTS:
            pref = await get_gem_tier_pref(slot)
            allowed = await get_gem_allowed(slot)
            lines.append(f"**{gem_type_name(slot)}** (slot {slot}): ưu tiên **{gem_pref_label(pref)}** · kho: {await _gem_stock_text(slot)}\n"
                         f"　{gem_allowed_text(allowed)}")
        await ctx.send("🎚️ Tier gem khi thay (✅ = được dùng, ⛔ = tắt):\n" + "\n".join(lines)
                       + "\n\nĐổi ưu tiên: `,gemtier <loại> <tier>` · bật/tắt tier: `,gemtier tat lucky common` / `,gemtier bat lucky common` (xem `,gemtier ?`).")
        return
    if first in ("?", "help", "huongdan"):
        await ctx.send(GEMTIER_USAGE)
        return

    if first in ("bat", "on", "allow", "tat", "off", "deny"):
        turn_on = first in ("bat", "on", "allow")
        if len(args) < 3:
            await ctx.send("Thiếu loại gem hoặc tier.\n" + GEMTIER_USAGE)
            return
        target = _fold(args[1])
        slots = list(GEM_SLOTS) if target in ("all", "tatca", "moi") else [resolve_gem_slot(args[1])]
        tiers, unknown = parse_gem_tier_words(args[2:])
        if None in slots or unknown or not tiers:
            bad = ", ".join(f"`{u}`" for u in unknown) if unknown else ""
            await ctx.send((f"Không hiểu tier {bad}.\n" if bad else "Mình chưa hiểu loại gem hoặc tier.\n") + GEMTIER_USAGE)
            return
        lines = []
        for slot in slots:
            cur = await get_gem_allowed(slot)
            cur = set(GEM_TIERS) if cur is None else set(cur)
            cur = (cur | set(tiers)) if turn_on else (cur - set(tiers))
            await set_gem_allowed(slot, cur)
            warn = "  ⚠️ đã tắt HẾT tier: bot sẽ không tự thay gem loại này" if not cur else ""
            lines.append(f"**{gem_type_name(slot)}**: {gem_allowed_text(cur)}{warn}")
        await ctx.send(f"✅ Đã {'BẬT' if turn_on else 'TẮT'} {', '.join(tiers)}:\n" + "\n".join(lines))
        return

    def is_reset(words):
        return _fold(" ".join(words)) in ("reset", "xoa", "macdinh", "default")

    if first in ("reset", "xoa", "macdinh", "default"):
        slots = [resolve_gem_slot(args[1])] if len(args) > 1 else list(GEM_SLOTS)
        rest = []
    elif first in ("all", "tatca", "moi"):
        slots, rest = list(GEM_SLOTS), list(args[1:])
    else:
        slots, rest = [resolve_gem_slot(args[0])], list(args[1:])
    if None in slots or (rest == [] and first not in ("reset", "xoa", "macdinh", "default")):
        await ctx.send("Mình chưa hiểu loại gem hoặc tier.\n" + GEMTIER_USAGE)
        return
    if first in ("reset", "xoa", "macdinh", "default") or is_reset(rest):
        for slot in slots:
            await set_config(f"gem_tier_{slot}", "")
            await set_config(f"gem_allow_{slot}", "")
        names = ", ".join(gem_type_name(s) for s in slots)
        await ctx.send(f"✅ Đã về mặc định (ưu tiên tier cao nhất, bật mọi tier) cho: {names}.")
        return
    pref = normalize_gem_tier_pref(" ".join(rest))
    if pref is None:
        await ctx.send(f"Không hiểu tier `{' '.join(rest)}`.\n" + GEMTIER_USAGE)
        return
    for slot in slots:
        await set_config(f"gem_tier_{slot}", pref)
    names = ", ".join(gem_type_name(s) for s in slots)
    note = ("" if pref in ("highest", "lowest") else
            " Hết đúng tier này thì bot lấy tier gần nhất thấp hơn, không còn mới lấy tier cao hơn.")
    await ctx.send(f"✅ Gem {names}: ưu tiên tier **{gem_pref_label(pref)}**.{note}")


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
    if await is_app_off():
        await message.channel.send("🔴 App đang TẮT (`,off`) nên mình không nhờ app gõ mã huntbot. Bật lại bằng `,off on`.")
        return True
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


async def import_weapon_export(raw: bytes, auto_session: bool = False) -> str:
    """Doc file weapons.json (NeonUtil), ghi Giu/Bo vao COL_WEAPON_REVIEW, gui file ke hoach cho Ruby. Tra ve doan tom tat.
    auto_session=True (file den tu `nw inv export` cua chinh Ruby): lap luon phien don kho cho app (app chi chay khi Ruby BAT cong tac)."""
    weapons = weapon_import.parse_export(raw)
    # Top Knowledge: gop danh sach da luu voi file moi (cay cao hon thi thay vao), roi luu lai cho lan nhap sau
    stored_top = await get_config(KNOWLEDGE_TOP_KEY, [])
    plan = weapon_import.build_plan(weapons, stored_top if isinstance(stored_top, list) else [])
    await set_config(KNOWLEDGE_TOP_KEY, plan["knowledge_top"])
    now = _utcnow().isoformat()
    seen = set(plan["keep"]) | set(plan["drop"])
    old = await mdb[COL_WEAPON_REVIEW].find({"source": "neon_export"}, {"_id": 1}).to_list(length=100000)
    stale = [r["_id"] for r in old if r["_id"] not in seen]
    if stale:
        await mdb[COL_WEAPON_REVIEW].delete_many({"_id": {"$in": stale}})
    by_id = {str(w["id"]): w for w in weapons}
    manual_ids = {r["_id"] for r in await mdb[COL_WEAPON_REVIEW].find({"manual": True}, {"_id": 1}).to_list(length=100000)}
    for decision, bucket in (("keep", plan["keep"]), ("drop", plan["drop"])):
        for wid, why in bucket.items():
            if wid in manual_ids:
                # Ruby da quyet tay: giu quyet dinh + ly do, chi lam moi chat luong / loai
                await mdb[COL_WEAPON_REVIEW].update_one(
                    {"_id": wid}, {"$set": {"source": "neon_export", "at": now, "q": by_id[wid]["q"], "t": by_id[wid]["t"]}}, upsert=True)
                continue
            await mdb[COL_WEAPON_REVIEW].update_one(
                {"_id": wid}, {"$set": {"decision": decision, "reason": why, "source": "neon_export", "at": now,
                                        "q": by_id[wid]["q"], "t": by_id[wid]["t"]}}, upsert=True)
    data = json.dumps({"tao_luc": now, "tong": plan["total"], "ly_do": plan["reasons"],
                       "giu": plan["keep"], "bo": plan["drop"]}, ensure_ascii=False, indent=1).encode("utf-8")
    await send_file_to_owner("📦 Kế hoạch Giữ / Bỏ từ file export (chưa xóa gì).", "weapon_import_plan.json", data)
    text = weapon_import.summary_text(plan)
    if auto_session:
        docs = await mdb[COL_WEAPON_REVIEW].find({"source": "neon_export"}).to_list(length=100000)
        st = weapon_import.cleanup_stages(docs, await extra_drop_ids())
        steps = weapon_import.cleanup_steps(st)
        # Phien moi thay phien cu: buoc cu con dang cho (tu export truoc) phai huy, khong de app lam theo ke hoach cu
        await mdb[COL_AUTOMACRO_COMMANDS].update_many(
            {"status": "pending", "action": {"$regex": "^clean_"}},
            {"$set": {"status": "cancelled", "completed_at": now}})
        if steps:
            await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value": {
                "active": True, "steps": steps, "cursor": 0, "total": len(steps), "at": now, "empty_reason": ""}}}, upsert=True)
            text += (f"\n🧹 Có {len(steps)} bước dọn kho. Bật **Dọn kho tự động** trong menu Hub (tab Misc) thì app tự làm; "
                     "chỉ bấm Dismantle khi số cây khớp, lệch là Cancel và dừng. Không bật thì không có gì xảy ra.")
        else:
            # Thay HAN phien cu (truoc day chi tat active nen total/cursor/at cu con sot lai lam app hien sai); luu ly do cho app
            reason = weapon_import.cleanup_empty_reason(st)
            await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value": {
                "active": False, "steps": [], "cursor": 0, "total": 0, "at": now, "empty_reason": reason}}}, upsert=True)
            text += f"\nKhông có bước dọn tự động: {reason}. Xem `,cleanplan`."
    else:
        text += "\nGõ `,cleanplan` để xem các bước dọn kho."
    return text


# ===================== Don kho tu dong (app lam, Ruby bat cong tac o Hub) =====================
CLEAN_KEY = "clean_session"
KNOWLEDGE_TOP_KEY = "weapon_knowledge_top"   # top 6 cay Knowledge cao nhat [{id, v}], luu giua cac lan ,weaponimport
EXTRA_DROP_KEY = "clean_extra_drop"   # ID Ruby them tay vao danh sach ra (,dropadd); ben qua cac lan ,weaponimport
CLEAN_BATCH = 8
CLEAN_MAX_ROUNDS = 2
_NEON_EXPORT_RE = re.compile(r"^nw\s+inv\w*\s+export\b", re.I)


async def extra_drop_ids() -> list:
    v = await get_config(EXTRA_DROP_KEY, [])
    return [str(i).upper() for i in v] if isinstance(v, list) else []


async def clean_session() -> dict:
    doc = await mdb[COL_CONFIG].find_one({"_id": CLEAN_KEY})
    return (doc or {}).get("value") or {}


async def clean_pending_count() -> int:
    return await mdb[COL_AUTOMACRO_COMMANDS].count_documents(
        {"status": "pending", "action": {"$regex": "^clean_"}})


async def clean_queue_batch():
    """Xep toi da CLEAN_BATCH buoc ke tiep neu khong con buoc don kho nao dang cho. Het buoc -> ket thuc phien."""
    s = await clean_session()
    if not s.get("active") or await clean_pending_count():
        return
    cur = int(s.get("cursor") or 0)
    steps = (s.get("steps") or [])[cur:cur + CLEAN_BATCH]
    if not steps:
        await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value.active": False}})
        if s.get("awaiting_export"):
            return   # buoc cuoi la `nw inv export`: file moi ve se mo phien moi (neu con cay can don)
        await notify_owner(f"✅ App đã dọn xong {s.get('total', 0)} bước. Gõ `nw inv export` lần nữa để kiểm tra kho còn lại.", min_gap=30)
        return
    total = int(s.get("total") or len(s.get("steps") or []))
    for i, st in enumerate(steps):
        # step_no / step_total: app hien "Buoc n/tong" cho Ruby biet dang o dau (gia tri la chuoi nhu cac params khac)
        params = dict(st["params"], step_no=str(cur + i + 1), step_total=str(total))
        await queue_automacro_command(st["action"], params)


def clean_status_snapshot(s: dict) -> dict:
    """Tom tat phien don kho cho app (GET /clean): app dung de biet bot da lap ke hoach moi chua, con bao nhieu buoc, vi sao khong co buoc."""
    at_epoch = 0
    try:
        if s.get("at"):
            at_epoch = int(datetime.fromisoformat(str(s["at"])).timestamp())
    except (ValueError, TypeError):
        at_epoch = 0
    return {"active": bool(s.get("active")), "cursor": int(s.get("cursor") or 0), "total": int(s.get("total") or 0),
            "at_epoch": at_epoch, "empty_reason": str(s.get("empty_reason") or "")}


async def handle_get_clean(request: web.Request):
    """GET /clean: tinh trang phien don kho (xem clean_status_snapshot) + so buoc dang cho app lam (`pending`)."""
    if not _check_api_token(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    snap = clean_status_snapshot(await clean_session())
    snap["pending"] = await clean_pending_count()
    return web.json_response(snap)


async def after_clean_ack(status: str, cmd: dict):
    s = await clean_session()
    if not s.get("active"):
        return
    if status != "done":
        await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value.active": False}})
        await mdb[COL_AUTOMACRO_COMMANDS].update_many(
            {"status": "pending", "action": {"$regex": "^clean_"}},
            {"$set": {"status": "cancelled", "completed_at": _utcnow().isoformat()}})
        step = (cmd.get("params") or {}).get("command_text", "?")
        await notify_owner(f"⛔ Dọn kho DỪNG ở bước `{step}` ({s.get('cursor', 0)}/{s.get('total', 0)} xong): số cây/ID trên màn hình "
                           "không khớp hoặc không bấm được. App đã bấm Cancel, chưa rã gì thêm. Xuất lại `nw inv export` để lập lại kế hoạch.", min_gap=10)
        return
    if (cmd.get("action") or "") == "clean_export":
        await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value.awaiting_export": True}})
        s["awaiting_export"] = True
    await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$inc": {"value.cursor": 1}})
    await clean_queue_batch()


NEON_EXPORT_LOOKBACK_SECONDS = 180   # file Neon khong reply: chi tinh lenh export cua OWNER trong 3 phut truoc do


async def find_recent_export_command(message):
    """Tin `nw inv export` MOI NHAT cua OWNER trong cung kenh, truoc `message` (file cua Neon) toi da 3 phut; khong co -> None.
    Duyet toi da 25 tin truoc file, bo qua tin cua nguoi khac / tin khong phai lenh export; lay lenh export CUA OWNER gan nhat
    (qua 3 phut thi coi nhu khong co, de khong gan nham file cu)."""
    try:
        async for m in message.channel.history(limit=25, before=message):
            if str(m.author.id) != str(OWNER_ID) or not _NEON_EXPORT_RE.match((m.content or "").strip()):
                continue
            age = (message.created_at - m.created_at).total_seconds()
            return m if 0 <= age <= NEON_EXPORT_LOOKBACK_SECONDS else None
    except Exception as e:
        print(f"[tracker][neon] Khong doc duoc lich su kenh de tim lenh export: {e!r}")
    return None


async def handle_neon_export_reply(message: discord.Message):
    """Neon gui weapons.json sau lenh `nw inv export` CUA CHINH RUBY -> tu nhap. Tin goc xac dinh theo reply cua Neon; neu Neon
    khong reply thi lay lenh export moi nhat cua OWNER trong kenh (toi da 3 phut truoc). Chi nhan khi tin goc la cua OWNER
    va dung lenh export; tin Neon khac bi bo qua."""
    atts = [a for a in (message.attachments or []) if (a.filename or "").lower().endswith(".json")]
    if not atts:
        return   # tin Neon thuong (khong co file .json): bo qua im lang

    async def skip(why: str):
        # Neon da gui file .json ma Tom khong nhan: noi ro ly do (log + bao Ruby), dung im lang
        print(f"[tracker][neon] Bo qua file Neon: {why}")
        await notify_owner(f"⚠️ Neon vừa gửi file .json nhưng Tom không nhận: {why}", min_gap=60)

    if not OWNER_ID:
        return await skip("bot chưa có biến môi trường OWNER_ID.")
    if str(await get_config("neon_autoimport", "on")) == "off":
        return await skip("đang TẮT tự nhận file — gõ `,neonauto on` để bật.")
    ref = message.reference
    if ref is not None and ref.message_id:
        orig = ref.resolved if isinstance(getattr(ref, "resolved", None), discord.Message) else None
        if orig is None:
            try:
                orig = await message.channel.fetch_message(ref.message_id)
            except Exception as e:
                return await skip(f"không đọc được tin lệnh gốc ({type(e).__name__}) — bot có quyền Read Message History trong kênh không?")
    else:
        # Neon gui file KHONG kem reply (thuc te hay gap): tim tin `nw inv export` moi nhat cua OWNER ngay truoc do trong kenh
        orig = await find_recent_export_command(message)
        if orig is None:
            return await skip(f"Neon không reply, và Tom không thấy tin `nw inv export` của bạn trong {NEON_EXPORT_LOOKBACK_SECONDS // 60} phút trước đó ở kênh này.")
    if str(orig.author.id) != str(OWNER_ID):
        return await skip(f"tin lệnh gốc do tài khoản {orig.author.id} gõ, khác OWNER_ID ({OWNER_ID}).")
    cmd_text = (orig.content or "").strip()
    if not _NEON_EXPORT_RE.match(cmd_text):
        return await skip(f"tin lệnh gốc là `{cmd_text[:40]}`, không phải `nw inv export`.")
    if atts[0].size and atts[0].size > 20 * 1024 * 1024:
        return await skip("file quá lớn (trên 20 MB).")
    try:
        text = await import_weapon_export(await atts[0].read(), auto_session=True)
    except ValueError as e:
        await notify_owner(f"Không đọc được file export của Neon: {e}", min_gap=30)
        return
    await notify_owner("📥 Tom đã tự nhận file `nw inv export` của bạn.\n" + text, min_gap=5)


@bot.command(name="weaponimport")
@is_owner()
async def weaponimport_cmd(ctx):
    """Nhap file `weapons.json` tu `,w inv export` cua NeonUtil (Ruby tu go lenh do 1 lan, roi DINH KEM file vao tin nay)
    -> lap danh sach Giu/Bo theo luat o weapon_import.py va ghi vao cung noi voi `,weaponreview`. KHONG xoa/ban gi."""
    atts = [a for a in (ctx.message.attachments or []) if (a.filename or "").lower().endswith(".json")]
    if not atts:
        await ctx.send("Đính kèm file `weapons.json` (từ lệnh `,w inv export` của NeonUtil) vào cùng tin nhắn `,weaponimport`.")
        return
    att = atts[0]
    if att.size and att.size > 20 * 1024 * 1024:
        await ctx.send("File quá lớn (> 20 MB).")
        return
    try:
        text = await import_weapon_export(await att.read())
    except ValueError as e:
        await ctx.send(f"Không đọc được file: {e}")
        return
    await ctx.send(text)


@bot.command(name="neonauto")
@is_owner()
async def neonauto_cmd(ctx, mode: str = ""):
    """`,neonauto on|off`: bat/tat viec Tom tu nhan file khi Neon tra loi lenh `nw inv export` cua chinh ban."""
    m = (mode or "").lower()
    if m not in ("on", "off"):
        cur = str(await get_config("neon_autoimport", "on"))
        await ctx.send(f"Tự nhận file `nw inv export`: **{cur}**. Dùng `,neonauto on` hoặc `,neonauto off`.")
        return
    await set_config("neon_autoimport", m)
    await ctx.send(f"Đã {'BẬT' if m == 'on' else 'TẮT'} tự nhận file `nw inv export`.")


async def dropadd_apply(ids: str = "") -> str:
    """Them ID vu khi vao danh sach RA (ra theo ID trong ,cleanplan / Don kho tu dong), ben qua cac lan ,weaponimport.
    `,dropadd C06P72 F40IBT` them; `,dropadd -x C06P72` go khoi danh sach; `,dropadd` khong tham so = xem danh sach."""
    cur = await extra_drop_ids()
    raw = (ids or "").strip()
    remove = False
    if raw[:2].lower() in ("-x", "-d") and (len(raw) == 2 or raw[2] in " \t\n"):
        remove, raw = True, raw[2:]
    new, bad = weapon_import.parse_weapon_ids(raw)
    if not new and not bad:
        return ("**Danh sách rã thêm tay** (" + str(len(cur)) + "): " + (" ".join(f"`{i}`" for i in cur) or "trống")
                + "\nThêm: `,dropadd <ID> <ID>…` · Gỡ: `,dropadd -x <ID>`")
    msg = []
    if remove:
        gone = [i for i in new if i in cur]
        cur = [i for i in cur if i not in new]
        await set_config(EXTRA_DROP_KEY, cur)
        msg.append(f"Đã gỡ {len(gone)} ID khỏi danh sách rã thêm." if gone else "Không có ID nào trong danh sách để gỡ.")
    else:
        docs = await mdb[COL_WEAPON_REVIEW].find({"source": "neon_export"}).to_list(length=100000)
        by_id = {str(d["_id"]).upper(): d for d in docs}
        added, locked, unknown = [], [], []
        for i in new:
            d = by_id.get(i)
            if d is not None and weapon_import.is_locked_reason(d.get("reason")):
                locked.append(i)
            else:
                if i not in cur:
                    cur.append(i)
                added.append(i)
                if d is None:
                    unknown.append(i)
        await set_config(EXTRA_DROP_KEY, cur)
        if added:
            msg.append("Đã thêm vào danh sách rã: " + " ".join(f"`{i}`" for i in added))
        if locked:
            msg.append("Bỏ qua cây đang KHÓA (không rã được): " + " ".join(f"`{i}`" for i in locked))
        if unknown:
            msg.append("Chưa thấy trong file export gần nhất (vẫn nhớ, sẽ áp dụng khi cây xuất hiện): " + " ".join(f"`{i}`" for i in unknown))
    if bad:
        msg.append("ID không hợp lệ: " + " ".join(f"`{b}`" for b in bad))
    msg.append("Gõ `nw inv export` (hoặc bật Dọn kho tự động) để Tom lập lại kế hoạch có các cây này. Xem lại bằng `,cleanplan`.")
    return "\n".join(msg)


@bot.command(name="dropadd")
@is_owner()
async def dropadd_cmd(ctx, *, ids: str = ""):
    """Them ID vu khi vao danh sach RA (xem dropadd_apply)."""
    await ctx.send(await dropadd_apply(ids))


@bot.command(name="cleanstop")
@is_owner()
async def cleanstop_cmd(ctx):
    """Dung phien don kho tu dong va huy cac buoc dang cho."""
    await mdb[COL_CONFIG].update_one({"_id": CLEAN_KEY}, {"$set": {"value.active": False}}, upsert=True)
    res = await mdb[COL_AUTOMACRO_COMMANDS].update_many(
        {"status": "pending", "action": {"$regex": "^clean_"}},
        {"$set": {"status": "cancelled", "completed_at": _utcnow().isoformat()}})
    await ctx.send(f"Đã dừng dọn kho, hủy {getattr(res, 'modified_count', 0)} bước đang chờ.")


@bot.command(name="knowledgetop", aliases=["kno", "knowledge"])
@is_owner()
async def knowledgetop_cmd(ctx):
    """Embed top 6 cay vu khi co passive Knowledge cao nhat (bot tu luu, cap nhat moi lan ,weaponimport / tu duyet Neon)."""
    top = await get_config(KNOWLEDGE_TOP_KEY, [])
    if not isinstance(top, list) or not top:
        await ctx.send("Chưa có cây Knowledge nào được lưu. Gõ `nw inv export` (rồi `,weaponimport`) hoặc chạy Tự duyệt để bot ghi nhận.")
        return
    rules = load_weapon_rules()
    types = (rules or {}).get("types") or {}
    emb = discord.Embed(title=f"🧠 Top {weapon_import.KNOWLEDGE_TOP_N} Knowledge cao nhất", color=0x7B61FF)
    for n, e in enumerate(top[:weapon_import.KNOWLEDGE_TOP_N], 1):
        wid = str(e.get("id"))
        doc = await mdb[COL_WEAPON_REVIEW].find_one({"_id": wid}) or {}
        t = doc.get("t")
        tname = (types.get(str(100 + t)) or {}).get("name") if isinstance(t, int) else None
        bits = [f"Knowledge **{e.get('v'):g}%**"]
        if tname:
            bits.append(str(tname))
        if doc.get("q") is not None:
            bits.append(f"chất lượng {doc['q']:g}%")
        emb.add_field(name=f"{n}. `{wid}`", value=" · ".join(bits), inline=False)
    emb.set_footer(text="Cây cao hơn xuất hiện sẽ thay cây thấp nhất · gõ `owo w <ID>` để xem")
    await ctx.send(embed=emb)


@bot.command(name="cleanplan")
@is_owner()
async def cleanplan_cmd(ctx):
    """Cac buoc don kho (cach lai) tu danh sach `,weaponimport`: sao cay GIU o bac thap -> ra theo bac -> ra theo ID."""
    docs = await mdb[COL_WEAPON_REVIEW].find({"source": "neon_export"}).to_list(length=100000)
    if not docs:
        await ctx.send("Chưa có danh sách. Gõ `,weaponimport` kèm file `weapons.json` trước.")
        return
    await ctx.send(weapon_import.cleanup_text(weapon_import.cleanup_stages(docs, await extra_drop_ids())))


@bot.command(name="starlist")
@is_owner()
async def starlist_cmd(ctx, page: int = 1, *, template: str = ""):
    """Cay GIU chua khoa o chat luong thap (Buoc 1 cua `,cleanplan`) de Ruby TU DANH SAO tay: `owo w <ID>` roi cham nut sao.
    `,starlist 1 owo w` = them tien to lenh truoc moi ID. Bot KHONG tu go/bam."""
    docs = await mdb[COL_WEAPON_REVIEW].find({"source": "neon_export"}).to_list(length=100000)
    st = weapon_import.cleanup_stages(docs, await extra_drop_ids())
    if st["missing_q"]:
        await ctx.send(weapon_import.cleanup_text(st))
        return
    if not st["star_ids"]:
        await ctx.send("Không có cây Giữ nào cần đánh sao ở bước này (hoặc chưa `,weaponimport`).")
        return
    lines, total, pages = weapon_import.star_lines(st["star_ids"], template, page)
    shown = max(1, min(int(page or 1), pages))
    await ctx.send(f"**{total} cây GIỮ cần đánh sao** — trang {shown}/{pages} (`,starlist <trang> [lệnh trước ID]`)\n```\n" + "\n".join(lines) + "\n```"
                   "Gõ từng dòng rồi chạm nút ⭐ trên tin của OwO. Đánh sao xong hết mới sang Bước 2 trong `,cleanplan`.")


@bot.command(name="dismantlelist")
@is_owner()
async def dismantlelist_cmd(ctx, per_cmd: int = 1, page: int = 1):
    """Tao san cac dong `owo dismantle <ID>` cho cay trong danh sach BO (tu `,weaponimport`) de Ruby TU DAN tay tung dong
    roi tu bam nut Dismantle cua OwO. Bot KHONG tu go lenh, KHONG tu bam. per_cmd = so ID moi lenh (mac dinh 1, toi da 10)."""
    docs = await mdb[COL_WEAPON_REVIEW].find({"source": "neon_export"}).to_list(length=100000)
    st = weapon_import.cleanup_stages(docs, await extra_drop_ids())
    if st["missing_q"]:
        await ctx.send(weapon_import.cleanup_text(st))
        return
    rows = [{"_id": i} for i in st["id_drop"]]
    if not rows:
        await ctx.send("Không có cây nào cần rã theo ID (hoặc chưa `,weaponimport`). Xem `,cleanplan`.")
        return
    lines, total, pages = weapon_import.dismantle_commands([r["_id"] for r in rows], per_cmd, page)
    shown = max(1, min(int(page or 1), pages))
    body = "\n".join(lines)
    await ctx.send(f"**{len(rows)} cây Bỏ ở chất lượng ≥ {weapon_import.SPLIT_Q:g}** (Bước 3 của `,cleanplan`) → {total} lệnh, trang {shown}/{pages} (`,dismantlelist {max(1, min(int(per_cmd or 1), 10))} <số trang>`)\n"
                   f"```\n{body}\n```"
                   "Dán **từng dòng** vào kênh, đọc kỹ tin xác nhận của OwO (số cây, ID) rồi **tự bấm Dismantle**. "
                   "Xong cả danh sách thì xuất lại `nw inv export` và `,weaponimport` để cập nhật.")


@bot.command(name="weaponscan")
@is_owner()
async def weaponscan_cmd(ctx):
    """Nho app lat het cac trang `owo weapon`, roi tu go `owo w <ID>` cho vai cay dai dien (moi loai + moi passive)
    de hoc ten day du + co che; xong gui file weapon_knowledge.json. Hay DUNG farm truoc khi chay."""
    await mdb[COL_WEAPON_LIST].delete_many({})
    await queue_automacro_command("weapon_scan", {"command_text": "owo weapon", "click_label": "forward",
                                                  "click_times": "70", "click_min_ms": "1800", "click_max_ms": "2800"})
    await ctx.send("📦 Đã nhờ app quét kho vũ khí (lật hết các trang). Nhớ **dừng farm** trong lúc này. Xong mình sẽ tự đọc "
                   "chi tiết vài cây đại diện rồi gửi file `weapon_knowledge.json`.")


@bot.command(name="weaponprobe")
@is_owner()
async def weaponprobe_cmd(ctx):
    """Xep hang lenh `owo w <ID>` tu danh sach vu khi da quet (khong lat trang lai)."""
    ids, left = await queue_weapon_probe()
    await ctx.send(f"Đã xếp {len(ids)} lệnh `owo w <ID>` cho app." + (f" Chưa phủ: {', '.join(left[:8])}" if left else ""))


@bot.command(name="weaponlist")
@is_owner()
async def weaponlist_cmd(ctx):
    """Gui file weapon_list.json: moi cay vu khi da quet (ID, do hiem, loai, passive, chat luong)."""
    rows = await mdb[COL_WEAPON_LIST].find({}).to_list(length=5000)
    if not rows:
        await ctx.send("Chưa có danh sách vũ khí. Chạy `,weaponscan` trước.")
        return
    items = [{"id": r["_id"], "rarity": r.get("rarity"), "type": r.get("type"), "name": r.get("name"),
              "quality": r.get("quality"), "passives": r.get("passives", []),
              "passive_emojis": r.get("passive_emojis", []),
              "starred": bool(r.get("starred")), "equipped": bool(r.get("equipped")),
              "equipped_by": r.get("equipped_by")} for r in rows]
    items.sort(key=lambda x: (x["type"] or "", -(x["quality"] or 0)))
    data = json.dumps({"tao_luc": _utcnow().isoformat(), "so_cay": len(items), "cay": items},
                      ensure_ascii=False, indent=1).encode("utf-8")
    await send_file_to_owner(f"📦 Danh sách {len(items)} cây vũ khí đã quét.", "weapon_list.json", data)
    await ctx.send("Đã gửi file `weapon_list.json`.")


@bot.command(name="weaponreview")
@is_owner()
async def weaponreview_cmd(ctx, action: str = "start", limit: int = 0):
    """Duyet vu khi bang nut Giu/Bo tren Hub noi. `,weaponreview` bat dau | `stop` | `undo` | `export` | `reset`.
    Chay lenh nay Ở ĐÚNG KÊNH đang farm (bot xoa tin kiem tra trong kenh nay). CHI GHI DANH SACH, khong tu dismantle."""
    action = (action or "start").lower()
    sess = await review_get()
    if action == "stop":
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.active": False}}, upsert=True)
        await review_refresh_embed(await review_get())
        await ctx.send("Đã dừng duyệt vũ khí (danh sách Giữ/Bỏ vẫn được lưu).")
        return
    if action == "undo":
        hist = list(sess.get("history") or [])
        if not hist:
            await ctx.send("Chưa có quyết định nào để hoàn tác.")
            return
        last = hist.pop()
        await mdb[COL_WEAPON_REVIEW].delete_one({"_id": last})
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.history": hist, "value.current": last,
                                                                       "value.check_msg_ids": [], "value.active": True,
                                                                       "value.phase": "review"}}, upsert=True)
        await review_refresh_embed(await review_get())
        await ctx.send(f"Đã hoàn tác cây `{last}` — kiểm tra lại cây này.")
        await queue_automacro_command("weapon_review", {"command_text": f"owo w {last}"})
        return
    if action == "export":
        decided = await review_decisions()
        data = json.dumps({"tao_luc": _utcnow().isoformat(),
                           "giu": sorted(i for i, d in decided.items() if d == "keep"),
                           "bo": sorted(i for i, d in decided.items() if d == "drop"),
                           "giu_mac_dinh_co_sao_hoac_dang_dung": await review_default_keep_ids()},
                          ensure_ascii=False, indent=1).encode("utf-8")
        await send_file_to_owner("📦 Danh sách vũ khí Giữ / Bỏ.", "weapon_review.json", data)
        await ctx.send("Đã gửi file `weapon_review.json`.")
        return
    if action == "reset":
        await mdb[COL_WEAPON_REVIEW].delete_many({})
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.history": []}}, upsert=True)
        await ctx.send("Đã xoá toàn bộ quyết định Giữ/Bỏ.")
        return
    if action == "auto":
        await ctx.send("⛔ Tự duyệt bằng NeonUtil đã **tắt**: chủ NeonUtil không cho tự động hóa lệnh/nút của bot họ. "
                       "Sẽ thay bằng việc nhập file `weapons.json` từ `,w inv export` (bạn tự gõ lệnh đó 1 lần).")
        return
    if action != "start":
        await ctx.send("Dùng: `,weaponreview` (duyệt tay) | `stop` | `undo` | `export` | `reset`")
        return
    tid = await get_config("tracked_user_id")
    if not tid:
        await ctx.send("Chưa biết tài khoản OwO cần theo dõi — dùng `,track @user` trước.")
        return
    # Bắt đầu = QUÉT LẠI toàn bộ kho (app gõ `owo w` rồi lật trang), chỉ nhận trang có tiêu đề <@bạn>'s Weapons.
    # Quyết định Giữ/Bỏ cũ được giữ, riêng ID không còn trong kho sẽ bị gỡ sau khi quét (xem _after_review_scan).
    await mdb[COL_WEAPON_LIST].delete_many({})
    await mdb[COL_CONFIG].update_one(
        {"_id": REVIEW_KEY},
        {"$set": {"value": {"active": True, "phase": "scanning", "channel_id": ctx.channel.id, "msg_id": None,
                            "current": None, "check_msg_ids": [], "history": sess.get("history") or [],
                            "delete_warned": False, "missing": [], "started_at": _utcnow().isoformat(),
                            "auto": action == "auto", "auto_limit": max(0, int(limit or 0))}}}, upsert=True)
    msg = await ctx.send(embed=await review_embed(await review_get()))
    await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.msg_id": msg.id}})
    qid = await queue_automacro_command("weapon_review_scan", {"command_text": "owo w", "click_label": "forward",
                                                               "click_times": "100", "click_min_ms": "1800", "click_max_ms": "2800"})
    if qid is None:
        await mdb[COL_CONFIG].update_one({"_id": REVIEW_KEY}, {"$set": {"value.active": False}})
        await review_refresh_embed(await review_get())
        await ctx.send("⚠️ App đang TẮT (`,off`) nên chưa giao việc — bật Hub nổi, **dừng farm**, rồi gõ lại `,weaponreview`.")
    else:
        await ctx.send("📦 Đã nhờ app quét lại kho (gõ `owo w` rồi lật trang, ~3–4 phút). Nhớ **dừng farm** trong lúc này.")


@bot.command(name="dismantleplan")
@is_owner()
async def dismantleplan_cmd(ctx):
    """Lap KE HOACH don vu khi tu danh sach da quet: GIU / RAC / XAM. CHI LAP KE HOACH - khong xoa gi, khong nho app go lenh."""
    try:
        import weapon_cleanup
    except Exception as e:
        await ctx.send(f"Thiếu file `weapon_cleanup.py` cạnh bot ({e!r}). Chép file đó vào repo rồi push lại.")
        return
    rows = await mdb[COL_WEAPON_LIST].find({}).to_list(length=5000)
    if not rows:
        await ctx.send("Chưa có danh sách vũ khí. Chạy `,weaponscan` trước (nhớ dừng farm).")
        return
    rules = load_weapon_rules(force=True)
    if not rules.get("types"):
        await ctx.send("Không đọc được `weapon_rules.json` cạnh bot — chưa thể lập kế hoạch.")
        return
    weapons = [{**r, "id": r["_id"]} for r in rows]
    plan = weapon_cleanup.plan_cleanup(weapons, rules)
    text = weapon_cleanup.summary_text(plan)
    seen = [r.get("seen_at") for r in rows if r.get("seen_at")]
    if seen:
        try:
            age_h = (_utcnow() - datetime.fromisoformat(max(seen))).total_seconds() / 3600
            if age_h > 6:
                text += f"\n⚠️ Danh sách quét cách đây {age_h:.0f} giờ — nên `,weaponscan` lại trước khi dọn thật."
        except (ValueError, TypeError):
            pass
    await ctx.send(text)
    data = json.dumps(plan, ensure_ascii=False, indent=1).encode("utf-8")
    await send_file_to_owner("🧹 Kế hoạch dọn vũ khí (chưa xóa gì): đủ 3 danh sách giữ / rác / xám.", "dismantle_plan.json", data)


@bot.command(name="unlocked")
@is_owner()
async def unlocked_cmd(ctx, tier: str = ""):
    """Liet ke pet da mo khoa (khong hien so luong)."""
    rows = await _zoo_unlocked_rows()
    if not rows:
        await ctx.send("Chưa có dữ liệu zoo. Gõ `owo zoo` trong kênh farm một lần.")
        return
    by_tier = {}
    for r in rows:
        by_tier.setdefault(r.get("tier"), []).append(_zoo_emoji(r))
    only = tier.lower().strip() or None
    if only and only not in by_tier:
        await ctx.send("Không có tier đó. Các tier: " + ", ".join(str(t) for t in by_tier))
        return
    lines, total = [], 0
    for t, ems in by_tier.items():
        if only and t != only:
            continue
        lines.append(f"**{t}** ({len(ems)})")
        lines.extend(_zoo_pack(ems))
        total += len(ems)
    for chunk in _zoo_chunks(f"Đã mở khóa **{total}** con\n" + "\n".join(lines)):
        await ctx.send(chunk)


async def zoodiff_report(kind_arg=""):
    """So 2 lần ghi zoo gần nhất cùng loại. Dùng chung cho lệnh `,zoodiff` và GET /zoodiff.
    Trả (trạng thái, chữ, loại): "bad_kind" = tham số sai · "no_data" = chưa đủ 2 lần ghi · "ok" = có kết quả so.
    `loại` là "current" / "all" (None nếu tham số sai hoặc chưa có lịch sử nào)."""
    ok, k = tools_api.parse_zoodiff_kind(kind_arg)
    if not ok:
        return "bad_kind", "Dùng `,zoodiff`, `,zoodiff d` (số đã bắt) hoặc `,zoodiff now` (đang giữ).", None
    if not k:
        newest = await mdb[COL_ZOO_HISTORY].find({}).sort("at", -1).to_list(length=1)
        if not newest:
            return "no_data", "Chưa có lịch sử zoo. Gõ `owo zoo` hoặc `owo zoo d` trong kênh farm.", None
        k = newest[0]["kind"]
    rows = await mdb[COL_ZOO_HISTORY].find({"kind": k}).sort("at", -1).to_list(length=2)
    if len(rows) < 2:
        return "no_data", (f"Mới có {len(rows)} lần ghi {ZOO_KIND_LABEL[k]}, chưa có gì để so. "
                           "Gõ lại lệnh zoo trong kênh farm khi zoo đã thay đổi."), k
    return "ok", _zoo_diff_text(rows[1], rows[0], k), k


@bot.command(name="zoodiff")
@is_owner()
async def zoodiff_cmd(ctx, kind: str = ""):
    """So 2 lan ghi zoo gan nhat cung loai: `,zoodiff d` (so da bat) hoac `,zoodiff now` (dang giu)."""
    _state, text, _kind = await zoodiff_report(kind)
    for chunk in _zoo_chunks(text):
        await ctx.send(chunk)


APP_DRIVING_COMMANDS = {"hbstart", "hbcode", "weaponscan", "weaponprobe", "zoodex"}  # các lệnh nhờ app gõ lệnh vào OwO


@bot.check
async def _app_off_guard(ctx):
    """Đang `,off` thì các lệnh nhờ app làm việc bị chặn ngay từ đầu (nên `,weaponscan` cũng không xóa danh sách vũ khí)."""
    if ctx.command and ctx.command.name in APP_DRIVING_COMMANDS and await is_app_off():
        await ctx.send("🔴 App đang TẮT (lệnh `,off`). Gõ `,off on` để bật lại rồi thử lại.")
        raise commands.CheckFailure("app_off")
    return True


_default_on_command_error = bot.on_command_error


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure) and str(error) == "app_off":
        return  # đã báo cho Ruby rồi, không cần in lỗi ra log
    await _default_on_command_error(ctx, error)


@bot.command(name="off")
@is_owner()
async def off_cmd(ctx, state: str = ""):
    """CONG TAT TONG: `,off` = tat moi hoat dong cua app; `,off on` = bat lai; `,off status` = xem trang thai."""
    st = state.strip().lower()
    pending = await mdb[COL_AUTOMACRO_COMMANDS].count_documents({"status": "pending"})
    if st in ("on", "bat", "bật", "resume"):
        await set_app_off(False)
        await ctx.send("🟢 Đã BẬT lại: bot giao việc cho app như bình thường. App đã dừng thì phải bấm **Bắt đầu** lại mới farm tiếp.")
        return
    if st in ("status", "xem", "tt"):
        off = await is_app_off()
        await ctx.send(("🔴 App đang **TẮT**" if off else "🟢 App đang **BẬT**") + f" · lệnh đang chờ app: {pending}.")
        return
    if st:
        await ctx.send("Dùng: `,off` (tắt) · `,off on` (bật lại) · `,off status` (xem trạng thái)")
        return
    await set_app_off(True)
    await mdb[COL_AUTOMACRO_COMMANDS].update_many(
        {"status": "pending"}, {"$set": {"status": "cancelled", "completed_at": _utcnow().isoformat()}})
    hb_pending["at"] = 0.0  # hủy cửa sổ chờ mã huntbot (nếu đang mở)
    await ctx.send(
        "🔴 **ĐÃ TẮT app.**\n"
        f"• Đã hủy {pending} lệnh đang chờ.\n"
        "• Bot không giao việc nào cho app nữa (huntbot tự động, thay gem, quét vũ khí...).\n"
        "• App bản đã cập nhật sẽ tự dừng farm trong vài giây. App bản cũ thì bấm **Dừng** bằng tay.\n"
        "• Kịch bản (script) boss man tự chạy trong app thì bot không dừng được.\n"
        "• Bật lại: `,off on`.")


@bot.command(name="weaponknowledge")
@is_owner()
async def weaponknowledge_cmd(ctx):
    """Gui lai file kien thuc vu khi/passive da hoc."""
    await send_weapon_knowledge()
    await ctx.send("Đã gửi file `weapon_knowledge.json`.")


@bot.command(name="teamcheck")
@is_owner()
async def teamcheck_cmd(ctx):
    """Cham doi hinh dang dung theo 2 yeu to: chi so/co che vu khi va passive (dua tren loi khuyen server OwO)."""
    text, _ = await build_team_check()
    for i in range(0, len(text), 1900):
        await ctx.send(text[i:i + 1900])


@bot.command(name="hbauto")
@is_owner()
async def hbauto_cmd(ctx, state: str = ""):
    """,hbauto on|off = bat/tat viec TU nho app chay lai huntbot (xin mat khau) khi huntbot vua ve. Khong tham so = xem."""
    st = state.strip().lower()
    if st in ("on", "bat", "bật"):
        await set_config("hb_auto", "on")
    elif st in ("off", "tat", "tắt"):
        await set_config("hb_auto", "off")
    elif st:
        await ctx.send("Dùng: `,hbauto on` | `,hbauto off`")
        return
    on = (await get_config("hb_auto", "on")) == "on"
    await ctx.send("🤖 Tự chạy lại huntbot khi huntbot về: **BẬT** (app gõ `owo hb`, bạn chỉ nhắn lại mã)." if on
                   else "🤖 Tự chạy lại huntbot: **TẮT**.")


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


@bot.command(name="weaponadvice")
@is_owner()
async def weaponadvice_cmd(ctx):
    """Gui lai file loi khuyen vu khi da luu (neu lan truoc khong nhan duoc)."""
    rows = await mdb[COL_WEAPON_ADVICE].find({}).to_list(length=200)
    if not rows:
        await ctx.send("Chưa có lời khuyên vũ khí nào. Bấm 📚 trong Hub nổi của app để app tự học.")
        return
    await send_weapon_advice_file(rows)
    await ctx.send(f"Đã gửi lại file ({len(rows)} loại).")


@bot.command(name="eventmode")
@is_owner()
async def eventmode_cmd(ctx, state: str = ""):
    """Bat/tat che do Event (cung nut trong app). BAT = dang co su kien, duoc dung slot thu 4 (gem Special).
    Dung: ,eventmode on | ,eventmode off | ,eventmode (xem trang thai)"""
    st = state.strip().lower()
    if st in ("on", "bat", "bật", "1"):
        await set_event_mode(True)
    elif st in ("off", "tat", "tắt", "0"):
        await set_event_mode(False)
    elif st:
        await ctx.send("Dùng: `,eventmode on` | `,eventmode off` | `,eventmode` (xem trạng thái)")
        return
    on = await get_event_mode()
    await ctx.send("🎉 Chế độ Event: **BẬT** — được dùng slot thứ 4 (gem Special)." if on
                   else "🎉 Chế độ Event: **TẮT** — bot không tự dùng gem Special.")


@bot.command(name="captcha")
async def captcha_cmd(ctx, action: str = ""):
    """,captcha = xem trang thai canh bao captcha. ,captcha clear = tu bao da giai xong (huy canh bao)."""
    if action.lower() in ("clear", "xoa", "huy", "xong"):
        # Huy canh bao captcha = cho app farm tiep, nen CHI chu bot duoc lam (kenh co nhieu nguoi khac)
        if not (OWNER_ID and str(ctx.author.id) == str(OWNER_ID)):
            await ctx.send("Chỉ chủ bot mới huỷ được cảnh báo captcha.")
            return
        await mdb[COL_ALERTS].update_one(
            {"_id": "captcha"},
            {"$set": {"active": False, "cleared_at": _utcnow().isoformat()}}, upsert=True)
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
            {"$set": {"status": "cancelled", "completed_at": _utcnow().isoformat()}})
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

    lines.append("\n**Vừa xử lý gần đây:**")
    if recent_done:
        lines += [f"#{d['_id']} `{d['action']}` — {d['status']}" for d in recent_done]
    else:
        lines.append("(chưa có)")

    await ctx.send("\n".join(lines))


# ----------------------------------------------------------------------
# LỆNH: ghi chú
# ----------------------------------------------------------------------
@bot.command(name="note")
@is_owner()
async def note_cmd(ctx, action: str = "list", *, text: str = ""):
    if action == "add" and text:
        nid = await next_note_id()
        await mdb[COL_NOTES].insert_one({"_id": nid, "text": text, "done": False,
                                          "created_at": _utcnow().isoformat()})
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
@is_owner()
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
@is_owner()
async def pets_cmd(ctx, *, search: str = ""):
    q = {"display_name": {"$regex": re.escape(search), "$options": "i"}} if search else {}
    cursor = mdb[COL_PET_SPECIES].find(q).sort("display_name", 1).limit(25)
    rows = await cursor.to_list(length=25)
    if not rows:
        await ctx.send("Chưa ghi nhận pet nào khớp.")
        return
    lines = [f"**{r['display_name']}** ({r.get('rank','?')}) — "
             f"HP{r['hp']}/ATT{r['att']}/PR{r['pr']}/WP{r['wp']}/MAG{r['mag']}/MR{r['mr']}" for r in rows]
    await ctx.send("\n".join(lines))


@bot.command(name="petset")
@is_owner()
async def petset_cmd(ctx, name: str, rank: str, hp: int, att: int, pr: int, wp: int, mag: int, mr: int):
    """Nhập tay 1 pet khi không có sẵn owodex — vd đọc từ nguồn khác.
    Dùng: ,petset <tên> <rank> <hp> <att> <pr> <wp> <mag> <mr>"""
    key = name.lower()
    await mdb[COL_PET_SPECIES].update_one(
        {"_id": key},
        {"$set": {"display_name": name, "rank": rank.capitalize(),
                  "hp": hp, "att": att, "pr": pr, "wp": wp, "mag": mag, "mr": mr,
                  "confirmed_at": _utcnow().isoformat(),
                  "confirmed_by": str(ctx.author.id), "source": "manual"}},
        upsert=True,
    )
    await ctx.send(f"Đã lưu **{name}** ({rank}) — HP{hp}/ATT{att}/PR{pr}/WP{wp}/MAG{mag}/MR{mr}.")


# ----------------------------------------------------------------------
# LỆNH: weapon types — xem/tra cứu + nhập tay
# ----------------------------------------------------------------------
@bot.command(name="weapontype")
@is_owner()
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
@is_owner()
async def weapontypes_cmd(ctx, *, search: str = ""):
    q = {"display_name": {"$regex": re.escape(search), "$options": "i"}} if search else {}
    cursor = mdb[COL_WEAPON_TYPES].find(q).sort("display_name", 1).limit(25)
    rows = await cursor.to_list(length=25)
    if not rows:
        await ctx.send("Chưa ghi nhận loại vũ khí nào khớp.")
        return
    await ctx.send("\n".join(
        f"**{r['display_name']}** — {r.get('main_desc_vi') or r.get('main_desc','(chưa rõ mô tả)')}" for r in rows
    ))


@bot.command(name="weapontypeset")
@is_owner()
async def weapontypeset_cmd(ctx, name: str, *, desc: str):
    """Nhập/sửa tay mô tả 1 loại vũ khí. Dùng: ,weapontypeset <tên> <mô tả>"""
    key = name.lower()
    await mdb[COL_WEAPON_TYPES].update_one(
        {"_id": key},
        {"$set": {"display_name": name, "main_desc": desc,
                  "confirmed_at": _utcnow().isoformat(), "confirmed_by": str(ctx.author.id)}},
        upsert=True,
    )
    await ctx.send(f"Đã lưu mô tả cho **{name}**.")


# ----------------------------------------------------------------------
# LỆNH: passives — xem/tra cứu + nhập tay
# ----------------------------------------------------------------------
@bot.command(name="passive")
@is_owner()
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
@is_owner()
async def passives_cmd(ctx, *, search: str = ""):
    q = {"display_name": {"$regex": re.escape(search), "$options": "i"}} if search else {}
    cursor = mdb[COL_PASSIVES].find(q).sort("display_name", 1).limit(25)
    rows = await cursor.to_list(length=25)
    if not rows:
        await ctx.send("Chưa ghi nhận passive nào khớp.")
        return
    await ctx.send("\n".join(f"**{r['display_name']}** — {r.get('description_vi') or r['description']}" for r in rows))


@bot.command(name="passiveset")
@is_owner()
async def passiveset_cmd(ctx, name: str, *, desc: str):
    """Nhập/sửa tay 1 passive. Dùng: ,passiveset <tên> <mô tả>"""
    await save_passive(name, desc, str(ctx.author.id))
    await ctx.send(f"Đã lưu passive **{name}**.")


@bot.command(name="ping")
async def ping_cmd(ctx):
    ms = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! `{ms}ms` · bot `{bot_version_text()}`")


# Danh sách lệnh hiện trong `,help`. Mỗi nhóm: (tên lệnh, chữ hiện ra). Lệnh nào bot không có thì tự bỏ qua.
# QUY ƯỚC: mỗi lần thêm / đổi / xóa lệnh phải cập nhật ở đây — test_help.py sẽ báo lỗi nếu quên.
HELP_GROUPS = [
    ("Theo dõi cá nhân", [
        ("status", "`,status` (owner): đang theo dõi ai, phạm vi (kênh/server), phiên bản bot và tình trạng huntbot"),
        ("huntbot", "`,huntbot` (owner): trạng thái HuntBot — tiến độ, số pet bắt được, còn bao lâu nữa về"),
        ("quests", "`,quests` (owner): quest hôm nay và tiến độ từng quest"),
        ("team", "`,team` (owner): đội hình gần nhất bot đọc được"),
        ("teamcheck", "`,teamcheck` (owner): chấm đội hình đang đứng"),
        ("inv", "`,inv [tìm]` (owner): kho đồ đã ghi nhận, lọc theo tên"),
        ("gems", "`,gems` (owner): độ bền từng slot gem đang trang bị"),
        ("gemtier", "`,gemtier [loại] [tier]` (owner): chọn tier gem dùng khi thay, riêng từng loại (hunting/empowering/lucky/special) · "
                    "`,gemtier tat|bat <loại> <tier>` bật/tắt tier được phép dùng · `,gemtier ?` xem hướng dẫn")]),
    ("Zoo", [
        ("zoo", "`,zoo [tìm]` (owner): zoo đang giữ, lọc theo tên pet"),
        ("unlocked", "`,unlocked [tier]` (owner): pet đã mở khóa, không hiện số lượng"),
        ("zoodiff", "`,zoodiff [d|now]` (owner): so 2 lần ghi zoo gần nhất, `d` = số đã bắt, `now` = đang giữ")]),
    ("Vũ khí của tôi", [
        ("myweapons", "`,myweapons [tìm]` (owner): vũ khí bạn đang sở hữu, tìm theo tên"),
        ("weaponscan", "`,weaponscan` (owner): quét lại kho vũ khí, nhớ dừng farm"),
        ("weaponprobe", "`,weaponprobe` (owner): xếp lệnh `owo w <ID>` cho app từ danh sách đã quét"),
        ("weaponlist", "`,weaponlist` (owner): gửi file danh sách vũ khí đã quét"),
        ("weaponreview", "`,weaponreview [stop|undo|export|reset]` (owner): bắt đầu bằng QUÉT LẠI kho (app gõ `owo w` + lật trang, dừng farm trước; chỉ nhận trang `<@bạn>'s Weapons`) rồi duyệt từng cây bằng 2 nút Giữ/Bỏ trên Hub nổi, chỉ ghi danh sách, KHÔNG tự xóa hay bán; `stop` dừng · `undo` hoàn tác cây vừa chọn · `export` gửi file Giữ/Bỏ · `reset` xóa hết quyết định"),
        ("dismantleplan", "`,dismantleplan` (owner): lập kế hoạch dọn vũ khí (giữ/rác/xám), CHƯA xóa gì"),
        ("weaponknowledge", "`,weaponknowledge` (owner): gửi lại file kiến thức vũ khí"),
        ("weaponadvice", "`,weaponadvice` (owner): gửi lại file lời khuyên vũ khí"),
        ("weaponowner", "`,weaponowner [Tên1, Tên2|xoa]` (owner): chỉ ghi vũ khí có tên chủ khớp tên Discord; thêm tên khác hoặc xóa tên đã thêm")]),
    ("Dọn kho vũ khí (từ file NeonUtil, bạn tự làm — bot không tự gõ/bấm)", [
        ("neonauto", "`,neonauto on|off` (owner): Tom tự nhận file khi NeonUtil trả lời đúng lệnh `nw inv export` của chính bạn (mặc định BẬT), rồi lập kế hoạch + phiên dọn kho cho app"),
        ("dropadd", "`,dropadd <ID>…` (owner): thêm ID vũ khí vào danh sách RÃ (rã theo ID, kể cả cây ở vùng chưa rõ bậc); `,dropadd -x <ID>` gỡ; `,dropadd` xem danh sách"),
        ("cleanstop", "`,cleanstop` (owner): dừng dọn kho tự động và hủy các bước đang chờ (app chỉ làm khi bạn bật công tắc trong Hub)"),
        ("weaponimport", "`,weaponimport` (owner): BƯỚC 1 — tự gõ `nw inv export` (lệnh NeonUtil cho phép) rồi ĐÍNH KÈM file `weapons.json` vào tin này; bot lập danh sách Giữ/Bỏ (khóa · có kill · chỉ số chính ≥ 80% · passive hạng ≥ 5 · không có bp thì chất lượng ≥ 75 → Giữ), gửi `weapon_import_plan.json`, KHÔNG xóa hay bán gì"),
        ("cleanplan", "`,cleanplan` (owner): BƯỚC 2 — xem kế hoạch dọn kho (cách lai) kèm số cây để đối chiếu: sao cây Giữ ở chất lượng thấp → rã theo bậc → rã theo ID phần còn lại"),
        ("knowledgetop", "`,knowledgetop` (owner; còn `,kno`): embed top 6 cây có passive Knowledge cao nhất bot đang lưu (ID, % Knowledge, loại, chất lượng); cây cao hơn xuất hiện sẽ thay cây thấp nhất"),
        ("starlist", "`,starlist [trang] [lệnh trước ID]` (owner): liệt kê cây GIỮ cần đánh sao trước khi rã theo bậc (OwO bỏ qua cây đã sao); mỗi cây gõ `owo w <ID>` rồi chạm nút ⭐; ví dụ `,starlist 1 owo w` tạo sẵn từng dòng lệnh"),
        ("dismantlelist", "`,dismantlelist [số ID mỗi lệnh] [trang]` (owner): tạo sẵn các dòng `owo dismantle <ID>` cho cây Bỏ ở chất lượng ≥ 61; bạn tự dán từng dòng, đọc tin xác nhận của OwO rồi tự bấm Dismantle")]),
    ("Huntbot và acc phụ", [
        ("hbstart", "`,hbstart [24h|số cowoncy]`: nhờ app gõ `owo hb <số>` để OwO đưa mật khẩu huntbot (mặc định 24h)"),
        ("hbcode", "`,hbcode [24h] <mã>`: nhập mã mật khẩu huntbot bạn đã đọc, app sẽ gõ `owo hb <số> <mã>` (bot không tự giải mã)"),
        ("hbauto", "`,hbauto on|off` (owner): bật/tắt tự nhờ app chạy lại huntbot khi vừa về; không kèm gì = xem trạng thái"),
        ("hbalert", "`,hbalert on|off` (owner): DM acc phụ khi huntbot còn 10 phút (bản dự phòng cho thông báo trên app)"),
        ("setalt", "`,setalt [id|xoa]` (owner): xem / đặt / tắt acc phụ nhận DM nhắc huntbot"),
        ("testalt", "`,testalt` (owner): thử gửi 1 tin DM vào acc phụ để kiểm tra có nhận được không")]),
    ("Chế độ và cảnh báo", [
        ("off", "`,off` (owner): TẮT mọi hoạt động của app · `,off on` bật lại · `,off status` xem"),
        ("eventmode", "`,eventmode on|off` (owner): bật khi có sự kiện, được dùng slot thứ 4"),
        ("captcha", "`,captcha` xem cảnh báo · `,captcha clear` báo đã giải xong"),
        ("autocheck", "`,autocheck on|off` (owner): app đang farm thì bot nhờ app gõ xen lệnh check cho mục dữ liệu đã cũ")]),
    ("Ghi chú", [
        ("note", "`,note add <text>` · `,note list` · `,note done <id>` (owner): ghi việc cần làm, xem danh sách, đánh dấu đã xong")]),
    ("Pet (loài)", [
        ("pet", "`,pet <tên>` / `,dex <tên>` (owner): tra dex đầy đủ 1 loài (rank, chỉ số, giá bán...)"),
        ("pets", "`,pets [tìm]` (owner): liệt kê pet đã ghi nhận, tìm theo tên hoặc rank"),
        ("zoodex", "`,zoodex` / `,dexzoo` (owner): nhờ app tra dex cho pet trong zoo chưa có dex hoặc dex còn thiếu (rank/chỉ số/nhập tay) · `,zoodex xem` chỉ liệt kê"),
        ("petset", "`,petset <tên> <rank> <hp> <att> <pr> <wp> <mag> <mr>` (owner): nhập tay 1 pet khi chưa có dex")]),
    ("Loại vũ khí", [
        ("weapontype", "`,weapontype <tên>` (owner): xem 1 loại vũ khí đã ghi nhận (hiệu ứng cố định...)"),
        ("weapontypes", "`,weapontypes [tìm]` (owner): liệt kê các loại vũ khí đã biết"),
        ("weapontypeset", "`,weapontypeset <tên> <mô tả>` (owner): nhập/sửa tay mô tả 1 loại vũ khí")]),
    ("Passive", [
        ("passive", "`,passive <tên>` (owner): tra 1 passive đã ghi nhận"),
        ("passives", "`,passives [tìm]` (owner): liệt kê các passive đã biết"),
        ("passiveset", "`,passiveset <tên> <mô tả>` (owner): nhập/sửa tay mô tả 1 passive")]),
    ("Cài đặt bot (owner)", [
        ("track", "`,track @user` (owner): chọn tài khoản OwO cần theo dõi"),
        ("setprefixes", "`,setprefixes owo,o` (owner): khai báo prefix OwO của bạn — bắt buộc nếu bạn gõ tắt (vd `o`)"),
        ("setserver", "`,setserver here|<ID>|xoa` (owner): theo dõi cả 1 server (mọi kênh); `here` = server đang gõ, `xoa` = bỏ giới hạn"),
        ("setchannel", "`,setchannel [#kênh|xoa]` (owner): chỉ theo dõi 1 kênh; không kèm gì = xem trạng thái"),
        ("ignorechannel", "`,ignorechannel here|#kênh|xoa [#kênh]` / `,boqua` (owner): Tom BỎ QUA 1 kênh trong server đang theo dõi (không đọc lệnh owo và tin OwO ở đó); không kèm gì = xem danh sách"),
        ("rawdump", "`,rawdump [xoa]` (owner): gửi qua DM file tin OwO nguyên văn bot đọc được để đối chiếu; `xoa` = xóa mẫu cũ"),
        ("debugnext", "`,debugnext` (owner): in nội dung tin OwO kế tiếp ra console để gỡ lỗi"),
        ("automacro", "`,automacro [clear]` (owner): xem lệnh đang chờ / đã xử lý của app; `clear` = hủy hết lệnh đang chờ")]),
    ("Khác", [
        ("ping", "`,ping`: kiểm tra bot còn sống, độ trễ và phiên bản"),
        ("help", "`,help`: xem lại danh sách lệnh này")]),
]


HELP_PAGE_CHARS = 5200   # mỗi embed Discord tối đa 6000 ký tự; chừa chỗ cho tiêu đề / chân trang


def build_help_pages(has_command=None):
    """Chia HELP_GROUPS thành các trang (mỗi trang là 1 embed): [[(tên_field, nội_dung), ...], ...].
    Mỗi lệnh 1 dòng; field <= 1000 ký tự, trang <= HELP_PAGE_CHARS. Lệnh bot không có thì tự bỏ qua."""
    has_command = has_command or (lambda name: True)
    fields = []
    for title, items in HELP_GROUPS:
        lines = ["• " + txt for name, txt in items if has_command(name)]
        cur, size, part = [], 0, 0
        for ln in lines + [None]:
            if ln is None or (cur and size + len(ln) + 1 > 1000):
                if cur:
                    fields.append((title if part == 0 else title + " (tiếp)", "\n".join(cur)))
                    part += 1
                cur, size = [], 0
            if ln is not None:
                cur.append(ln)
                size += len(ln) + 1
    pages, page, size = [], [], 0
    for name, value in fields:
        cost = len(name) + len(value)
        if page and size + cost > HELP_PAGE_CHARS:
            pages.append(page)
            page, size = [], 0
        page.append((name, value))
        size += cost
    if page:
        pages.append(page)
    return pages


@bot.command(name="help")
async def help_cmd(ctx):
    groups = HELP_GROUPS
    pages = build_help_pages(lambda name: bot.get_command(name) is not None)
    covered = {name for _, items in groups for name, _ in items}
    # Lưới an toàn: lệnh nào mới thêm mà chưa có trong danh sách trên thì tự hiện ra, help không bao giờ lỗi thời im lặng
    extra = sorted(c.name for c in bot.commands if c.name not in covered)
    if extra and pages:
        pages[-1].append(("Lệnh mới (chưa có mô tả trong ,help)", " · ".join(f"`,{n}`" for n in extra)[:1000]))
    for i, fields in enumerate(pages):
        embed = discord.Embed(
            title=f"OwO Tracker {bot_version_text()} — danh sách lệnh" if i == 0 else "OwO Tracker — danh sách lệnh (tiếp)",
            description="Prefix: `,` · (owner) = chỉ chủ bot dùng được" if i == 0 else None,
            color=0xD9A227,
        )
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        if i == len(pages) - 1:
            embed.set_footer(text=f"Bot {bot_version_text()} · Chỉ thấy được server đã mời nó vào — không tự theo dõi ở nơi khác.")
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
