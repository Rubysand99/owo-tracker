"""test_spawn.py — spawn(): tác vụ nền được giữ tham chiếu tới khi xong, lỗi in ra Logs. Chạy: python test_spawn.py"""
import sys, asyncio, io, contextlib
from unittest.mock import MagicMock
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

async def main():
    done = []
    gate = asyncio.Event()
    async def work():
        await gate.wait()
        done.append(1)
    t = b.spawn(work(), "work")
    await asyncio.sleep(0)
    check("đang chạy: được giữ tham chiếu mạnh", t in b._bg_tasks, True)
    gate.set(); await t; await asyncio.sleep(0)
    check("xong: chạy tới cùng và được giải phóng", (done, t in b._bg_tasks), ([1], False))

    async def boom():
        raise RuntimeError("hỏng rồi")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        t = b.spawn(boom(), "boom")
        try:
            await t
        except RuntimeError:
            pass
        await asyncio.sleep(0)
    out = buf.getvalue()
    check("lỗi trong tác vụ nền được in ra Logs (kèm tên) và giải phóng", ("boom" in out and "hỏng rồi" in out, t in b._bg_tasks), (True, False))

    async def forever():
        await asyncio.sleep(3600)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        t = b.spawn(forever(), "forever"); await asyncio.sleep(0)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
    check("huỷ task: không in lỗi, được giải phóng", (buf.getvalue(), t in b._bg_tasks), ("", False))
asyncio.run(main())
print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
