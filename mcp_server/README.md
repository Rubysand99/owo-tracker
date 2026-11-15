# owo_tracker_mcp

MCP server (Python, stdio) để hỏi/điều khiển bot **owo-tracker** ngay trong Claude. Bọc đúng API mà app Star Hub dùng.

## Cài
    pip install -r requirements.txt

## Cấu hình (Claude Desktop → claude_desktop_config.json)
    {
      "mcpServers": {
        "owo-tracker": {
          "command": "python",
          "args": ["/duong/dan/owo_tracker_mcp.py"],
          "env": {
            "OWO_API_URL": "https://bot.example.com",
            "OWO_API_TOKEN": "giống AUTOMACRO_API_TOKEN của bot",
            "OWO_READ_ONLY": "1"
          }
        }
      }
    }
Bỏ dòng `OWO_READ_ONLY` nếu muốn bật các tool ghi (đổi công tắc, tier gem, ghi chú, nhập tay pet/vũ khí/passive, báo đã giải captcha).

## Tool
Đọc: owo_get_hub, owo_get_alerts, owo_get_unlocked, owo_get_zoodiff, owo_get_teamcheck, owo_get_clean_status,
owo_get_gemtier, owo_get_settings, owo_list_notes, owo_get_alt, owo_list_pending_commands
Ghi: owo_set_setting, owo_set_gemtier, owo_add_note, owo_done_note, owo_manual_pet, owo_manual_weapontype,
owo_manual_passive, owo_clear_captcha

Cố ý KHÔNG có: /power, /notify, /commands/*/ack, /weapon-review/* (các đường khiến app gõ lệnh vào Discord).
Token chỉ nằm trong biến môi trường, không bao giờ ghi vào code hay log.
