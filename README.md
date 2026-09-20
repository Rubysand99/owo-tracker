# OwO Tracker Bot

Một bot Discord duy nhất làm mọi việc — theo dõi tài khoản chơi OwO,
lưu vào MongoDB dùng chung với các dự án khác của bạn, và trả lời qua
chính lệnh Discord. Không web, không GitHub Pages, không app riêng.

> Muốn tạo/cập nhật repo GitHub hoặc chạy thẳng bot ngay trên điện
> thoại qua Termux, không cần máy tính? Xem `TERMUX.md`.

**Không có dữ liệu game nào ghi sẵn trong file.** Toàn bộ thông tin về
pet/loại vũ khí/passive đều do bot tự bắt được lúc chơi (`owo owodex`,
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

## Dùng thử

```
,track @Ruby            → đặt tài khoản cần theo dõi (chỉ owner)
,status                 → tổng quan: đang theo dõi ai, trận gần nhất, huntbot
,battlelog 10            → 10 trận gần nhất
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

- **Pet** (`owot_pet_species`): mỗi lần `owo owodex <tên>` được đọc,
  bot upsert theo tên loài — vì base stat của 1 loài là hằng số của
  game, ghi 1 lần là đủ, các lần sau chỉ cập nhật lại `confirmed_at`.
- **Loại vũ khí** (`owot_weapon_types`): mỗi lần `owo weapon <ID>`
  được đọc, bot gộp thêm hiệu ứng cố định quan sát được (vd Mortality
  của Culling Scythe) vào danh sách — không ghi đè, chỉ bổ sung.
- **Vũ khí bạn sở hữu** (`owot_weapon_instances`): từng cây cụ thể
  theo unique ID, quality/passive luôn là bản mới nhất.
- **Passive** (`owot_passives`): tên + mô tả chính xác, lấy từ đúng
  dòng `__Tên__ - mô tả` trong tin nhắn OwO.

### Zoo, Inventory, và nhắc thay gem tự động

Bot còn đọc thêm 3 loại tin nhắn:

- **`owo zoo`** — lưu toàn bộ bảng đếm pet theo mọi tier + Zoo Points.
  Xem lại bằng `,zoo [tìm]`.
- **`owo inventory`** — lưu toàn bộ item (gem, crate, vé, vũ khí thô...).
  Xem lại bằng `,inv [tìm]`.
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
