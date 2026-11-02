"""test_gemtier.py — chọn tier gem riêng cho từng loại (lệnh ,gemtier) khi bot nhờ app thay gem hết độ bền.
Chạy: python test_gemtier.py"""
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

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# ---------- hàm thuần ----------
check("loại gem: hunting/1", (b.resolve_gem_slot("Hunting"), b.resolve_gem_slot("1")), ("1", "1"))
check("loại gem: empowering/3", (b.resolve_gem_slot("empowering"), b.resolve_gem_slot("3")), ("3", "3"))
check("loại gem: lucky/4", (b.resolve_gem_slot("LUCKY"), b.resolve_gem_slot("4")), ("4", "4"))
check("loại gem: special/sao/đặc biệt -> star",
      (b.resolve_gem_slot("special"), b.resolve_gem_slot("sao"), b.resolve_gem_slot("đặc biệt")), ("star", "star", "star"))
check("loại gem: không biết -> None", b.resolve_gem_slot("xyz"), None)
check("tier: tên đầy đủ + chữ cái đầu + alias",
      [b.normalize_gem_tier_pref(x) for x in ("rare", "R", "Mythic", "legendary", "f", "Epic")],
      ["Rare", "Rare", "Mythical", "Legendary", "Fabled", "Epic"])
check("tier: cao/thấp tiếng Việt có dấu",
      [b.normalize_gem_tier_pref(x) for x in ("cao", "Cao nhất", "thấp", "Thấp nhất")], ["highest", "highest", "lowest", "lowest"])
check("tier: không hiểu -> None", (b.normalize_gem_tier_pref("xyz"), b.normalize_gem_tier_pref("")), (None, None))

def opt(tier, rank, count=1):
    return {"gem_tier": tier, "gem_tier_rank": rank, "count": count}
stock = [opt("Common", 1), opt("Rare", 3), opt("Epic", 4), opt("Legendary", 6)]
tier_of = lambda o: o and o["gem_tier"]
P = b.pick_gem_option
check("chọn: highest", tier_of(P(stock, "highest")), "Legendary")
check("chọn: lowest", tier_of(P(stock, "lowest")), "Common")
check("chọn: đúng tier còn viên", tier_of(P(stock, "Rare")), "Rare")
check("chọn: tier hết -> tier gần nhất THẤP hơn (Uncommon -> Common)", tier_of(P(stock, "Uncommon")), "Common")
check("chọn: tier hết -> thấp hơn gần nhất (Mythical -> Epic)", tier_of(P(stock, "Mythical")), "Epic")
check("chọn: chỉ còn tier cao hơn -> lấy cao hơn gần nhất", tier_of(P([opt("Rare", 3), opt("Epic", 4)], "Common")), "Rare")
check("chọn: kho rỗng -> None", P([], "Rare"), None)
check("chọn: giá trị lạ -> như highest", tier_of(P(stock, "???")), "Legendary")


async def scenarios():
    said = []
    async def send(text=None, **kw): said.append(text or "")
    ctx = NS(send=send)

    def fresh(name):
        b.mdb = AsyncMongoMockClient()[name]
        b.gem_missing_streak.clear()
        b._app_off_cache.update({"v": None, "at": 0})
        said.clear()

    # ----- lệnh ,gemtier -----
    fresh("gemtier_cmd")
    check("mặc định: tier cao nhất cho cả 4 loại", [await b.get_gem_tier_pref(s) for s in ("1", "3", "4", "star")], ["highest"] * 4)
    await b.gemtier_cmd(ctx, "hunting", "rare")
    check("đặt hunting = Rare", await b.get_gem_tier_pref("1"), "Rare")
    check("đặt hunting không đụng loại khác", [await b.get_gem_tier_pref(s) for s in ("3", "4", "star")], ["highest"] * 3)
    check("trả lời có tên tier + giải thích khi hết", ("Rare" in said[-1], "thấp hơn" in said[-1]), (True, True))
    await b.gemtier_cmd(ctx, "lucky", "thấp", "nhất")
    check("đặt lucky = thấp nhất (có dấu cách)", await b.get_gem_tier_pref("4"), "lowest")
    await b.gemtier_cmd(ctx, "all", "epic")
    check("all epic -> cả 4 loại = Epic", [await b.get_gem_tier_pref(s) for s in ("1", "3", "4", "star")], ["Epic"] * 4)
    await b.gemtier_cmd(ctx, "hunting", "reset")
    check("reset 1 loại -> về mặc định, loại khác giữ nguyên",
          [await b.get_gem_tier_pref(s) for s in ("1", "3")], ["highest", "Epic"])
    await b.gemtier_cmd(ctx, "reset")
    check("reset không kèm loại -> về mặc định cả 4", [await b.get_gem_tier_pref(s) for s in ("1", "3", "4", "star")], ["highest"] * 4)
    said.clear()
    await b.gemtier_cmd(ctx, "xyz", "rare")
    check("loại gem lạ -> hướng dẫn, không đổi gì", ("chưa hiểu" in said[-1], await b.get_gem_tier_pref("1")), (True, "highest"))
    said.clear()
    await b.gemtier_cmd(ctx, "hunting", "tierlalam")
    check("tier lạ -> báo không hiểu, không đổi gì", ("Không hiểu tier" in said[-1], await b.get_gem_tier_pref("1")), (True, "highest"))
    said.clear()
    await b.gemtier_cmd(ctx, "hunting")
    check("thiếu tier -> hướng dẫn", "chưa hiểu" in said[-1], True)
    said.clear()
    await b.mdb[b.COL_INVENTORY].insert_one({"_id": "051", "is_gem": True, "gem_slot": "1", "count": 3,
                                              "gem_tier": "Common", "gem_tier_rank": 1})
    await b.gemtier_cmd(ctx)
    check("xem: có đủ 4 loại và kho gem", all(x in said[-1] for x in ("Hunting", "Empowering", "Lucky", "Special", "Common ×3")), True)

    # ----- đầu-cuối: bot chọn viên theo tier đã đặt -----
    async def run_swap(db_name, pref_cmd):
        fresh(db_name)
        await b.mdb[b.COL_INVENTORY].insert_many([
            {"_id": "051", "is_gem": True, "gem_slot": "1", "count": 3, "gem_tier": "Common", "gem_tier_rank": 1},
            {"_id": "053", "is_gem": True, "gem_slot": "1", "count": 2, "gem_tier": "Rare", "gem_tier_rank": 3},
            {"_id": "054", "is_gem": True, "gem_slot": "1", "count": 1, "gem_tier": "Epic", "gem_tier_rank": 4}])
        if pref_cmd:
            await b.gemtier_cmd(ctx, *pref_cmd)
        msg = NS(channel=NS(send=send, id=1))
        await b.remind_gem_replacements(msg, {"1"}, "555")
        cmds = [c async for c in b.mdb[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending"})]
        return [c["params"]["command_text"] for c in cmds]

    check("thay gem: chưa đặt -> tier cao nhất (Epic 054)", await run_swap("sw_default", None), ["owo use 054"])
    check("thay gem: hunting = Rare -> đúng viên Rare 053", await run_swap("sw_rare", ("hunting", "rare")), ["owo use 053"])
    check("thay gem: hunting = thấp nhất -> Common 051", await run_swap("sw_low", ("hunting", "thap")), ["owo use 051"])
    check("thay gem: hunting = Uncommon (hết) -> Common 051 (thấp hơn gần nhất)",
          await run_swap("sw_unc", ("hunting", "uncommon")), ["owo use 051"])
    check("thay gem: hunting = Legendary (hết) -> Epic 054 (thấp hơn gần nhất)",
          await run_swap("sw_leg", ("hunting", "legendary")), ["owo use 054"])
    check("thay gem: đặt cho loại KHÁC (lucky) không ảnh hưởng hunting", await run_swap("sw_other", ("lucky", "common")), ["owo use 054"])

    # ----- bật / tắt tier được phép dùng -----
    fresh("gem_allow")
    check("mặc định: mọi tier đều được phép (None)", await b.get_gem_allowed("4"), None)
    await b.gemtier_cmd(ctx, "tat", "lucky", "common", "uncommon")
    check("tắt Common+Uncommon cho lucky", sorted(await b.get_gem_allowed("4")), sorted(set(b.GEM_TIERS) - {"Common", "Uncommon"}))
    check("tắt lucky không đụng loại khác", await b.get_gem_allowed("1"), None)
    check("trả lời nêu tier đã tắt + trạng thái ✅/⛔", ("TẮT" in said[-1], "⛔Common" in said[-1], "✅Rare" in said[-1]), (True, True, True))
    await b.gemtier_cmd(ctx, "bat", "lucky", "common")
    check("bật lại Common cho lucky", "Common" in await b.get_gem_allowed("4") and "Uncommon" not in await b.get_gem_allowed("4"), True)
    await b.gemtier_cmd(ctx, "tat", "all", "mythical,legendary")
    check("tắt cho cả 4 loại (nhiều tier bằng dấu phẩy)",
          [("Mythical" in (await b.get_gem_allowed(s)), "Legendary" in (await b.get_gem_allowed(s))) for s in ("1", "3", "4", "star")], [(False, False)] * 4)
    await b.gemtier_cmd(ctx, "bat", "hunting", "all")
    check("bật 'all' tier cho hunting -> về mặc định (None)", await b.get_gem_allowed("1"), None)
    await b.gemtier_cmd(ctx, "tat", "special", "all")
    check("tắt hết tier -> tập rỗng + cảnh báo", (await b.get_gem_allowed("star"), "HẾT" in said[-1]), (set(), True))
    said.clear()
    await b.gemtier_cmd(ctx, "tat", "lucky", "tierlalam")
    check("tier lạ -> báo không hiểu", ("Không hiểu tier" in said[-1], "tierlalam" in said[-1]), (True, True))
    said.clear()
    await b.gemtier_cmd(ctx, "tat", "lucky")
    check("thiếu tier -> hướng dẫn", "Thiếu" in said[-1], True)
    await b.gemtier_cmd(ctx, "reset")
    check("reset đưa tier được phép về mặc định cả 4 loại", [await b.get_gem_allowed(s) for s in ("1", "3", "4", "star")], [None] * 4)
    said.clear()
    await b.mdb[b.COL_INVENTORY].insert_one({"_id": "051", "is_gem": True, "gem_slot": "1", "count": 3,
                                              "gem_tier": "Common", "gem_tier_rank": 1})
    await b.gemtier_cmd(ctx, "tat", "hunting", "uncommon")
    await b.gemtier_cmd(ctx)
    check("xem: hiện ⛔Uncommon của hunting", "⛔Uncommon" in said[-1], True)

    # ----- đầu-cuối: tier bị tắt thì KHÔNG được chọn -----
    async def run_allow(db_name, setup):
        fresh(db_name)
        await b.mdb[b.COL_INVENTORY].insert_many([
            {"_id": "051", "is_gem": True, "gem_slot": "1", "count": 3, "gem_tier": "Common", "gem_tier_rank": 1},
            {"_id": "053", "is_gem": True, "gem_slot": "1", "count": 2, "gem_tier": "Rare", "gem_tier_rank": 3},
            {"_id": "054", "is_gem": True, "gem_slot": "1", "count": 1, "gem_tier": "Epic", "gem_tier_rank": 4}])
        for args in setup:
            await b.gemtier_cmd(ctx, *args)
        said.clear()
        msg = NS(channel=NS(send=send, id=1))
        await b.remind_gem_replacements(msg, {"1"}, "555")
        cmds = [c async for c in b.mdb[b.COL_AUTOMACRO_COMMANDS].find({"status": "pending"})]
        return [c["params"]["command_text"] for c in cmds]

    check("tắt Epic -> mặc định (cao nhất) rơi xuống Rare 053", await run_allow("al_epic", [("tat", "hunting", "epic")]), ["owo use 053"])
    check("tắt Epic+Rare -> còn Common 051", await run_allow("al_er", [("tat", "hunting", "epic", "rare")]), ["owo use 051"])
    check("ưu tiên Epic nhưng Epic bị tắt -> lấy tier thấp hơn gần nhất được phép (Rare)",
          await run_allow("al_pref", [("hunting", "epic"), ("tat", "hunting", "epic")]), ["owo use 053"])
    check("chỉ bật Common -> dùng Common", await run_allow("al_only", [("tat", "hunting", "all"), ("bat", "hunting", "common")]), ["owo use 051"])
    out = await run_allow("al_none", [("tat", "hunting", "all")])
    check("tắt hết -> KHÔNG tạo lệnh thay gem", out, [])
    check("tắt hết -> có báo trong kênh là các tier đang TẮT", any("đang TẮT" in (t or "") for t in said), True)
    check("tắt tier của loại khác (lucky) không ảnh hưởng hunting", await run_allow("al_other", [("tat", "lucky", "all")]), ["owo use 054"])

    # ----- API cho app: GET/POST /gemtier -----
    import json as _json
    old_token, b.AUTOMACRO_API_TOKEN = b.AUTOMACRO_API_TOKEN, "t" * 30
    try:
        def req(body=None, token="t" * 30, bad_json=False):
            async def j():
                if bad_json: raise ValueError("no json")
                return body
            return NS(headers={"Authorization": f"Bearer {token}"}, json=j, remote="1.2.3.4")
        fresh("gem_api")
        await b.mdb[b.COL_INVENTORY].insert_one({"_id": "051", "is_gem": True, "gem_slot": "1", "count": 3,
                                                  "gem_tier": "Common", "gem_tier_rank": 1})
        r = await b.handle_get_gemtier(req(token="sai"))
        check("GET /gemtier: sai token -> 401", r.status, 401)
        r = await b.handle_get_gemtier(req())
        data = _json.loads(r.text)
        check("GET /gemtier: 200 + 4 loại + 7 tier", (r.status, [s["slot"] for s in data["slots"]], len(data["tiers"])),
              (200, ["1", "3", "4", "star"], 7))
        check("GET /gemtier: mặc định bật hết + có kho", (len(data["slots"][0]["allowed"]), data["slots"][0]["stock"]),
              (7, [{"tier": "Common", "count": 3}]))
        r = await b.handle_post_gemtier(req({"allowed": {"4": ["Rare", "Epic"], "1": []}}, token="sai"))
        check("POST /gemtier: sai token -> 401", r.status, 401)
        r = await b.handle_post_gemtier(req({"allowed": {"4": ["Rare", "Epic"], "1": []}}))
        data = _json.loads(r.text)
        by = {s["slot"]: s["allowed"] for s in data["slots"]}
        check("POST /gemtier: lưu lucky=[Rare,Epic], hunting=[] (tắt hết)", (r.status, by["4"], by["1"]), (200, ["Rare", "Epic"], []))
        check("POST /gemtier: loại không nằm trong body giữ nguyên", by["3"], list(b.GEM_TIERS))
        check("POST /gemtier: khớp với lệnh Discord (get_gem_allowed)", (await b.get_gem_allowed("4"), await b.get_gem_allowed("1")),
              ({"Rare", "Epic"}, set()))
        r = await b.handle_post_gemtier(req({"allowed": {"3": ["Common"], "4": ["Zzz"]}}))
        check("POST /gemtier: tier lạ -> 400 và KHÔNG đổi gì (kể cả loại hợp lệ đứng trước)",
              (r.status, await b.get_gem_allowed("3")), (400, None))
        r = await b.handle_post_gemtier(req({"allowed": {"9": ["Common"]}}))
        check("POST /gemtier: loại lạ -> 400", r.status, 400)
        r = await b.handle_post_gemtier(req(bad_json=True))
        check("POST /gemtier: không có body -> 400", r.status, 400)
        r = await b.handle_post_gemtier(req({"allowed": {}}))
        check("POST /gemtier: allowed rỗng -> 400", r.status, 400)
    finally:
        b.AUTOMACRO_API_TOKEN = old_token

asyncio.run(scenarios())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("✅ Test chọn tier gem pass.")
