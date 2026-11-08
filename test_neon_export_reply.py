"""test_neon_export_reply.py — handle_neon_export_reply: nhận file `nw inv export` của Neon, và NÓI RÕ LÝ DO khi bỏ qua.
Chạy: python test_neon_export_reply.py   (cần mongomock-motor như các test khác)"""
import sys, asyncio
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b
from mongomock_motor import AsyncMongoMockClient

if not isinstance(b.discord.Message, type):   # discord giả (MagicMock): isinstance() cần một class thật
    b.discord.Message = type("Message", (), {})

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

OWNER = "111111111111111111"

from datetime import datetime, timedelta, timezone
NOW = datetime(2026, 11, 9, 5, 50, tzinfo=timezone.utc)

def neon_msg(orig, filename="weapons.json", with_ref=True, size=100, history=None, history_error=False):
    """history = tin trong kênh TRƯỚC file Neon, mới nhất trước (dùng khi Neon không reply)."""
    async def fetch_message(_id):
        if orig is None:
            raise RuntimeError("Forbidden")
        return orig
    async def hist(limit=100, before=None):
        if history_error:
            raise RuntimeError("Forbidden")
        for m in (history or []):
            yield m
    att = NS(filename=filename, size=size, read=None)
    ref = NS(message_id=555, resolved=None) if with_ref else None
    return NS(attachments=[att] if filename else [], reference=ref, created_at=NOW,
              channel=NS(fetch_message=fetch_message, history=hist))

def cmd(author_id=OWNER, content="nw inv export", ago=20):
    return NS(author=NS(id=author_id), content=content, created_at=NOW - timedelta(seconds=ago))

async def scenarios():
    b.mdb = AsyncMongoMockClient()["neon_test"]
    old = (b.OWNER_ID, b.notify_owner, b.import_weapon_export)
    notes, imported = [], []
    async def fake_notify(text, *a, **k):
        notes.append(text); return True
    async def fake_import(raw, auto_session=False):
        imported.append(auto_session); return "KE HOACH"
    async def fake_read():
        return b"{}"
    b.notify_owner, b.import_weapon_export = fake_notify, fake_import
    try:
        async def run(msg, owner=OWNER):
            b.OWNER_ID = owner
            notes.clear(); imported.clear()
            msg.attachments and setattr(msg.attachments[0], "read", fake_read)
            await b.handle_neon_export_reply(msg)
            return list(notes), list(imported)

        n, i = await run(neon_msg(cmd()))
        check("hợp lệ: nhập file với auto_session và báo Ruby", (i, len(n), "Tom đã tự nhận file" in n[0]), ([True], 1, True))
        n, i = await run(neon_msg(cmd(content="  NW inv export  ")))
        check("lệnh gốc viết hoa/thừa khoảng trắng vẫn nhận", (i, len(n)), ([True], 1))

        n, i = await run(neon_msg(cmd(), filename=""))
        check("tin Neon KHÔNG có file .json: im lặng, không báo", (n, i), ([], []))
        n, i = await run(neon_msg(cmd(), filename="anh.png"))
        check("file không phải .json: im lặng", (n, i), ([], []))

        n, i = await run(neon_msg(cmd()), owner="")
        check("thiếu OWNER_ID: báo rõ", (i, len(n), "OWNER_ID" in n[0]), ([], 1, True))
        await b.set_config("neon_autoimport", "off")
        n, i = await run(neon_msg(cmd()))
        check("đã tắt `,neonauto`: báo cách bật lại", (i, len(n), ",neonauto on" in n[0]), ([], 1, True))
        await b.set_config("neon_autoimport", "on")
        # --- Neon gửi file KHÔNG kèm reply: tìm lệnh export gần nhất của OWNER trong kênh ---
        n, i = await run(neon_msg(None, with_ref=False, history=[cmd(ago=30)]))
        check("không reply + lệnh của OWNER 30 giây trước: vẫn nhận", (i, len(n), "Tom đã tự nhận file" in n[0]), ([True], 1, True))
        n, i = await run(neon_msg(None, with_ref=False, history=[cmd(author_id="999", content="chat"), cmd(content="owo hunt", ago=5), cmd(ago=60)]))
        check("không reply: bỏ qua tin chat/lệnh khác, lấy lệnh export của OWNER", (i, len(n)), ([True], 1))
        n, i = await run(neon_msg(None, with_ref=False, history=[cmd(ago=180)]))
        check("không reply + đúng 3 phút: vẫn nhận (biên)", (i, len(n)), ([True], 1))
        n, i = await run(neon_msg(None, with_ref=False, history=[cmd(ago=181)]))
        check("không reply + lệnh cũ hơn 3 phút: KHÔNG gán nhầm, báo rõ", (i, len(n), "3 phút" in n[0]), ([], 1, True))
        n, i = await run(neon_msg(None, with_ref=False, history=[]))
        check("không reply + không có lệnh nào: báo rõ", (i, len(n), "Neon không reply" in n[0]), ([], 1, True))
        n, i = await run(neon_msg(None, with_ref=False, history=[cmd(author_id="999", ago=10)]))
        check("không reply + lệnh export của NGƯỜI KHÁC: không nhận", (i, len(n)), ([], 1))
        n, i = await run(neon_msg(None, with_ref=False, history_error=True))
        check("không reply + không đọc được lịch sử kênh: báo rõ, không văng lỗi", (i, len(n), "3 phút" in n[0]), ([], 1, True))
        n, i = await run(neon_msg(None))
        check("không đọc được tin gốc: nhắc quyền Read Message History", (i, len(n), "Read Message History" in n[0]), ([], 1, True))
        n, i = await run(neon_msg(cmd(author_id="999")))
        check("tin gốc do tài khoản khác gõ: nêu cả 2 ID", (i, len(n), "999" in n[0] and OWNER in n[0]), ([], 1, True))
        n, i = await run(neon_msg(cmd(content="owo hunt")))
        check("tin gốc không phải nw inv export: nêu nội dung", (i, len(n), "owo hunt" in n[0]), ([], 1, True))
        n, i = await run(neon_msg(cmd(), size=21 * 1024 * 1024))
        check("file quá lớn: báo rõ", (i, len(n), "20 MB" in n[0]), ([], 1, True))
    finally:
        b.OWNER_ID, b.notify_owner, b.import_weapon_export = old

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test nhận file export của Neon pass.")
