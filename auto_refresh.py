"""auto_refresh.py — các quyết định THUẦN (không đụng DB/Discord) cho 2 việc:

1. Nhắc huntbot: khi còn <= 10 phút nữa là huntbot về (`huntbot_alert_due`).
2. Chen lệnh check khi app đang farm: dữ liệu nào đã cũ thì nhờ app gõ lệnh để bot đọc lại
   (`pick_check`). owo_tracker_bot.py lo phần lấy dữ liệu và xếp lệnh; file này chỉ trả lời "có/không, lệnh nào".
"""

# ---- Nhắc huntbot -------------------------------------------------------------------------
HB_ALERT_SECONDS = 600       # nhắc khi còn <= 10 phút
HB_ALERT_MIN_LEFT = 60       # còn chưa tới 1 phút thì thôi (nhắc muộn vô nghĩa)
HB_SAME_HUNT_WINDOW = 1800   # giờ về lệch < 30 phút = vẫn là CÙNG 1 chuyến (OwO chỉ báo theo phút nên giờ về dao động)


def huntbot_alert_due(hunting, seconds_left, ready_epoch, last_notified_epoch,
                      alert_seconds=HB_ALERT_SECONDS, min_left=HB_ALERT_MIN_LEFT,
                      same_hunt_window=HB_SAME_HUNT_WINDOW):
    """True nếu NÊN nhắc ngay bây giờ. Mỗi chuyến chỉ nhắc 1 lần (so với giờ về đã nhắc lần trước)."""
    if not hunting or seconds_left is None or ready_epoch is None:
        return False
    if not (min_left < seconds_left <= alert_seconds):
        return False
    if last_notified_epoch is not None and abs(ready_epoch - last_notified_epoch) < same_hunt_window:
        return False
    return True


# ---- Chen lệnh check khi đang farm --------------------------------------------------------
HB_MAX_AGE = 3 * 3600        # huntbot: tối đa 3 giờ không quan sát lại thì check (lấy essence/chỉ số mới)
HB_RETURN_GRACE = 60         # huntbot đã tới hạn bấy nhiêu giây mà chưa quan sát lại -> check (chờ OwO tự báo trước)
AUTO_MIN_GAP = 180           # giữa 2 lệnh check tự động liên tiếp (giây)
RETRY_GAP = 15 * 60          # vừa xin 1 loại mà chưa thấy dữ liệu mới thì chờ bấy nhiêu mới xin lại

# (khóa mục trên Hub, lệnh OwO, tuổi dữ liệu tối đa tính bằng giây) — theo thứ tự ưu tiên
CHECK_PLAN = (
    ("cowoncy", "owo cash", 25 * 60),
    ("inventory", "owo inv", 90 * 60),
    ("quest", "owo quest", 2 * 3600),
    ("weapon_shards", "owo ws", 3 * 3600),
    ("zoo", "owo zoo", 4 * 3600),
)


def huntbot_check_due(now_epoch, hunting, ready_epoch, observed_epoch, max_age=HB_MAX_AGE, grace=HB_RETURN_GRACE):
    """Huntbot cần gõ `owo hb` để đọc lại không?"""
    if observed_epoch is None:
        return True                                   # chưa từng thấy trạng thái nào
    if hunting and ready_epoch is not None and now_epoch >= ready_epoch + grace and observed_epoch < ready_epoch:
        return True                                   # đã tới hạn mà chưa quan sát lại sau đó
    return (now_epoch - observed_epoch) > max_age


def pick_check(now_epoch, hb, ages, last_auto_epoch, last_requested, plan=CHECK_PLAN,
               min_gap=AUTO_MIN_GAP, retry_gap=RETRY_GAP):
    """Chọn TỐI ĐA 1 lệnh để chen vào. Trả (khóa, lệnh) hoặc None.

    hb: {"hunting", "ready_epoch", "observed_epoch"}; ages: {khóa: tuổi dữ liệu (giây) hoặc None = chưa có};
    last_auto_epoch: lần gần nhất đã xin 1 lệnh check; last_requested: {khóa: lần gần nhất xin riêng khóa đó}.
    """
    if last_auto_epoch and now_epoch - last_auto_epoch < min_gap:
        return None

    def can_retry(key):
        t = last_requested.get(key)
        return t is None or now_epoch - t >= retry_gap

    if can_retry("huntbot") and huntbot_check_due(
            now_epoch, hb.get("hunting"), hb.get("ready_epoch"), hb.get("observed_epoch")):
        return ("huntbot", "owo hb")
    for key, command, max_age in plan:
        age = ages.get(key)
        if (age is None or age > max_age) and can_retry(key):
            return (key, command)
    return None
