"""test_event_pets.py — nhận diện pet sự kiện + dữ liệu /hub. Chạy: python test_event_pets.py"""
import sys, asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock
import event_pets as ep

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# --- nhận diện tên ---
check("tên đầy đủ", ep.match_event_pet("2026november_pumpkinpie"), "2026november_pumpkinpie")
check("không phân biệt hoa thường", ep.match_event_pet("2026November_AutumnHsin"), "2026november_autumnHsin")
check("dạng rút gọn", ep.match_event_pet("pumpkinpie"), "2026november_pumpkinpie")
check("bỏ dấu gạch dưới", ep.match_event_pet("2026novemberautumnhsin"), "2026november_autumnHsin")
check("pet thường không khớp", ep.match_event_pet("dragon"), None)
check("rỗng / None", (ep.match_event_pet(""), ep.match_event_pet(None)), (None, None))
check("tên chỉ chứa 1 phần không khớp", ep.match_event_pet("pie"), None)

animals = [{"name": "bee"}, {"name": "2026november_pumpkinpie", "emoji_id": "123", "emoji_animated": True},
           {"name": "pumpkinpie"}, {"name": "2026november_autumnHsin"}]
got = ep.find_in_animals(animals)
check("tìm trong danh sách thú: không trùng khóa, giữ mục đầu", [(g["key"], g.get("emoji_id")) for g in got],
      [("2026november_pumpkinpie", "123"), ("2026november_autumnHsin", None)])
check("danh sách rỗng", (ep.find_in_animals(None), ep.find_in_animals([])), ([], []))

# --- /hub ---
now = datetime(2026, 11, 22, 10, 0, 0)
p = ep.hub_payload({}, now)
check("chưa thấy con nào: vẫn trả mục để app hiện 'chưa thấy'", (p["active"], p["found_count"], p["total"], [x["found"] for x in p["pets"]]),
      (True, 0, 2, [False, False]))
docs = {"2026november_pumpkinpie": {"found": True, "times_found": 2, "first_found_at": "2026-11-22T08:00:00",
                                    "last_found_at": "2026-11-22T09:30:00", "emoji_id": "55", "emoji_animated": True, "count": 1}}
p = ep.hub_payload(docs, now)
pie = p["pets"][0]
check("đã thấy 1 con", (p["found_count"], pie["found"], pie["times_found"], pie["count"], pie["age_seconds"], pie["emoji_id"]),
      (1, True, 2, 1, 1800, "55"))
check("giờ có hậu tố Z", (pie["first_found_at"], pie["last_found_at"]), ("2026-11-22T08:00:00Z", "2026-11-22T09:30:00Z"))
check("con kia chưa thấy: không có mốc thời gian", (p["pets"][1]["found"], p["pets"][1]["last_found_at"], p["pets"][1]["age_seconds"]),
      (False, None, None))
check("hạn sự kiện", (p["title"], p["ends_epoch"]), ("November", 1795939140))
after = datetime(2026, 12, 1, 0, 0, 0)
check("hết sự kiện, chưa tìm được gì -> ẩn", ep.hub_payload({}, after), None)
p2 = ep.hub_payload(docs, after)
check("hết sự kiện nhưng đã có pet -> vẫn hiện, active=False", (p2["active"], p2["found_count"]), (False, 1))
check("múi giờ có tzinfo cũng đúng", ep.hub_payload({}, datetime(2026, 11, 22, tzinfo=timezone.utc))["active"], True)

# --- Ghi nhận qua bot (DB giả trong bộ nhớ) ---
for m in ["discord", "discord.ext", "discord.ext.commands", "motor", "motor.motor_asyncio", "aiohttp"]:
    if m not in sys.modules:
        try:
            __import__(m)
        except Exception:
            sys.modules[m] = MagicMock()
import owo_tracker_bot as b

class FakeCol:
    def __init__(self): self.docs = {}
    async def find_one(self, q): return dict(self.docs[q["_id"]]) if q["_id"] in self.docs else None
    async def update_one(self, q, upd, upsert=False):
        d = self.docs.get(q["_id"])
        if d is None:
            if not upsert: return
            d = {"_id": q["_id"]}; d.update(upd.get("$setOnInsert", {}))
        d.update(upd.get("$set", {}))
        for k, v in upd.get("$inc", {}).items(): d[k] = d.get(k, 0) + v
        self.docs[q["_id"]] = d
    def find(self, q): 
        outer = self
        class C:
            async def to_list(self, length): return [dict(x) for x in outer.docs.values()]
        return C()

async def main():
    col = FakeCol()
    b.mdb = {b.COL_EVENT_PETS: col}
    firsts = await b.record_event_pets([{"name": "bee"}, {"name": "2026november_pumpkinpie", "emoji_id": "9", "emoji_animated": True}], 1, "hunt")
    check("hunt lần đầu: báo lần đầu", firsts, ["2026november_pumpkinpie"])
    check("hunt lần đầu: ghi found + times_found=1", (col.docs["2026november_pumpkinpie"]["found"], col.docs["2026november_pumpkinpie"]["times_found"]), (True, 1))
    firsts = await b.record_event_pets([{"name": "2026november_pumpkinpie"}], 1, "hunt")
    check("hunt lần 2: không báo lần đầu, times_found=2", (firsts, col.docs["2026november_pumpkinpie"]["times_found"]), ([], 2))
    first_at = col.docs["2026november_pumpkinpie"]["first_found_at"]
    await b.record_event_pets([{"name": "2026november_pumpkinpie", "count": 3}], 1, "zoo")
    d = col.docs["2026november_pumpkinpie"]
    check("zoo: ghi số đang giữ, giữ nguyên lần đầu + last_found_at", (d["count"], d["first_found_at"], "last_found_at" in d), (3, first_at, True))
    await b.record_event_pets([{"name": "2026november_autumnHsin", "count": 7}], 1, "zoo_all")
    e = col.docs["2026november_autumnHsin"]
    check("zoo d: đánh dấu đã tìm thấy nhưng KHÔNG ghi số đang giữ", (e["found"], "count" in e, "last_found_at" in e, e["first_via"]), (True, False, False, "zoo_all"))
    check("không có pet sự kiện: không ghi gì thêm", (await b.record_event_pets([{"name": "dragon"}], 1, "hunt"), len(col.docs)), ([], 2))
    hub = await b._hub_event_pets(datetime(2026, 11, 22))
    check("/hub: cả 2 con đều đã thấy", (hub["found_count"], hub["total"]), (2, 2))

asyncio.run(main())
print("\nTất cả pass" if not fails else f"\n{len(fails)} lỗi: {fails}")
sys.exit(1 if fails else 0)
