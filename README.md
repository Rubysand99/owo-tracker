# OwO Tracker Bot

Một bot Discord duy nhất làm mọi việc — theo dõi tài khoản chơi OwO,
lưu vào MongoDB dùng chung với các dự án khác của bạn, và trả lời qua
chính lệnh Discord. Không web, không GitHub Pages, không app riêng.

> Muốn tạo/cập nhật repo GitHub hoặc chạy thẳng bot ngay trên điện
> thoại qua Termux, không cần máy tính? Xem `TERMUX.md`.

**Không có dữ liệu game nào ghi sẵn trong file.** Toàn bộ thông tin về
pet/loại vũ khí/passive đều do bot tự bắt được lúc chơi (`owo dex`/`odex`,
`owo weapon`), hoặc do bạn gõ lệnh nhập tay trực tiếp. Bot ghi nhận
**mọi** pet/vũ khí/passive quan sát được — không lọc theo độ hiếm hay
sức mạnh.

## Cài đặt

```bash
pip install discord.py motor
```

## Chạy

```bash
export DISCORD_TOKEN="token_bot_cua_ban"
export OWNER_ID="discord_id_cua_ban"        # chỉ ID này đổi được tracked user
export MONGODB_URI="mongodb+srv://..."       # connection string dùng chung
export MONGODB_DB_NAME="owo_tracker"         # tên database riêng, mặc định "owo_tracker"

python owo_tracker_bot.py
```

`MONGODB_DB_NAME` mặc định là **database riêng** trong cùng cluster —
không đụng tới collection của các dự án khác dù dùng chung
`MONGODB_URI`. Muốn dùng chung hẳn 1 database cũng được, vì mọi
collection của bot này đều có tiền tố `owot_` để tránh trùng tên.

Mời bot vào (các) server bạn chơi OwO — **phải mời thủ công vào từng
server**, bot không thể tự "theo dõi mọi nơi" (xem phần Giới hạn).

### Prefix OwO của bạn — BẮT BUỘC kiểm tra nếu bạn dùng prefix rút gọn

OwO cho phép mỗi người tự đặt prefix riêng (vd `o` thay vì `owo`). Bot
mặc định chỉ nhận diện `owo` — nếu bạn gõ tắt kiểu `Oh` (=`o`+`h`) mà
chưa cấu hình, bot **sẽ không thấy được**, `,gems`/`,zoo`/... sẽ luôn
báo rỗng dù bạn chơi bình thường. Kiểm tra và sửa:

```
,setprefixes          → xem đang nhận diện prefix nào
,setprefixes owo,o    → thêm "o" vào danh sách (chỉ owner dùng được)
```

## Cấu trúc file

- `owo_tracker_bot.py` — bot Discord, lệnh, lưu MongoDB, API cho AutoMacro.
- `owo_parsers.py` — các hàm **thuần** đọc/phân tích tin nhắn OwO (`parse_*`, regex, hằng số đi kèm). Không đụng DB hay Discord nên test được trực tiếp. `owo_tracker_bot.py` import lại các tên này nên `b.parse_xxx` trong test vẫn chạy.
- `weapon_cleanup.py`, `weapon_rules.json` — luật dọn vũ khí.
- `test_*.py` — test (dữ liệu mẫu thật nằm trong `fixtures_*.json`).

## Chạy test

```bash
pip install -r requirements-dev.txt
for t in test_*.py; do python "$t" || break; done
```

Mỗi lần push lên `main` (hoặc mở pull request), GitHub Actions tự chạy lại toàn bộ test (`.github/workflows/tests.yml`).

## Kết nối với AutoMacro (tự động thay gem)

Bot có thể ghi "lệnh cần làm" vào MongoDB để app Android **AutoMacro**
đọc và tự thực hiện trên điện thoại — bắt đầu với case thay gem: khi
phát hiện 1 gem hết độ bền (như trước giờ vẫn nhắc qua Discord), bot
**đồng thời** ghi 1 lệnh `swap_gem` vào hàng đợi, tự chọn viên tier
thấp nhất còn lại trong kho.

**Bật tính năng này:** đặt thêm biến môi trường

```bash
export AUTOMACRO_API_TOKEN="1-chuoi-bi-mat-tu-dat-cang-dai-cang-tot"
export AUTOMACRO_API_PORT="8080"   # tuỳ chọn, Railway tự đặt PORT nên thường không cần
```

**Không đặt `AUTOMACRO_API_TOKEN` thì API này KHÔNG chạy** — mặc định
an toàn, không mở cổng ra ngoài nếu chưa cấu hình. Token này KHÁC với
`MONGODB_URI` — điện thoại chỉ cần biết token (thu hồi được bất cứ lúc
nào bằng cách đổi biến môi trường), không bao giờ cầm chuỗi kết nối
MongoDB thật.

Xem lệnh đang chờ / đã xử lý ngay trong Discord: `,automacro` (owner).

### API cho AutoMacro (kỹ thuật, tham khảo khi cấu hình app)

- `GET /commands/pending` — trả về danh sách lệnh đang chờ, dạng JSON.
- `POST /commands/{id}/ack` — báo đã xử lý xong, body `{"status": "done"}`
  hoặc `{"status": "failed"}`.
- `GET /hub` — trả về **toàn bộ dữ liệu mới nhất bot đã đọc được** để
  app AutoMacro hiện thành màn hình Hub: `daily` (giờ nhận kế tiếp, streak),
  `cowoncy`, `gems` (đang trang bị + gem dự
  phòng trong kho), `huntbot` (kèm `ready_at`/`seconds_left` — giờ xong
  tính từ lúc bot thấy tin nhắn), `quest`, `team`, `zoo`,
  `inventory`, `weapons`. Mục nào bot chưa thấy lần nào thì là `null`.
  Mỗi mục có `updated_at` + `age_seconds` để biết dữ liệu cũ hay mới.
- Cả 3 đều cần header `Authorization: Bearer <AUTOMACRO_API_TOKEN>`,
  thiếu/sai token trả về lỗi 401.

**Hub chỉ biết những gì OwO đã in ra khi bạn gõ lệnh.** Ví dụ muốn có
danh sách pet mới thì gõ `owo zoo`; muốn kho mới thì gõ `owo inventory`;
vũ khí chỉ có những cây bạn từng xem bằng `owo weapon <ID>`.

## Dùng thử

```
,track @Ruby            → đặt tài khoản cần theo dõi (chỉ owner)
,setchannel #kênh       → giới hạn bot CHỈ hoạt động trong 1 kênh (chỉ owner)
,rawdump                → gửi file nguyên văn tin OwO + kết quả bot đọc (chỉ owner)
,status                 → tổng quan: đang theo dõi ai, huntbot
,weaponowner            → xem/đặt tên chủ vũ khí được chấp nhận (chỉ owner)
,huntbot                 → trạng thái HuntBot hiện tại
,quests                  → trạng thái quest hôm nay
,team                    → đội hình gần nhất ghi nhận được
,myweapons scythe        → vũ khí BẠN đang sở hữu, tìm theo tên
,ping                     → kiểm tra bot còn sống, độ trễ bao nhiêu ms
,zoo bee                  → xem zoo đã ghi nhận, lọc theo tên
,inv gem                  → xem inventory đã ghi nhận, lọc theo tên
,gems                      → tình trạng độ bền từng slot gem đang trang bị

,note add Bắt gowl       → thêm việc cần làm
,note list / ,note done 1

,pet gowl / ,dex gowl     → tra dex đầy đủ 1 loài (flavor, rank, rarity, sell, sacrifice, alias, chỉ số)
,pets legendary           → tìm pet theo tên/rank đã ghi nhận
,petset gowl legendary 10 1 3 1 2 3   → nhập tay khi không có owodex

,weapontype "culling scythe"          → tra 1 loại vũ khí đã ghi nhận
,weapontypes                          → liệt kê loại vũ khí đã biết
,weapontypeset "poison dagger" "Gây sát thương + Poison DoT xuyên giáp"

,passive sacrifice        → tra 1 passive đã ghi nhận
,passives                 → liệt kê passive đã biết
,passiveset enrage "Tăng sát thương khi HP thấp"

,debugnext                → in raw content/embed của tin OwO tiếp theo (owner)
,help                     → xem lại toàn bộ lệnh
```

## Cách dữ liệu được tích luỹ

- **Pet** (`owot_pet_species`): mỗi lần `owo dex <tên>` (hoặc `odex <tên>`)
  bot upsert theo tên loài — vì base stat của 1 loài là hằng số của
  game, ghi 1 lần là đủ, các lần sau chỉ cập nhật lại `confirmed_at`.
- **Loại vũ khí** (`owot_weapon_types`): mỗi lần `owo weapon <ID>`
  được đọc, bot gộp thêm hiệu ứng cố định quan sát được (vd Mortality
  của Culling Scythe) vào danh sách — không ghi đè, chỉ bổ sung.
- **Vũ khí bạn sở hữu** (`owot_weapon_instances`): từng cây cụ thể
  theo unique ID, quality/passive luôn là bản mới nhất.
- **Kiểm tra chủ vũ khí:** `owo weapon <ID>` xem được cả vũ khí của người
  khác — tiêu đề tin nhắn ghi tên chủ (`## Ruby's Culling Scythe`). Bot chỉ
  ghi (cả cây vũ khí, loại vũ khí lẫn passive) khi tên chủ **khớp tên Discord
  của bạn**. Tên Discord bot tự học mỗi lần bạn gõ lệnh owo (tên hiển thị,
  tên toàn cục, biệt danh trong server, tên đăng nhập; so sánh không phân
  biệt hoa/thường và bỏ qua ký hiệu). Vũ khí sai chủ bị bỏ qua và in 1 dòng
  vào Logs. Nếu OwO ghi chủ bằng một tên khác, thêm bằng
  `,weaponowner Tên1, Tên2`; gõ `,weaponowner` để xem bot đang chấp nhận
  những tên nào và cây vũ khí gần nhất bị bỏ qua; `,weaponowner xoa` để xoá
  các tên thêm tay.
- **Tên pet từ emoji:** OwO hiển thị pet bằng emoji, bot đọc ra dạng
  `<a:slothbot:711772997320441897>` — hàm `emoji_to_name` lấy đúng tên
  (`slothbot`). Đội hình cũng bỏ ID emoji (dãy số ~18 chữ số) trước khi
  đọc HP/WP/ATT/MAG/PR/MR.
- **Gem đang dùng:** OwO bọc `[hiện/tối đa]` trong dấu backtick, ví dụ
  `` <:egem1:...>`[48/75]` `` — regex cho phép dấu backtick này ở cả 2 đầu
  (tuỳ chọn, để phòng khi OwO đổi lại không có backtick).
- **Zoo bị chia 2 tin nhắn — độ trễ RẤT thất thường:** thực tế đo được, tin
  thứ 2 (chứa Zoo Points) có lúc tới sau **1-2 giây**, có lúc sau **gần 2
  tiếng** — không cố định. Vì vậy cửa sổ chờ ghép (`ZOO_PART_WINDOW`) để
  **30 phút**, không phải 60 giây như bản đầu. Bot LUÔN in 1 dòng
  `[tracker][zoo] ...` vào Logs cho mỗi tin liên quan (không cần
  `,debugnext`), cho biết: tin có tiêu đề hay nối tiếp, ghép được bao nhiêu
  pet, đọc được Zoo Points chưa, và nếu bỏ qua thì vì sao. Khi hết 30 phút
  mà tin nối tiếp vẫn chưa tới, phiên chờ tự đóng (xoá khỏi bộ nhớ) để không
  còn báo "tới quá muộn" lặp lại cho mọi tin owo sau đó. Nếu Zoo Points còn
  hiện `?` ngay sau khi gõ lệnh, cứ đợi thêm rồi bấm Làm mới lại — bot sẽ tự
  cập nhật ngay khi tin thứ 2 tới, không cần gõ lại `owo zoo`.
- **Icon thật cho app:** bot ghi nhớ ID của MỌI emoji tuỳ chỉnh từng thấy
  trong bất kỳ tin nhắn OwO nào (`owot_emoji_registry`, hàm
  `remember_emojis`/`resolve_emoji`) — ID emoji là cố định nên chỉ cần học 1
  lần. Trong `/hub`, pet/gem/tier/thành viên đội hình/phần thưởng quest được
  gắn thêm `emoji_id` + `emoji_animated` (app tự ghép thành link CDN của
  Discord để tải ảnh thật) hoặc `emoji` (ký tự Unicode có sẵn, cho các con
  vật OwO hiện bằng emoji chuẩn như `:bee:`, không có ID riêng).
- **Passive** (`owot_passives`): tên + mô tả chính xác, lấy từ đúng
  dòng `__Tên__ - mô tả` trong tin nhắn OwO.

### Pet Dex trong Hub (số liệu gốc từng loài pet)

Ngoài Zoo (số con đang có), hub còn có mục **Pet Dex** — số liệu GỐC của
từng loài (6 chỉ số, độ hiếm, giá bán/hiến tế) lấy từ `owot_pet_species`.
Khác với Zoo, mục này liệt kê **cả loài bạn chưa có**, miễn là bạn từng gõ
`owo dex <tên>` hoặc `odex <tên>` cho loài đó — vì bot không có sẵn danh
sách toàn bộ pet trong game, chỉ biết loài nào bạn đã từng tra. Loài đang
sở hữu xếp lên trước, kèm số lượng hiện có (đối chiếu với Zoo mới nhất);
loài chưa có chỉ hiện số liệu gốc, không có số lượng.

### Kiểm tra bot đọc có đúng không (`,rawdump`)

Bot lưu lại **nguyên văn** tin nhắn OwO mới nhất của từng loại (hunt, inv,
zoo, team, quest, daily, hb, cash, weapon) cùng với **kết quả bot đọc được**
từ tin đó. Gõ `,rawdump` để nhận 1 file `owo_raw.json` qua **tin nhắn riêng**
(không hiện ở kênh chung). Cách dùng:

1. Trong kênh đang theo dõi, gõ lần lượt: `owo hunt`, `owo inv`, `owo zoo`,
   `owo team`, `owo quest`, `owo daily`, `owo hb`, `owo cash`, và
   `owo weapon <ID vũ khí của bạn>`.
2. Gõ `,rawdump`. Bot sẽ liệt kê những loại **chưa thấy** để bạn gõ bù.
3. So từng mục trong file với tin nhắn thật trong game (hoặc gửi file cho
   người sửa bot). Mục `unrecognized` giữ vài tin OwO mà bot **không hiểu gì**
   — nếu 1 lệnh bạn gõ mà chỉ thấy nó nằm ở đây, nghĩa là bot chưa biết đọc
   loại tin đó (hoặc OwO đã đổi cách viết).
4. `,rawdump xoa` để xoá mẫu cũ, bắt đầu lại cho sạch.

Mục `weapon` luôn được ghi mẫu kể cả khi vũ khí không phải của bạn (kèm
`saved: false` để biết bot đã bỏ qua).

### Giới hạn hoạt động vào 1 kênh

Mặc định bot xử lý lệnh `owo` + tin nhắn OwO ở **mọi kênh** nó có mặt. Dùng
`,setchannel #tên-kênh` (hoặc dán thẳng ID kênh) để giới hạn CHỈ 1 kênh duy
nhất — hữu ích nếu bạn chơi OwO ở nhiều server/kênh nhưng chỉ muốn theo dõi
1 chỗ, tránh dữ liệu bị lẫn. Gõ `,setchannel` không kèm gì để xem đang giới
hạn kênh nào; `,setchannel xoa` để bỏ giới hạn. Lệnh của chính bot này
(`,status`, `,zoo`, `,debugnext`...) vẫn dùng được ở mọi kênh, không bị ảnh
hưởng — giới hạn chỉ áp dụng cho việc theo dõi lệnh owo/tin nhắn OwO.

### Zoo, Inventory, và nhắc thay gem tự động

Bot còn đọc thêm 3 loại tin nhắn:

- **`owo zoo`** — lưu toàn bộ bảng đếm pet theo mọi tier + Zoo Points.
  Zoo dài nên OwO chia thành **2 tin nhắn** (hoặc nhiều hơn): tin đầu có
  tiêu đề `'s zoo`, tin sau không có tiêu đề và chứa các tier còn lại +
  Zoo Points. Bot tự ghép các tin liên tiếp trong vòng 30 phút (cùng kênh)
  thành 1 bảng (`handle_zoo_text`). Gõ lại `owo zoo` thì bắt đầu bảng mới,
  không cộng dồn.
  Trong hub, **tổng pet** và số pet từng tier lấy từ **dòng cuối** của bảng
  (`F-3, CP-9, ..., C-439810` → tổng 748,012), vì đó là số liệu đầy đủ. Các
  số nhỏ cạnh từng loài (bee ¹⁹⁰...) vẫn được lưu riêng và có thể không
  khớp với dòng cuối. Nếu dòng cuối thiếu tier nào thì hub quay về cách
  cộng các số nhỏ (`total_source` = `list`).
  Xem lại bằng `,zoo [tìm]`.
- **`owo inventory`** — lưu toàn bộ item (gem, crate, vé, vũ khí thô...).
  Xem lại bằng `,inv [tìm]`.
  **Mỗi lần gõ `owo inv` là một lần chụp mới (v16):** tin 1 (có tiêu đề) và
  tin 2 (không tiêu đề, nếu có) cùng thuộc một snapshot. Sau khi các tin đã tới
  (chờ `INV_PRUNE_GRACE` = 20 giây), món nào KHÔNG có trong lần chụp mới sẽ bị
  xóa — nên gem F, star, box, crate đã hết sẽ không còn nằm lại trong Hub.
  Hai chỗ an toàn: lần chụp đọc được ít hơn `INV_MIN_ITEMS` = 3 món thì coi như
  đọc hỏng và giữ nguyên kho cũ; tin 2 "mồ côi" (bot vừa khởi động lại, không
  biết tin 1) chỉ được ghi thêm, không xóa gì. Dữ liệu `gems.spare_updated_at` /
  `spare_age_seconds` trong `/hub` là giờ cập nhật riêng của gem dự phòng
  (lấy từ `owo inv`), tách khỏi gem đang dùng (lấy từ `owo hunt`).
- **`owo hunt` / `owo autohunt`** — đọc dòng "hunt is empowered by..."
  để biết đang trang bị gem nào, độ bền còn bao nhiêu.

**Cơ chế nhắc thay gem:** OwO có 3 slot gem (1/3/4) + có thể có thêm
loại chỉ dùng được trong sự kiện, mỗi slot nhiều tier (Common → Fabled).
Gem nào **không trang bị sẽ không hiện** trong dòng "empowered by" —
bot dùng chính đặc điểm này để phát hiện: so sánh slot đang thấy ở lần
hunt mới nhất với lần trước đó, **slot nào biến mất là gem vừa hết độ
bền**. Lúc đó bot tự nhắn vào đúng kênh, tag bạn, liệt kê mọi gem cùng
slot còn tồn trong inventory kèm sẵn lệnh:
```
owo use 051
```
Không tự chọn hộ tier nào — liệt kê hết để bạn tự quyết định dùng viên
nào trước.

⚠️ **Về độ chắc chắn của cơ chế phát hiện:** Toàn bộ format 2 tin nhắn
`owo zoo` và `owo inventory` được viết dựa theo đúng nguyên văn bạn
từng gửi qua ảnh chụp màn hình — đã test khớp 100% với y hệt các mẫu
đó (`test_parsers.py`). Riêng dòng "empowered by" trong tin nhắn hunt
mình viết dựa trên trí nhớ về 1 ví dụ cũ hơn, **chưa có mẫu thật để
đối chiếu trong lần này** — độ tin cậy thấp hơn 2 cái kia. Dùng
`,debugnext` ngay trước khi hunt 1 lần để in raw content thật ra
console, so với `parse_hunt_gem_status()` xem có khớp không trước khi
tin tưởng hoàn toàn cơ chế nhắc.

### Daily, Cowoncy, Quest

- **`owo daily`** — đọc cả 2 dạng tin nhắn: "chưa tới giờ" (`You need to
  wait 3H 11M 28S`) và "đã nhận" (thưởng, streak, giờ nhận kế tiếp).
  Dạng "chưa tới giờ" không có chữ "daily" trong tin nhắn nên bot chỉ nhận
  khi lệnh bạn vừa gõ là lệnh daily. Streak/thưởng chỉ có ở tin "đã nhận",
  nên nếu bạn nhận daily lúc bot tắt thì streak trong hub sẽ cũ.
- **`owo money` / `owo cash`** — lưu số cowoncy hiện có.
- **`owo quest`** — bảng Quest Log là loại tin nhắn kiểu mới của Discord
  (Components V2: có các tab Daily/Weekly/Quests), chữ không nằm trong
  `content` hay embed mà nằm trong các thành phần lồng nhau. Bot đã biết
  đọc loại này (`flatten_message`) và lấy được Seals + mốc quest kế tiếp
  + **từng quest** (tên, mô tả, phần thưởng, tiến độ `1/10`). Một quest
  tính là xong khi tiến độ đạt tối đa. Các mẫu tin nhắn thật lấy bằng
  `,debugnext` (in ra Logs của Railway).
- **`owo profile`** — là **ảnh** (thẻ hồ sơ), không có chữ nào để đọc nên
  bot không lấy được dữ liệu từ đây.

### Về việc tự động dịch sang tiếng Việt

Mọi mô tả vũ khí/passive lấy từ OwO đều là tiếng Anh gốc. Bot cố dịch
sang tiếng Việt **theo mẫu câu cố định** (không gọi API dịch ngoài —
tốn phí, phụ thuộc mạng, có thể lỗi âm thầm mà không biết). Hàm
`translate_effect_text()` nhận diện ~8 mẫu câu OwO hay dùng (Deals
X% STR..., Increases your X by Y%..., v.v.) và dịch chính xác theo
mẫu. Câu nào không khớp mẫu nào đã biết thì **giữ nguyên tiếng Anh**
thay vì đoán bừa ra bản dịch sai — bản gốc tiếng Anh luôn được lưu
song song, không bao giờ mất.

Rank pet (`common`, `legendary`...) dịch qua bảng tra cố định
`RANK_VI`, luôn chính xác vì chỉ có đúng 14 giá trị rank trong game.

Flavor text (câu in nghiêng mô tả pet, kiểu đùa/thơ) **không dịch** —
văn phong sáng tạo dịch theo mẫu dễ sai nghĩa hơn là giữ nguyên tiếng
Anh, nên bot chủ động không cố dịch phần này.

### Về việc tách hiệu ứng cố định khỏi passive ngẫu nhiên

1 tin nhắn `owo weapon` có thể chứa NHIỀU dòng dạng `__Tên__ - mô tả`:
vừa hiệu ứng gắn liền với chính loại vũ khí (vd mọi Culling Scythe đều
có Mortality), vừa passive ngẫu nhiên roll được lúc mở (vd Giant
Slayer, Physical Resistance...). Bot lấy **dòng cuối cùng luôn là
passive roll thật**, các dòng trước thuộc về loại vũ khí — quy tắc
này đã kiểm chứng đúng với mọi mẫu tin nhắn thật có trong lúc trò
chuyện trước đó (test trong `test_parsers.py`).

## Cách bot nhận diện đúng dữ liệu của bạn

Discord không cho bot biết trực tiếp "tin nhắn này trả lời cho ai".
Cách bot suy luận:

1. Thấy đúng Discord ID đang `,track` gõ tin nhắn bắt đầu bằng
   `owo` trong 1 kênh → ghi nhớ "đang chờ phản hồi ở kênh này".
2. Tin nhắn tiếp theo từ OwO bot **trong đúng kênh đó**, trong vòng
   20 giây → coi là phản hồi cho bạn, đem đi parse.
3. Nếu nhiều người cùng gõ `owo` liên tục trong cùng 1 kênh cùng lúc,
   có thể bị lẫn — giới hạn của cách tiếp cận này, không có API chính
   thức nào từ OwO bot để biết chắc chắn 100%.

## ⚠️ Đã tự test trước khi giao — nhưng vẫn cần bạn xác nhận lần cuối

`test_parsers.py` test 2 lớp: (1) toàn bộ hàm parse với đúng mẫu tin
nhắn thật từ ảnh chụp màn hình đã gửi, (2) toàn bộ chu trình lưu/đọc
MongoDB (dùng `mongomock-motor` giả lập, cùng interface với `motor`
thật). Chạy `python test_parsers.py` để xem lại — hiện tại toàn bộ
pass, kể cả 3 lỗi từng phát hiện và sửa trong lúc phát triển:

1. Passive luôn ra rỗng vì thiếu `**` markdown sau `__Tên__`.
2. Đội hình bị đảo lộn số liệu vì số trong thanh XP và số ẩn trong ID
   vũ khí (vd `C2PRPT` có chữ `2`) bị lẫn vào HP/WP/ATT/MAG/PR/MR.
3. Cùng 1 loại vũ khí bị lưu thành nhiều bản ghi khác nhau vì tên bị
   dính thêm số lượng kill (`"Culling Scythe [2]"` thay vì
   `"Culling Scythe"`).

Nhưng toàn bộ test đều dùng **text tái tạo từ ảnh chụp màn hình**,
không phải `message.content`/`embed` thật lấy trực tiếp từ Discord —
khả năng cao khớp, nhưng chưa chắc 100% (khoảng trắng, ký tự ẩn, cách
chia field có thể khác đôi chút). Dùng `,debugnext` để in ra console
đúng raw content/embed thật, đối chiếu với các hàm `parse_*` nếu có gì
không khớp.
