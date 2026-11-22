"""test_new_pet.py — pet mới khi hunt: lệnh owo dex + DM tên/emoji. Chạy: python test_new_pet.py"""
import sys, asyncio
from unittest.mock import MagicMock

for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import new_pet as np_
import owo_tracker_bot as b

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# --- hàm thuần ---
check("lệnh dex", np_.dex_command("gowl"), "owo dex gowl")
check("tên lạ không tạo lệnh", (np_.dex_command("a b"), np_.dex_command("<@1>"), np_.dex_command(""), np_.dex_command("x" * 33), np_.dex_command(None)),
      (None, None, None, None, None))
check("ảnh emoji tĩnh / động / thường", (
    np_.emoji_image_url({"emoji_id": "123"}), np_.emoji_image_url({"emoji_id": "456", "emoji_animated": True}), np_.emoji_image_url({"name": "bee"})),
    ("https://cdn.discordapp.com/emojis/123.png?size=96&quality=lossless", "https://cdn.discordapp.com/emojis/456.gif?size=96&quality=lossless", None))
animals = [{"name": "Gowl", "emoji_id": "1", "emoji_animated": False}, {"name": "bee"}, {"name": "dragon", "emoji_id": "2", "emoji_animated": True}]
got = np_.pick(["gowl", "GOWL", "dragon", "unknown", "x1", "x2"], animals)
check("pick: bỏ trùng, giữ thông tin emoji, tối đa 3", [(e["name"], e["emoji_id"]) for e in got], [("Gowl", "1"), ("dragon", "2"), ("unknown", None)])
txt = np_.dm_text([{"name": "gowl", "emoji_id": "1"}], lambda e: "<:gowl:1>", True)
check("DM 1 pet", txt, "🆕 **Pet mới!**\n<:gowl:1> **gowl**\nApp sẽ gõ `owo dex gowl` để ghi nhận.")
txt = np_.dm_text([{"name": "gowl"}, {"name": "2026november_pumpkinpie"}], lambda e: "E", False)
check("DM nhiều pet, có pet sự kiện, không xếp lệnh", txt, "🆕 **2 pet mới!**\nE **gowl**\nE **2026november_pumpkinpie** 🍂 **PET SỰ KIỆN!**")

check("tin trong kênh kèm sẵn lệnh dex + tag", np_.channel_text([{"name": "gowl"}], lambda e: "E", "<@9>"),
      "<@9> 🆕 **Pet mới!**\nE **gowl**\nGõ `owo dex gowl` để ghi nhận.")
check("tin trong kênh nhiều pet, không tag", np_.channel_text([{"name": "a"}, {"name": "bad name"}], lambda e: "E"),
      "🆕 **2 pet mới!**\nE **a**\nE **bad name**\nGõ `owo dex a` để ghi nhận.")

# --- luồng trong bot (thay các hàm I/O bằng bản giả) ---
async def run(app_off, dm_ok=True, queue_ok=True):
    log = {"queued": [], "dm": []}
    async def off(): return app_off
    async def queue(action, params):
        log["queued"].append((action, params))
        return 7 if queue_ok else None
    async def dm(uid, text, images=None):
        log["dm"].append((uid, text, images)); return dm_ok
    async def cfg(key, default=None): return "999" if key == "tracked_user_id" else default
    b.is_app_off, b.queue_automacro_command, b.dm_user, b.get_config = off, queue, dm, cfg
    found = {"animals": [{"name": "gowl", "emoji_id": "55", "emoji_animated": True}, {"name": "bee"}]}
    await b.announce_new_pets(["gowl"], found, 1)
    return log

log = asyncio.run(run(False))
check("xếp đúng 1 lệnh owo dex cho app", log["queued"], [("dex_pet", {"command_text": "owo dex gowl", "pet": "gowl"})])
uid, text, images = log["dm"][0]
check("DM cho người dùng được theo dõi, có tên + emoji + ảnh", (uid, "**gowl**" in text, "<a:gowl:55>" in text, images),
      ("999", True, True, ["https://cdn.discordapp.com/emojis/55.gif?size=96&quality=lossless"]))
class FakeChannel:
    def __init__(self): self.sent = []
    async def send(self, text, allowed_mentions=None): self.sent.append(text)

async def run_off(channel):
    log = {"queued": [], "dm": []}
    async def off(): return True
    async def queue(action, params): log["queued"].append(action); return 1
    async def dm(uid, text, images=None): log["dm"].append(text); return True
    async def cfg(key, default=None): return "999" if key == "tracked_user_id" else default
    b.is_app_off, b.queue_automacro_command, b.dm_user, b.get_config = off, queue, dm, cfg
    await b.announce_new_pets(["gowl"], {"animals": [{"name": "gowl", "emoji_id": "55", "emoji_animated": True}]}, 1, channel=channel)
    return log

ch = FakeChannel()
log = asyncio.run(run_off(ch))
check("Hub tắt: đăng tin trong kênh có tag + lệnh owo dex, không xếp lệnh, không DM", (log["queued"], log["dm"], len(ch.sent),
      ch.sent and ("<@999>" in ch.sent[0], "`owo dex gowl`" in ch.sent[0], "<a:gowl:55>" in ch.sent[0])), ([], [], 1, (True, True, True)))
log = asyncio.run(run_off(None))
check("Hub tắt mà không có kênh: im lặng, không lỗi", (log["queued"], log["dm"]), ([], []))
log = asyncio.run(run(False, queue_ok=False))
check("không xếp được lệnh vẫn DM nhưng không hứa gõ dex", ("App sẽ gõ" in log["dm"][0][1], len(log["dm"])), (False, 1))
log = asyncio.run(run(False, dm_ok=False))
check("DM lỗi không làm hỏng luồng (lệnh vẫn xếp)", len(log["queued"]), 1)

async def boom():
    async def off(): raise RuntimeError("x")
    b.is_app_off = off
    await b.announce_new_pets(["gowl"], {"animals": []}, 1)
asyncio.run(boom())
check("lỗi bất ngờ bị nuốt, không văng ra luồng hunt", True, True)

print("\nTất cả pass" if not fails else f"\n{len(fails)} lỗi: {fails}")
sys.exit(1 if fails else 0)
