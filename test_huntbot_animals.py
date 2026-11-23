"""test_huntbot_animals.py — đọc danh sách thú trong tin huntbot về, nhận pet sự kiện. Chạy: python test_huntbot_animals.py"""
import sys
import owo_parsers as P
import event_pets

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

MSG = """**<:ebot:459996050174902272> |** `BEEP BOOP. I AM BACK WITH 5760 ANIMALS,`
** <:blank:427371936482328596> |** `120000 ESSENCE, AND 136080 EXPERIENCE` 
<:common:416520037713838081> **|** :bee:⁶⁸⁴   :beetle:⁶⁸⁸   :snail:⁶⁶⁵   :bug:⁶⁷⁰   :butterfly:⁷⁰¹   
<:uncommon:416520056269176842> **|** :mouse2:³³⁸   :rooster:³⁶⁷
<:mythic:416520808501084162> **|** :ghost:⁰⁰²   :dragon:⁰⁰¹   
<a:legendary:417955061801680909> **|** <a:gfox:418291892376305664>⁰⁰²   <a:gsquid:417968419984375808>⁰⁰¹"""
r = P.parse_huntbot_animals(MSG)
by = {a["name"]: a for a in r["animals"]}
check("đọc đúng số loài (không lấy emoji rarity/ebot/blank)", len(r["animals"]), 11)
check("số lượng chữ số mũ", (by["bee"]["count"], by["ghost"]["count"], by["gfox"]["count"]), (684, 2, 2))
check("emoji tuỳ chỉnh giữ id + animated", (by["gfox"]["emoji_id"], by["gfox"]["emoji_animated"]), ("418291892376305664", True))
check("không phải tin huntbot về thì None", P.parse_huntbot_animals("You found: :bee:⁶"), None)
check("tin rỗng/None", (P.parse_huntbot_animals(""), P.parse_huntbot_animals(None)), (None, None))
check("tin huntbot không có pet nào", P.parse_huntbot_animals("I AM BACK WITH 0 ANIMALS"), None)

EVMSG = MSG + "\n<:special:1> **|** <:2026november_pumpkinpie:999>¹   :bee:⁰⁰¹"
r2 = P.parse_huntbot_animals(EVMSG)
evs = event_pets.find_in_animals(r2["animals"])
check("nhận ra pet sự kiện trong tin huntbot", [e["key"] for e in evs], ["2026november_pumpkinpie"])
check("tin huntbot thường không có pet sự kiện", event_pets.find_in_animals(r["animals"]), [])
check("tên trùng thì cộng dồn", {a["name"]: a["count"] for a in r2["animals"]}["bee"], 685)
print("\nTất cả pass" if not fails else f"\n{len(fails)} lỗi: {fails}")
sys.exit(1 if fails else 0)
