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
    def find(s, f=None): return Cur([d for d in s.docs.values() if _match(d, f or {})])
    async def find_one(s, f): return next((dict(d) for d in s.docs.values() if _match(d, f)), None)
    async def count_documents(s, f): return len([d for d in s.docs.values() if _match(d, f)])
    async def delete_one(s, f): s.docs.pop(f["_id"], None)
    async def delete_many(s, f): s.docs.clear()
    async def update_one(s, f, u, upsert=False):
        d = s.docs.get(f["_id"])
        if d is None:
            if not upsert: return
            d = s.docs[f["_id"]] = {"_id": f["_id"]}
        for k, v in u.get("$set", {}).items(): _setpath(d, k, v)
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

asyncio.run(go())
if fails:
    print("\n❌ %d bài lỗi" % len(fails)); sys.exit(1)
print("\n✅ Toàn bộ test weapon_review pass.")
