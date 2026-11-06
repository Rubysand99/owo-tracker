"""test_neon_feed.py — luu tin NeonUtil: phan loai, tach 'Nhan: gia tri', loc tin cua nguoi khac. Chay: python3 -W ignore test_neon_feed.py"""
import sys, os
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import neon_feed as nf

fails = []
def check(label, got, want):
    ok = got == want
    print(("✅ " if ok else "❌ ") + label)
    if not ok:
        print("   mong doi:", want); print("   thuc te :", got); fails.append(label)

# --- slug / classify
check("slug bo ID trong ngoac, so, emoji", nf.slug("## <:w:1> Ruby's Bow ( ABCD1 ) 42"), "ruby-s-bow")
check("slug rong", nf.slug("123 456"), "")
check("classify theo dong dau", nf.classify("**Zoo Stats** for <@123>\nfoo"), "other:zoo-stats-for")
check("classify nhan duoc tu parser", nf.classify("bat ky", "weapon_breakdown"), "weapon_breakdown")
check("classify tin rong", nf.classify(""), "other")

# --- fields
TXT = "## Pet Value\n**Total:** 12,345\nOwner: Ruby\n> Rarity : Epic\nkhong co cap\nTotal: 999\n"
f = nf.extract_fields(TXT)
check("fields: Total (giu gia tri dau)", f.get("Total"), "12,345")
check("fields: Owner", f.get("Owner"), "Ruby")
check("fields: Rarity co khoang trang truoc ':'", f.get("Rarity"), "Epic")
check("fields: dong khong co ':' bi bo", "khong co cap" in f, False)

# --- build_doc
d = nf.build_doc("x" * 7000, kind="k", message_id=5, channel_id=6, command="owo zoo", at_iso="2026-11-07T00:00:00Z")
check("doc: cat raw + danh dau", (len(d["raw"]), d["raw_truncated"]), (nf.RAW_MAX, True))
check("doc: id dang chuoi", (d["message_id"], d["channel_id"], d["edited"]), ("5", "6", False))

# --- belongs_to_other
def msg(ref_author=None, inter_user=None, attr="interaction_metadata"):
    m = NS(reference=NS(resolved=NS(author=NS(id=ref_author))) if ref_author is not None else None)
    if inter_user is not None:
        setattr(m, attr, NS(user=NS(id=inter_user)))
    return m
check("khong co thong tin -> luu", nf.belongs_to_other(msg(), 1), False)
check("chua biet ai la nguoi theo doi -> luu", nf.belongs_to_other(msg(ref_author=2), None), False)
check("reply tin cua nguoi khac -> bo", nf.belongs_to_other(msg(ref_author=2), 1), True)
check("reply tin cua minh -> luu", nf.belongs_to_other(msg(ref_author=1), "1"), False)
check("slash cua nguoi khac -> bo", nf.belongs_to_other(msg(inter_user=2), 1), True)
check("slash cua minh -> luu", nf.belongs_to_other(msg(inter_user=1), 1), False)
check("interaction (ban cu) cua nguoi khac -> bo", nf.belongs_to_other(msg(inter_user=2, attr="interaction"), 1), True)

# --- summary
check("summary rong", "Chưa lưu" in nf.summary_text([], 0), True)
s = nf.summary_text([{"_id": "weapon_breakdown", "n": 3, "last": "2026-11-07T01:02:03Z"}], 3)
check("summary co loai + so tin", ("`weapon_breakdown` ×3" in s and "3 tin" in s), True)

print("\nTAT CA DAT" if not fails else f"\nLOI: {len(fails)}")
sys.exit(1 if fails else 0)
