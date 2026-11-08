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

def neon_msg(orig, filename="weapons.json", with_ref=True, size=100):
    async def fetch_message(_id):
        if orig is None:
            raise RuntimeError("Forbidden")
        return orig
    att = NS(filename=filename, size=size, read=None)
    ref = NS(message_id=555, resolved=None) if with_ref else None
    return NS(attachments=[att] if filename else [], reference=ref, channel=NS(fetch_message=fetch_message))

def cmd(author_id=OWNER, content="nw inv export"):
    return NS(author=NS(id=author_id), content=content)

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
        n, i = await run(neon_msg(cmd(), with_ref=False))
        check("Neon không reply: báo rõ", (i, len(n), "reply" in n[0]), ([], 1, True))
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
