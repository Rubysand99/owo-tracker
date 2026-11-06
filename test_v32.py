"""test_v32.py — ,weaponreview auto: doc NeonUtil (tin gon + Breakdown) + Knowledge roi tu quyet Giu/Bo. Chay: python test_v32.py"""
import sys, asyncio, time
from datetime import datetime
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

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

notes = []
async def fake_notify(text, *a, **k):
    notes.append(text)
async def fake_raw(*a, **k):
    return None

async def fresh_db():
    b.mdb = AsyncMongoMockClient()["v32_test"]
    b._app_off_cache.update({"v": None, "at": 0})
    notes.clear()

async def set_session(**value):
    await b.mdb[b.COL_CONFIG].update_one({"_id": b.REVIEW_KEY}, {"$set": {"value": value}}, upsert=True)

async def add(id, type, passives, quality=45.0, rarity="rare"):
    await b.mdb[b.COL_WEAPON_LIST].insert_one({"_id": id, "type": type, "passives": passives, "quality": quality,
                                               "rarity": rarity, "starred": False, "equipped": False})

async def queued():
    return [(d["action"], d["params"].get("command_text"), d["params"].get("click_label")) for d in
            await b.mdb[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending"}).sort("_id", 1).to_list(length=50)]

async def decisions():
    return {r["_id"]: (r["decision"], r.get("reason")) for r in await b.mdb[b.COL_WEAPON_REVIEW].find({}).to_list(length=100)}

_mid = [1000]
def msg(content, ch=5, ts=None):
    _mid[0] += 1
    return NS(id=_mid[0], content=content, embeds=[], components=[], channel=NS(id=ch),
              created_at=datetime.fromtimestamp(ts if ts is not None else time.time() + 1))

def bd(wid, tiers):
    lines = [f"## Ruby's Bow ( {wid} )"]
    for i, t in enumerate(tiers):
        lines.append(f"<:s{i}:1> **{100 + i}** (Range: 100-150 — <:{t}:2> 50%)")
    return "\n".join(lines)

COMPACT = "<:rare:1> 40% max | `Worn Bow 80,50 swarm 42`"

async def start(limit=0):
    await set_session(active=True, auto=True, phase="scanning", channel_id=5, msg_id=None, current=None,
                      check_msg_ids=[], history=[], missing=[], auto_limit=limit)

async def scenarios():
    old = (b.notify_owner, b.record_raw)
    b.notify_owner, b.record_raw = fake_notify, fake_raw
    try:
        # ---------- bat dau: cay tot GIU ngay, cay rac vao hang doi ----------
        await fresh_db()
        await start()
        await add("GGGG11", "vban", ["att"], 79.6, "epic")
        await add("RRRR11", "pstaff", ["swarm"])
        await add("RRRR22", "pstaff", ["swarm"])
        await b._auto_begin(0)
        sess = await b.review_get()
        check("begin: cay tot giu ngay", (await decisions()).get("GGGG11", ("",))[0], "keep")
        check("begin: hang doi chi co cay rac", sess["auto_queue"], ["RRRR11", "RRRR22"])
        check("begin: giao lenh cay dau, bam Details", await queued(), [("weapon_detail_check", "owo w RRRR11", "details")])
        check("begin: phase checking", (sess["phase"], sess["current"]), ("checking", "RRRR11"))

        # ---------- doc du lieu -> bo ----------
        await b.auto_feed_detail(msg(""), {"id": "RRRR11", "passive": {"name": "Swarm", "desc": "x"}})
        await b.auto_feed_neon(msg(COMPACT))
        check("chua du breakdown: chua quyet", "RRRR11" in await decisions(), False)
        await b.auto_feed_neon(msg(bd("RRRR11", ["common", "uncommon", "epic"])))
        d = await decisions()
        check("chi so vu khi thap -> bo", d.get("RRRR11"), ("drop", "rac_chi_so_thap"))
        check("tu sang cay ke", (await b.review_get())["current"], "RRRR22")
        check("giao lenh cay ke", (await queued())[-1], ("weapon_detail_check", "owo w RRRR22", "details"))

        # ---------- Mythic o chi so vu khi -> giu ----------
        await b.auto_feed_detail(msg(""), {"id": "RRRR22", "passive": {"name": "Swarm", "desc": "x"}})
        await b.auto_feed_neon(msg(COMPACT))
        await b.auto_feed_neon(msg(bd("RRRR22", ["common", "mythic", "common"])))
        check("co chi so vu khi Mythic -> giu", (await decisions()).get("RRRR22"), ("keep", "chi_so_vu_khi_mythic"))
        check("het hang doi -> ket thuc", ((await b.review_get())["active"], (await b.review_get())["phase"]), (False, "done"))

        # ---------- Knowledge > 14% -> giu ----------
        await fresh_db(); await start()
        await add("RRRR11", "pstaff", ["swarm"])
        await b._auto_begin(0)
        await b.auto_feed_detail(msg(""), {"id": "RRRR11", "passive": {"name": "Knowledge", "desc": "+**15.5%** xp"}})
        await b.auto_feed_neon(msg(COMPACT))
        await b.auto_feed_neon(msg(bd("RRRR11", ["common", "common", "common"])))
        check("Knowledge 15.5% -> giu", (await decisions()).get("RRRR11"), ("keep", "knowledge_15.5%"))

        # ---------- an toan: tin sai cay / cu / kenh khac bi bo ----------
        await fresh_db(); await start()
        await add("RRRR11", "pstaff", ["swarm"])
        await b._auto_begin(0)
        await b.auto_feed_detail(msg(""), {"id": "RRRR11", "passive": {"name": "Swarm", "desc": "x"}})
        await b.auto_feed_neon(msg(COMPACT))
        await b.auto_feed_neon(msg(bd("OTHER99", ["common", "common", "common"])))
        check("Breakdown cua cay khac -> bo qua", "RRRR11" in await decisions(), False)
        await b.auto_feed_neon(msg(bd("RRRR11", ["common", "common", "common"]), ts=time.time() - 600))
        check("tin Neon cu (truoc luc bat dau) -> bo qua", "RRRR11" in await decisions(), False)
        await b.auto_feed_neon(msg(bd("RRRR11", ["common", "common", "common"]), ch=6))
        check("tin Neon o kenh khac -> bo qua", "RRRR11" in await decisions(), False)

        # ---------- thieu du lieu: watchdog -> giu, dem loi, dung sau 3 lan ----------
        await fresh_db(); await start()
        for i in ("RRRR11", "RRRR22", "RRRR33", "RRRR44"):
            await add(i, "pstaff", ["swarm"])
        await b._auto_begin(0)
        for i in ("RRRR11", "RRRR22"):
            await b.auto_try_finish(force=True)
        d = await decisions()
        check("thieu OwO/Neon -> giu (khong bao gio bo khi thieu)", (d["RRRR11"], d["RRRR22"]), (("keep", "thieu_chi_tiet_owo"),) * 2)
        check("2 loi: van chay", (await b.review_get())["active"], True)
        await b.auto_try_finish(force=True)
        check("3 cay lien tiep loi -> dung", ((await b.review_get())["active"], any("dừng" in n for n in notes)), (False, True))
        check("3 cay loi: khong giao them lenh cay thu 4", [q[1] for q in await queued()].count("owo w RRRR44"), 0)

        # ---------- thu N cay ----------
        await fresh_db(); await start(limit=1)
        for i in ("RRRR11", "RRRR22", "RRRR33"):
            await add(i, "pstaff", ["swarm"])
        await b._auto_begin(1)
        check("limit 1: chi 1 cay trong hang doi", (await b.review_get())["auto_queue"], ["RRRR11"])

        # ---------- app bao loi -> bo qua cay do ----------
        await fresh_db(); await start()
        await add("RRRR11", "pstaff", ["swarm"]); await add("RRRR22", "pstaff", ["swarm"])
        await b._auto_begin(0)
        await b._auto_on_failed("RRRR11")
        sess = await b.review_get()
        check("app loi: bo qua cay, sang cay ke, chua quyet cay loi", (sess["current"], sess["auto_skipped"], "RRRR11" in await decisions()),
              ("RRRR22", ["RRRR11"], False))
    finally:
        b.notify_owner, b.record_raw = old

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test v32 pass.")
