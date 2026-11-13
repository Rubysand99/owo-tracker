"""test_parser_robust.py — hàm parse_* không được ném ngoại lệ với tin lạ / hỏng (một tin hỏng không được làm bỏ dở xử lý cả tin).
Chạy: python test_parser_robust.py   (không cần thư viện ngoài)"""
import glob, json, os, random, re, sys
import owo_parsers as P

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong đợi:", want); print("   thực tế :", got); fails.append(label)

# ---- 1) Lỗi đã gặp: regex số quá lỏng bắt trúng mỗi dấu câu -> int("") / float("...") ném ValueError ----
def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa
        return f"{type(e).__name__}: {e}"

r = safe(P.parse_huntbot_status, "**HUNTBOT**\nI AM BACK WITH YOUR LOOT, ANIMALS CAPTURED")
check("dấu phẩy đứng trước ANIMALS CAPTURED: không lỗi, không đoán số", isinstance(r, dict) and r["animals_captured"] is None, True)
r = safe(P.parse_huntbot_status, "HUNTBOT: STILL HUNTING...% DONE")
check("dấu chấm đứng trước % DONE: không lỗi, không đoán phần trăm", isinstance(r, dict) and r["progress_pct"] is None, True)
r = safe(P.parse_huntbot_status, "HUNTBOT 1.2.3% DONE")
check("số thập phân kép 1.2.3%: không lỗi, không đọc nhầm thành 2.3", isinstance(r, dict) and r["progress_pct"] is None, True)
r = safe(P.parse_daily, "Here is your daily, cowoncy! Wow, daily streak!")
check("daily: dấu phẩy lẻ loi không làm lỗi", isinstance(r, dict) and r["reward"] is None and r["streak"] is None, True)

# ---- 2) Dữ liệu hợp lệ vẫn đọc đúng như trước ----
r = P.parse_huntbot_status("**HUNTBOT is currently hunting!** 63.5% DONE\n1,234 ANIMALS CAPTURED\nBEEP BOOP. I WILL BE BACK IN 2H 5M")
check("huntbot hợp lệ: phần trăm / số pet / giờ về", (r["progress_pct"], r["animals_captured"], r["hunting"]), (63.5, 1234, True))
r = P.parse_huntbot_status("HUNTBOT 100% DONE, 7 ANIMALS CAPTURED")
check("huntbot: 100% và số nhỏ", (r["progress_pct"], r["animals_captured"]), (100.0, 7))
r = P.parse_daily("Here is your daily <:cowoncy:123> 5,000 Cowoncy!\nYou're on a 1,337 daily streak!\nYour next daily is in: 23H 29M 17S")
check("daily hợp lệ: thưởng, streak, giờ nhận kế", (r["reward"], r["streak"], r["seconds_until_next"]), (5000, 1337, 23 * 3600 + 29 * 60 + 17))

# ---- 3) Fuzz nhỏ, cố định hạt giống: mọi parse_* chịu được tin bị cắt / sửa số / đảo dòng ----
here = os.path.dirname(os.path.abspath(__file__))
seeds = set()
def walk(o):
    if isinstance(o, str):
        if 12 <= len(o) <= 3000: seeds.add(o)
    elif isinstance(o, dict):
        for v in o.values(): walk(v)
    elif isinstance(o, list):
        for v in o: walk(v)
for f in sorted(glob.glob(os.path.join(here, "fixtures_*.json"))):
    with open(f, encoding="utf-8") as fh: walk(json.load(fh))
seeds |= {"**HUNTBOT is currently hunting!** 63.5% DONE\n1,234 ANIMALS CAPTURED\nI WILL BE BACK IN 2H 5M",
          "Here is your daily <:cowoncy:123> 5,000 Cowoncy!\nYou're on a 1,337 daily streak!"}
seeds = sorted(seeds)
WEIRD = ["", " ", "\n\n", "0", "-1", "9" * 40, "0/0", "[0/0]", "\x00", "💀" * 20, "<a:x:99999999999999999999>", "¹²³⁴⁵⁶⁷⁸⁹⁰" * 3, ",", ".", "...%", ", ANIMALS CAPTURED"]
rnd = random.Random(20261113)
def mutate(s):
    k = rnd.randrange(7)
    if k == 0: return s[:rnd.randrange(len(s) + 1)]
    if k == 1:
        i = rnd.randrange(len(s)); return s[:i] + s[i + rnd.randrange(1, 12):]
    if k == 2: return re.sub(r"\d+", lambda m: rnd.choice(["0", "-1", "99999999999999999999", "", "0.5", ","]), s, count=rnd.randrange(1, 4))
    if k == 3:
        L = s.split("\n"); rnd.shuffle(L); return "\n".join(L)
    if k == 4:
        i = rnd.randrange(len(s) + 1); return s[:i] + rnd.choice(WEIRD) + s[i:]
    if k == 5: return (s + "\n") * rnd.randrange(2, 4)
    return s.upper()
inputs = list(seeds) + WEIRD
for _ in range(500):
    s = rnd.choice(seeds)
    for _ in range(rnd.randrange(1, 4)):
        s = mutate(s) if s else rnd.choice(WEIRD)
    inputs.append(s)

FUNCS = {n: getattr(P, n) for n in (
    "parse_owodex", "parse_weapon_detail", "parse_team", "parse_huntbot_status", "parse_quest_items", "parse_quest_status",
    "parse_checklist", "parse_cowoncy", "parse_weapon_shards", "parse_weapon_advice", "parse_weapon_list", "parse_zoo",
    "parse_gem_name", "resolve_gem_slot", "normalize_gem_tier_pref", "decode_allowed_tiers", "parse_inventory",
    "parse_hunt_gem_status", "parse_battle", "parse_hunt_found", "duration_to_seconds", "decode_superscript_number",
    "emoji_to_name", "clean_owner_name", "strip_rarity", "parse_zoo_breakdown")}
errors = {}
def run(name, fn, s):
    try:
        fn(s)
    except Exception as e:  # noqa
        errors.setdefault((name, type(e).__name__, str(e)[:60]), s[:70])
for name, fn in FUNCS.items():
    for s in inputs:
        run(name, fn, s)
for s in inputs:
    run("parse_daily", lambda x: P.parse_daily(x, "daily"), s)
    run("parse_event_hunt", lambda x: P.parse_event_hunt(x, 1), s)
    run("parse_zoo(cont)", lambda x: P.parse_zoo(x, True, "common"), s)
    run("parse_inventory(cont)", lambda x: P.parse_inventory(x, True), s)
for k, v in sorted(errors.items()):
    print("   ❗", k, "| mẫu:", repr(v))
check(f"fuzz {len(inputs)} đầu vào x {len(FUNCS) + 4} hàm: không ngoại lệ nào", sorted(errors), [])

print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
