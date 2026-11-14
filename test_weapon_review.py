"""test_weapon_review.py — duyệt vũ khí Giữ/Bỏ: hàng đợi, quyết định, xoá tin kiểm tra, undo-ready history.
Dùng Mongo giả trong bộ nhớ (không cần mongomock). Chạy: python test_weapon_review.py"""
import asyncio, sys
from types import SimpleNamespace as NS
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


def _match(doc, f):
    for k, v in f.items():
        if k == "$or":
            if not any(_match(doc, x) for x in v):
                return False
        elif doc.get(k) != v:
            return False
    return True


def _setpath(doc, path, val):
    parts = path.split(".")
    for p in parts[:-1]:
        doc = doc.setdefault(p, {})
    doc[parts[-1]] = val


def _getpath(doc, path, default=None):
    for p in path.split("."):
        if not isinstance(doc, dict) or p not in doc:
            return default
        doc = doc[p]
    return doc


class Cur:
    def __init__(s, rows): s.rows = rows
    async def to_list(s, length=None): return [dict(r) for r in s.rows]


class Col:
    def __init__(s): s.docs = {}
    def find(s, f=None, proj=None): return Cur([d for d in s.docs.values() if _match(d, f or {})])
    async def find_one(s, f): return next((dict(d) for d in s.docs.values() if _match(d, f)), None)
    async def count_documents(s, f): return len([d for d in s.docs.values() if _match(d, f)])
    async def update_many(s, f, u):
        for d in s.docs.values():
            if d.get("status") == f.get("status") and str(d.get("action", "")).startswith("clean_"):
                for k, v in u.get("$set", {}).items(): _setpath(d, k, v)
    async def delete_one(s, f): s.docs.pop(f["_id"], None)
    async def delete_many(s, f): s.docs.clear()
    async def update_one(s, f, u, upsert=False):
        d = s.docs.get(f["_id"])
        if d is None:
            if not upsert: return
            d = s.docs[f["_id"]] = {"_id": f["_id"]}
        for k, v in u.get("$set", {}).items(): _setpath(d, k, v)
        for k, v in u.get("$inc", {}).items(): _setpath(d, k, (_getpath(d, k, 0) or 0) + v)
        for k, v in u.get("$addToSet", {}).items():
            cur = _getpath(d, k, []);  cur = list(cur)
            if v not in cur: cur.append(v)
            _setpath(d, k, cur)
        for k, v in u.get("$push", {}).items():
            cur = list(_getpath(d, k, [])) + list(v["$each"])
            _setpath(d, k, cur[v["$slice"]:] if v.get("$slice", 0) < 0 else cur)


class DB(dict):
    def __missing__(s, k): s[k] = Col(); return s[k]


deleted, edits = [], []
class Partial:
    def __init__(s, mid): s.mid = mid
    async def delete(s): deleted.append(s.mid)
    async def edit(s, **kw): edits.append(s.mid)
class Chan:
    def get_partial_message(s, mid): return Partial(mid)
    async def send(s, **kw): return NS(id=999)
b.bot = NS(get_channel=lambda cid: Chan(), fetch_channel=None)
b.mdb = DB()
b._utcnow = b._utcnow

W = b.mdb[b.COL_WEAPON_LIST]
def add(i, q, starred=False, equipped=False, t="bow"):
    W.docs[i] = {"_id": i, "id": i, "quality": q, "type": t, "starred": starred, "equipped": equipped}
for i, q, st, eq in [("aaaa", 50, False, False), ("bbbb", 90, True, False), ("cccc", 70, False, False),
                     ("dddd", 80, False, True), ("eeee", 60, False, False)]:
    add(i, q, st, eq)

async def go():
    # hàng đợi: bỏ cây có sao (bbbb) và đang trang bị (dddd); chất lượng thấp -> cao
    check("hàng đợi bỏ cây có sao / đang dùng, chất lượng tăng dần", await b.review_pending_ids(), ["aaaa", "eeee", "cccc"])
    check("giữ mặc định = có sao + đang dùng", await b.review_default_keep_ids(), ["bbbb", "dddd"])

    await b.mdb[b.COL_CONFIG].update_one({"_id": b.REVIEW_KEY}, {"$set": {"value": {
        "active": True, "channel_id": 5, "msg_id": 100, "current": "aaaa", "check_msg_ids": [], "history": []}}}, upsert=True)

    # tin của cây đang kiểm tra được nhớ; tin cây khác / kênh khác thì không
    await b.review_note_message(NS(id=11, channel=NS(id=5)), "AAAA")
    await b.review_note_message(NS(id=12, channel=NS(id=5)), "aaaa")
    await b.review_note_message(NS(id=13, channel=NS(id=5)), "zzzz")
    await b.review_note_message(NS(id=14, channel=NS(id=6)), "aaaa")
    await b.review_note_message(NS(id=100, channel=NS(id=5)), "aaaa")   # chính embed danh sách: không được xoá
    check("nhớ đúng tin của cây đang kiểm tra", (await b.review_get())["check_msg_ids"], [11, 12, 100])

    res, err = await b.review_decide("drop")
    check("bấm Bỏ: ghi quyết định + chọn cây kế", (res["decided"], res["decision"], res["next_id"], res["remaining"]), ("aaaa", "drop", "eeee", 2))
    check("xoá tin kiểm tra nhưng chừa embed danh sách", sorted(deleted), [11, 12])
    check("cập nhật embed danh sách", edits, [100])
    s = await b.review_get()
    check("phiên: current mới + dọn danh sách tin + history", (s["current"], s["check_msg_ids"], s["history"]), ("eeee", [], ["aaaa"]))

    res, err = await b.review_decide("keep")
    check("bấm Giữ", (res["decided"], res["next_id"]), ("eeee", "cccc"))
    res, err = await b.review_decide("keep")
    check("cây cuối -> next_id rỗng", (res["next_id"], res["remaining"]), (None, 0))
    res, err = await b.review_decide("keep")
    check("hết cây thì báo lỗi", (res, err), (None, "khong co cay nao dang duyet"))
    res, err = await b.review_decide("xoa")
    check("quyết định lạ bị từ chối", res, None)
    check("danh sách quyết định", await b.review_decisions(), {"aaaa": "drop", "eeee": "keep", "cccc": "keep"})
    hub = await b._hub_weapon_review()
    check("Hub: tóm tắt phiên", (hub["active"], hub["current_id"], hub["remaining"], hub["kept"], hub["dropped"]), (True, None, 0, 2, 1))
    check("ID dài được cắt gọn, ưu tiên cây mới", b._review_ids_text([f"{i:04d}" for i in range(400)]).startswith("… (+"), True)

async def go2():
    # ---- 3 danh sach + chon tay
    b.mdb = DB()
    for i, (t, q) in enumerate([("a", 10), ("b", 20), ("c", 30), ("d", 40)]):
        await b.mdb[b.COL_WEAPON_LIST].update_one({"_id": f"W{i}"}, {"$set": {"type": t, "quality": q}}, upsert=True)
    R = b.mdb[b.COL_WEAPON_REVIEW]
    await R.update_one({"_id": "W0"}, {"$set": {"decision": "keep", "reason": "chi_so_cao"}}, upsert=True)
    await R.update_one({"_id": "W1"}, {"$set": {"decision": "keep", "reason": "bp_la"}}, upsert=True)
    await R.update_one({"_id": "W2"}, {"$set": {"decision": "drop", "reason": "chi_so_thap"}}, upsert=True)
    L = await b.review_lists()
    check("lists: Giữ/Bỏ/Chưa rõ/Chưa xem (bp_la = Chưa rõ, W3 chưa quyết = Chưa xem)",
          (L["keep"], L["drop"], L["unknown"], L["unseen"]), (["W0"], ["W2"], ["W1"], ["W3"]))
    res, err = await b.review_select("zz9")
    check("chọn ID lạ bị từ chối", (res, err), (None, "khong tim thay cay nay"))
    res, err = await b.review_select("w2")
    check("chọn tay W2", (res and res["id"], err), ("W2", None))
    res, err = await b.review_decide("keep")
    check("đổi Bỏ -> Giữ tay, hết hàng đợi", (res["decided"], res["next_id"]), ("W2", None))
    doc = await R.find_one({"_id": "W2"})
    check("giữ nguyên lý do gốc, đánh dấu manual", (doc["decision"], doc["reason"], doc.get("manual")), ("keep", "chi_so_thap", True))
    check("W2 sang danh sách Giữ", (await b.review_lists())["keep"], ["W0", "W2"])
    await b.review_select("W1")
    res, err = await b.review_decide("keep")
    check("quyết tay W1 (bp_la) -> rời Chưa rõ; W3 vẫn Chưa xem", ((await b.review_lists())["unknown"], (await b.review_lists())["unseen"]), ([], ["W3"]))
    await b.review_select("W0")
    await b.review_decide("unknown")
    check("đặt tay Không xác định", "W0" in (await b.review_lists())["unknown"], True)
    cs = await b.clean_session()
    check("kế hoạch dọn kho bị vô hiệu sau khi đổi tay", (cs["active"], cs["steps"]), (False, []))

async def go3():
    await b.review_select("W3")
    await b.review_stop()
    sess = await b.review_get()
    check("Dừng duyệt: tắt phiên, bỏ cây hiện tại", (sess["active"], sess["current"]), (False, None))
    res, err = await b.review_decide("keep")
    check("Dừng rồi thì Giữ/Bỏ báo không có cây", err, "khong co cay nao dang duyet")

async def go4():
    # ---- tu duyet bang dong gon Neon
    b.mdb = DB()
    queued = []
    async def fake_q(action, params): queued.append(params["command_text"]); return 1
    b.queue_automacro_command = fake_q
    async def fake_notify(*a, **k): pass
    b.notify_owner = fake_notify
    async def fake_dc(sess): pass
    b.review_delete_checks = fake_dc
    async def fake_emb(sess=None): pass
    b.review_refresh_embed = fake_emb
    for i, q in (("N1", 50), ("N2", 50), ("N3", 50)):
        await b.mdb[b.COL_WEAPON_LIST].update_one({"_id": i}, {"$set": {"type": "x", "quality": q}}, upsert=True)
    R = b.mdb[b.COL_WEAPON_REVIEW]
    await R.update_one({"_id": "N1"}, {"$set": {"decision": "keep", "reason": "q_thap_chua_chac", "q": 50.0}}, upsert=True)
    await R.update_one({"_id": "N2"}, {"$set": {"decision": "keep", "reason": "bp_la", "q": 50.0}}, upsert=True)
    await R.update_one({"_id": "N3"}, {"$set": {"decision": "unknown", "manual": True}}, upsert=True)
    await b.mdb[b.COL_WEAPON_LIST].update_one({"_id": "N4"}, {"$set": {"type": "x", "quality": 50}}, upsert=True)
    await R.update_one({"_id": "N4"}, {"$set": {"decision": "keep", "reason": "khoa", "q": 50.0}}, upsert=True)
    res, err = await b.autoneon_start()
    check("tự duyệt: hàng đợi = Chưa rõ trừ cây tự đặt '?'", (res, err, queued), ({"ok": True, "queue": 3}, None, ["owo w N1"]))
    res, err = await b.review_decide("keep")
    check("đang tự duyệt thì chặn bấm tay", err, "dang tu duyet, bam Dung truoc khi tu quyet")
    class Msg:
        def __init__(s, text): s.text = text; s.created_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc); s.reference = None
    b.flatten_message = lambda m: m.text
    await b.autoneon_handle_neon(Msg("mythic 89.8% max｜`sstaff 100,91,68 knowledge 98`"))
    doc = await R.find_one({"_id": "N1"})
    check("Neon: Knowledge 98 vào top 6 -> Giữ", (doc["decision"], doc["reason"], doc.get("manual")), ("keep", "knowledge_top", True))
    check("chuyển cây kế + nhờ app gõ", queued, ["owo w N1", "owo w N2"])
    await b.autoneon_handle_neon(Msg("rare 30% max｜`sstaff 10,20,30`"))
    doc = await R.find_one({"_id": "N2"})
    check("Neon: không đủ 2 chỉ số -> Bỏ chắc chắn", (doc["decision"], doc["reason"]), ("drop", "chi_so_thap"))
    await b.autoneon_handle_neon(Msg("rare 20% max｜`sstaff 10,20,30`"))
    d4 = await R.find_one({"_id": "N4"})
    check("cây khóa chưa có bp cũng được xem; chỉ số không đạt -> khoa_khong_dat, vẫn Giữ, lưu bp", (d4["decision"], d4["reason"], d4.get("bp")), ("keep", "khoa_khong_dat", "sstaff 10,20,30"))
    sess = await b.review_get()
    check("hết hàng đợi -> tự tắt", (sess["autoneon"], sess["active"], sess["autoneon_done"], sess["autoneon_changed"]), (False, False, 3, 2))
    check("N1 ra khỏi Chưa rõ; N2 sang Bỏ", ((await b.review_lists())["unknown"], (await b.review_lists())["drop"]), (["N3"], ["N2"]))
    top = await b.get_config(b.KNOWLEDGE_TOP_KEY, [])
    check("top Knowledge cập nhật", top, [{"id": "N1", "v": 98}])

asyncio.run(go())
asyncio.run(go2())
asyncio.run(go3())
asyncio.run(go4())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test weapon_review pass.")
