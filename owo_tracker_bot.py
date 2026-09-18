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
import asyncio
from datetime import datetime

import discord
from discord.ext import commands
from motor.motor_asyncio import AsyncIOMotorClient

# ----------------------------------------------------------------------
# CẤU HÌNH
# ----------------------------------------------------------------------
OWO_BOT_ID = 408785106942164992  # kiểm tra lại ID thật trong server bạn
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
OWNER_ID = os.environ.get("OWNER_ID")
MONGODB_URI = os.environ.get("MONGODB_URI")
MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "owo_tracker")
CORRELATION_WINDOW = 20  # giây — cửa sổ khớp lệnh owo với phản hồi của OwO bot

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
COL_BATTLES = "owot_battles"
COL_HUNTBOT = "owot_huntbot_status"
COL_QUEST = "owot_quest_status"
COL_NOTES = "owot_notes"

pending_commands = {}  # channel_id -> timestamp gần nhất có lệnh owo từ tracked user


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
        "id": id_m.group(1).strip(),
        "quality": float(quality_m.group(1)) if quality_m else None,
        "main_desc": main_desc_m.group(1).strip() if main_desc_m else None,
        "inherent_effects": inherent_effects,
        "passive": roll_passive,
    }


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
        stat_zone = re.sub(r"Lvl\s*\d+\s*\[[\d,/]+\]", "", block)
        stat_zone = re.sub(r"`[A-Z0-9]{6}`.*", "", stat_zone, flags=re.S)
        nums = re.findall(r"(\d+)%?", stat_zone)
        entry = {
            "pos": i, "name": name_m.group(1).strip(),
            "level": int(lvl_m.group(1)) if lvl_m else None,
            "weaponId": weapon_m.group(1) if weapon_m else None,
            "quality": float(quality_m.group(1)) if quality_m else None,
        }
        if len(nums) >= 6:
            entry.update({"hp": int(nums[0]), "wp": int(nums[1]), "att": int(nums[2]),
                          "mag": int(nums[3]), "pr": int(nums[4]), "mr": int(nums[5])})
        result.append(entry)
    return result


def parse_battle_result(text: str):
    m = re.search(r"You (won|lost) in (\d+) turns?!\s*\|\s*\+?([\d,]+)\s*xp\s*\|\s*Streak:\s*(\d+)", text)
    if not m:
        return None
    return {"result": m.group(1), "turns": int(m.group(2)),
            "xp": int(m.group(3).replace(",", "")), "streak": int(m.group(4))}


def parse_huntbot_status(text: str):
    if "HUNTBOT" not in text.upper():
        return None
    essence_m = re.search(r"Animal Essence.*?[-–]?\s*(\d+)", text)
    hunting = "STILL HUNTING" in text.upper() or "currently hunting" in text.lower()
    progress_m = re.search(r"([\d.]+)%\s*DONE", text.upper())
    animals_m = re.search(r"([\d,]+)\s*ANIMALS CAPTURED", text.upper())
    time_m = re.search(r"BACK IN\s*([0-9HMhm ]+)", text.upper())
    return {
        "essence": int(essence_m.group(1)) if essence_m else None,
        "hunting": hunting,
        "progress_pct": float(progress_m.group(1)) if progress_m else None,
        "animals_captured": int(animals_m.group(1).replace(",", "")) if animals_m else None,
        "time_remaining": time_m.group(1).strip() if time_m else None,
    }


def parse_quest_status(text: str):
    if "Quest Log" not in text and "Quest Seals" not in text:
        return None
    seals_m = re.search(r"Balance:\s*(\d+)", text)
    all_done = "finished all" in text.lower() or "come back tomorrow" in text.lower()
    next_m = re.search(r"Next quest:\s*([^\n]+)", text)
    return {
        "seals": int(seals_m.group(1)) if seals_m else None,
        "all_done": all_done,
        "next_quest": next_m.group(1).strip() if next_m else None,
    }


# ----------------------------------------------------------------------
# LƯU — tất cả upsert theo key tự nhiên (tên pet, tên loại vũ khí, tên
# passive, ID vũ khí) nên gọi lại nhiều lần không tạo bản trùng.
# ----------------------------------------------------------------------
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


async def save_battle(b):
    b = dict(b)
    b["created_at"] = datetime.utcnow().isoformat()
    await mdb[COL_BATTLES].insert_one(b)


async def save_huntbot(h):
    h = dict(h)
    h["created_at"] = datetime.utcnow().isoformat()
    await mdb[COL_HUNTBOT].insert_one(h)


async def save_quest(q):
    q = dict(q)
    q["created_at"] = datetime.utcnow().isoformat()
    await mdb[COL_QUEST].insert_one(q)


# ----------------------------------------------------------------------
# LẮNG NGHE
# ----------------------------------------------------------------------
@bot.event
async def on_ready():
    print(f"[tracker] Đăng nhập: {bot.user}")
    if mdb is None:
        print("[tracker] CẢNH BÁO: chưa có MONGODB_URI — bot sẽ lỗi khi cố lưu/đọc dữ liệu.")
        return
    tracked = await get_config("tracked_user_id")
    print(f"[tracker] Đang theo dõi user ID: {tracked or '(chưa đặt — dùng ,track)'}")


@bot.event
async def on_message(message: discord.Message):
    if mdb is None:
        await bot.process_commands(message)
        return

    tracked_id = await get_config("tracked_user_id")

    if tracked_id and str(message.author.id) == str(tracked_id) \
            and message.content.lower().startswith("owo"):
        pending_commands[message.channel.id] = time.time()
        await bot.process_commands(message)
        return

    if message.author.id == OWO_BOT_ID:
        last = pending_commands.get(message.channel.id)
        if last and (time.time() - last) < CORRELATION_WINDOW:
            pending_commands[message.channel.id] = time.time()
            await handle_owo_response(message, tracked_id)

    await bot.process_commands(message)


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
        await save_weapon_type(weapon, source_id)
        await save_weapon_instance(weapon, source_id)
        if weapon.get("passive"):
            await save_passive(weapon["passive"]["name"], weapon["passive"]["desc"], source_id)
        for eff in weapon.get("inherent_effects", []):
            await save_passive(eff["name"], eff["desc"], source_id)

    if "Lvl" in text and re.search(r"\[\d+\]", text):
        team = parse_team(text)
        if team:
            await save_team(team)

    battle = parse_battle_result(text)
    if battle:
        await save_battle(battle)

    hunt = parse_huntbot_status(text)
    if hunt:
        await save_huntbot(hunt)

    quest = parse_quest_status(text)
    if quest:
        await save_quest(quest)


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


@bot.command(name="status")
async def status(ctx):
    tracked = await get_config("tracked_user_id")
    last_battle = await mdb[COL_BATTLES].find_one(sort=[("_id", -1)])
    last_hunt = await mdb[COL_HUNTBOT].find_one(sort=[("_id", -1)])

    embed = discord.Embed(title="Trạng thái theo dõi", color=0xD9A227)
    embed.add_field(name="Đang theo dõi", value=f"<@{tracked}>" if tracked else "Chưa đặt — dùng `,track`", inline=False)
    if last_battle:
        embed.add_field(name="Trận gần nhất",
                         value=f"{'Thắng' if last_battle['result']=='won' else 'Thua'} sau {last_battle['turns']} lượt · "
                               f"+{last_battle['xp']} xp · Streak {last_battle['streak']}", inline=False)
    if last_hunt:
        state = f"{last_hunt['progress_pct']}% · {last_hunt['animals_captured']} pet · còn {last_hunt['time_remaining']}" \
            if last_hunt["hunting"] else "Không đang hunt"
        embed.add_field(name="HuntBot", value=state, inline=False)
    await ctx.send(embed=embed)


@bot.command(name="battlelog")
async def battlelog(ctx, n: int = 5):
    cursor = mdb[COL_BATTLES].find().sort("_id", -1).limit(min(n, 20))
    rows = await cursor.to_list(length=20)
    if not rows:
        await ctx.send("Chưa có trận nào được ghi nhận.")
        return
    lines = [f"{'✅' if r['result']=='won' else '❌'} {r['turns']} lượt · +{r['xp']} xp · Streak {r['streak']} "
             f"· {r['created_at'][:16].replace('T',' ')}" for r in rows]
    await ctx.send("**Nhật ký trận đấu gần đây:**\n" + "\n".join(lines))


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
    lines = [f"[{r['pos']}] **{r['name']}** Lvl{r['level']} — HP{r['hp']} WP{r['wp']} "
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
        value="`,track @user` (owner) · `,status` · `,battlelog [n]` · "
              "`,huntbot` · `,quests` · `,team` · `,myweapons [tìm]`",
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
    embed.add_field(name="Khác", value="`,ping` · `,help` · `,debugnext` (owner)", inline=False)
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
