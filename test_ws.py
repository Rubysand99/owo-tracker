"""test_ws.py — kiểm tra bộ đọc weapon shards (owo ws) bằng tin OwO THẬT.
Chạy: python test_ws.py"""
import sys, asyncio
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# Mẫu thật (Discord hiện chữ thường, emoji thành tên "weaponshard")
check("ws: mẫu thật từ màn hình", b.parse_weapon_shards(
    "weaponshard | Ruby, you currently have 1,174 Weapon Shards!"), {"amount": 1174})
# Tin gốc OwO gửi: có emoji, in đậm
check("ws: dạng gốc có emoji + in đậm", b.parse_weapon_shards(
    "<:weaponshard:837538614409691166> **| Ruby**, you currently have **1,174** Weapon Shards!"), {"amount": 1174})
check("ws: số lớn nhiều dấu phẩy", b.parse_weapon_shards(
    "<:weaponshard:1> **| Ruby**, you currently have **12,345,678** Weapon Shards!"), {"amount": 12345678})
check("ws: đúng 1 mảnh (số ít)", b.parse_weapon_shards(
    "weaponshard | Ruby, you currently have 1 Weapon Shard!"), {"amount": 1})
check("ws: 0 mảnh vẫn đọc được", b.parse_weapon_shards(
    "weaponshard | Ruby, you currently have 0 Weapon Shards!"), {"amount": 0})
# Không nhầm lẫn giữa cowoncy và ws
CASH = "<:cowoncy:1> **| Ruby**, you currently have **2,061,145** cowoncy!"
check("ws: tin cowoncy KHÔNG bị đọc thành ws", b.parse_weapon_shards(CASH), None)
check("cowoncy: tin ws KHÔNG bị đọc thành cowoncy", b.parse_cowoncy(
    "weaponshard | Ruby, you currently have 1,174 Weapon Shards!"), None)
check("ws: tin lạ trả None", b.parse_weapon_shards("Ruby, hunt is empowered by gems"), None)

async def roundtrip():
    b.mdb = AsyncMongoMockClient()["ws_test"]
    await b.load_emoji_cache()
    from datetime import datetime
    check("hub ws: chưa có dữ liệu -> None", await b._hub_weapon_shards(datetime.utcnow()), None)
    await b.save_weapon_shards({"amount": 1174}, "999")
    h = await b._hub_weapon_shards(datetime.utcnow())
    check("hub ws: lưu rồi đọc lại đúng số", h["amount"], 1174)
    check("hub ws: có tuổi dữ liệu", "age_seconds" in h, True)
    await b.save_weapon_shards({"amount": 1500}, "999")
    h = await b._hub_weapon_shards(datetime.utcnow())
    check("hub ws: lần sau đè lần trước", h["amount"], 1500)
asyncio.run(roundtrip())

if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test ws pass.")
