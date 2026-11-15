#!/usr/bin/env python3
"""MCP server cho owo-tracker: bọc API HTTP của bot (cùng API mà app Star Hub dùng).

Biến môi trường:
  OWO_API_URL    địa chỉ https của bot, vd https://bot.example.com   (bắt buộc)
  OWO_API_TOKEN  giống AUTOMACRO_API_TOKEN của bot                    (bắt buộc)
  OWO_READ_ONLY  đặt 1 để TẮT hết tool ghi (chỉ còn tool đọc)        (tuỳ chọn)

Chạy: python owo_tracker_mcp.py   (stdio)
"""
import json
import os
import sys
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

# Hỗ trợ cả SDK v2 (MCPServer) lẫn v1 (FastMCP)
try:
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as _Server
from mcp.types import ToolAnnotations

API_URL = os.environ.get("OWO_API_URL", "").rstrip("/")
API_TOKEN = os.environ.get("OWO_API_TOKEN", "")
READ_ONLY = os.environ.get("OWO_READ_ONLY", "").strip() in ("1", "true", "yes")
MAX_CHARS = 20000
TIMEOUT = 20.0

mcp = _Server("owo_tracker_mcp")


# ---------------------------------------------------------------- hạ tầng

class OwoError(Exception):
    """Lỗi có thông điệp tiếng Việt rõ ràng, hiện thẳng cho người dùng."""


async def _request(method: str, path: str, *, params: Optional[dict] = None,
                   body: Optional[dict] = None) -> Any:
    if not API_URL or not API_TOKEN:
        raise OwoError("Chưa cấu hình: cần đặt biến môi trường OWO_API_URL và OWO_API_TOKEN.")
    if not API_URL.startswith("https://") and not API_URL.startswith("http://localhost") \
            and not API_URL.startswith("http://127.0.0.1"):
        raise OwoError("OWO_API_URL phải là https:// (token sẽ bị lộ nếu dùng http).")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.request(
                method, f"{API_URL}{path}", params=params, json=body,
                headers={"Authorization": f"Bearer {API_TOKEN}"},
            )
    except httpx.TimeoutException:
        raise OwoError("Bot không trả lời kịp (timeout). Kiểm tra bot có đang chạy không.")
    except httpx.HTTPError as e:
        raise OwoError(f"Không kết nối được tới bot ({type(e).__name__}). Kiểm tra OWO_API_URL.")
    if r.status_code == 401:
        raise OwoError("Token sai (401). Kiểm tra OWO_API_TOKEN khớp AUTOMACRO_API_TOKEN của bot. "
                       "Sai nhiều lần bot sẽ khoá IP 5 phút.")
    if r.status_code == 404:
        raise OwoError(f"Bot chưa có đường {path} (404). Có thể bot bản cũ, hãy cập nhật bot.")
    if r.status_code == 400:
        try:
            j = r.json()
            detail = j.get("error", "") + (f" (trường: {j['field']})" if j.get("field") else "")
            if j.get("known") or j.get("tiers"):
                detail += f" — gợi ý: {j.get('known') or j.get('tiers')}"
        except Exception:
            detail = r.text[:200]
        raise OwoError(f"Bot từ chối dữ liệu (400): {detail}")
    if r.status_code >= 400:
        raise OwoError(f"Bot báo lỗi HTTP {r.status_code}.")
    try:
        return r.json()
    except ValueError:
        raise OwoError("Bot trả về dữ liệu không phải JSON.")


def _out(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n... [đã cắt, dài {len(text)} ký tự; hãy lọc theo sections/tier/kind]"
    return text


async def _run(method: str, path: str, **kw) -> str:
    try:
        return _out(await _request(method, path, **kw))
    except OwoError as e:
        return f"Lỗi: {e}"


def read_tool(name: str, title: str):
    return mcp.tool(name=name, annotations=ToolAnnotations(
        title=title, readOnlyHint=True, destructiveHint=False,
        idempotentHint=True, openWorldHint=False))


def write_tool(name: str, title: str, idempotent: bool = True):
    """Tool ghi: bỏ qua hoàn toàn khi OWO_READ_ONLY=1."""
    def deco(fn):
        if READ_ONLY:
            return fn
        return mcp.tool(name=name, annotations=ToolAnnotations(
            title=title, readOnlyHint=False, destructiveHint=False,
            idempotentHint=idempotent, openWorldHint=False))(fn)
    return deco


class _Strict(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# ---------------------------------------------------------------- tool ĐỌC

HubSection = Literal[
    "daily", "cowoncy", "weapon_shards", "event", "event_mode", "slowdown", "gems",
    "huntbot", "quest", "team", "zoo", "inventory", "weapons", "weapon_review",
    "pet_dex", "battle", "new_pets", "channel", "captcha", "checklists",
]
_DEFAULT_SECTIONS = ["daily", "cowoncy", "gems", "huntbot", "quest", "team", "captcha", "event_mode"]


class HubInput(_Strict):
    sections: Optional[list[HubSection]] = Field(
        default=None,
        description="Mục cần lấy. Bỏ trống = bản gọn (daily, cowoncy, gems, huntbot, quest, team, "
                    "captcha, event_mode). Các mục nặng như zoo, inventory, weapons, pet_dex chỉ "
                    "lấy khi nêu rõ. Mục bot chưa thấy lần nào có giá trị null.")


@read_tool("owo_get_hub", "Lấy dữ liệu Hub")
async def owo_get_hub(params: HubInput) -> str:
    """Dữ liệu mới nhất bot đã đọc được từ OwO (như màn Hub của app). Mỗi mục có
    updated_at/age_seconds để biết cũ hay mới. Hub chỉ biết những gì OwO đã in khi
    chủ acc gõ lệnh (vd muốn zoo mới thì phải đã gõ `owo zoo`)."""
    try:
        hub = await _request("GET", "/hub")
    except OwoError as e:
        return f"Lỗi: {e}"
    wanted = params.sections or _DEFAULT_SECTIONS
    picked = {k: hub.get(k) for k in wanted}
    picked["bot_version"] = hub.get("bot_version")
    picked["server_time"] = hub.get("server_time")
    return _out(picked)


@read_tool("owo_get_alerts", "Cảnh báo captcha / huntbot")
async def owo_get_alerts() -> str:
    """Nhẹ: captcha có đang đòi không (kèm số giây từ lúc báo), OwO im lặng bao lâu,
    bot có đang OFF không, huntbot còn bao nhiêu giây. Không thay đổi trạng thái farm."""
    return await _run("GET", "/alerts")   # cố ý KHÔNG gửi ?farm=, vì tham số đó đổi trạng thái theo dõi của bot


class UnlockedInput(_Strict):
    tier: Optional[str] = Field(default=None, description="Lọc 1 bậc hiếm, vd 'rare', 'legendary'. Bỏ trống = tất cả.")


@read_tool("owo_get_unlocked", "Pet đã mở khóa theo bậc")
async def owo_get_unlocked(params: UnlockedInput) -> str:
    """Danh sách pet đã mở khóa, gom theo bậc hiếm (như `,unlocked`)."""
    return await _run("GET", "/unlocked", params={"tier": params.tier} if params.tier else None)


class ZooDiffInput(_Strict):
    kind: Optional[Literal["d", "all", "now", "current"]] = Field(
        default=None, description="'all' | 'current' (d/now là bí danh). Bỏ trống = loại ghi gần nhất.")


@read_tool("owo_get_zoodiff", "So sánh 2 lần ghi zoo")
async def owo_get_zoodiff(params: ZooDiffInput) -> str:
    """So 2 lần ghi zoo gần nhất (như `,zoodiff`). ok=false nghĩa là chưa đủ 2 lần ghi."""
    return await _run("GET", "/zoodiff", params={"kind": params.kind} if params.kind else None)


@read_tool("owo_get_teamcheck", "Kiểm tra đội hình")
async def owo_get_teamcheck() -> str:
    """Đội hình gần nhất bot ghi nhận (như `,teamcheck`); members=0 nghĩa là chưa có."""
    return await _run("GET", "/teamcheck")


@read_tool("owo_get_clean_status", "Tình trạng dọn kho")
async def owo_get_clean_status() -> str:
    """Phiên dọn kho vũ khí tự động: active, tiến độ cursor/total, số bước đang chờ."""
    return await _run("GET", "/clean")


@read_tool("owo_get_gemtier", "Cài đặt tier gem")
async def owo_get_gemtier() -> str:
    """Tier gem được phép dùng và tier ưu tiên cho từng loại (1 Hunting, 2 Empowering, 3 Lucky, 4 Special)."""
    return await _run("GET", "/gemtier")


@read_tool("owo_get_settings", "Công tắc của bot")
async def owo_get_settings() -> str:
    """auto_check, hb_auto, hb_alert, event_mode, app_on, captcha_active."""
    return await _run("GET", "/settings")


@read_tool("owo_list_notes", "Ghi chú")
async def owo_list_notes() -> str:
    """Danh sách ghi chú (như `,note list`)."""
    return await _run("GET", "/notes")


@read_tool("owo_get_alt", "Acc phụ nhận DM")
async def owo_get_alt() -> str:
    """ID acc phụ nhận DM nhắc huntbot (rỗng = tắt)."""
    return await _run("GET", "/alt")


@read_tool("owo_list_pending_commands", "Lệnh đang chờ app")
async def owo_list_pending_commands() -> str:
    """Các lệnh bot đã xếp hàng cho app Star Hub (chỉ xem; MCP này không xác nhận/chạy chúng)."""
    return await _run("GET", "/commands/pending")


# ---------------------------------------------------------------- tool GHI

class SettingInput(_Strict):
    key: Literal["auto_check", "hb_auto", "hb_alert"] = Field(
        ..., description="auto_check = tự chen lệnh check; hb_auto = tự chạy lại huntbot; hb_alert = nhắc huntbot qua DM")
    enabled: bool = Field(..., description="true = bật, false = tắt")


@write_tool("owo_set_setting", "Đổi công tắc bot")
async def owo_set_setting(params: SettingInput) -> str:
    """Bật/tắt 1 công tắc của bot. Trả lại toàn bộ cài đặt mới."""
    return await _run("POST", "/settings", body={"key": params.key, "enabled": params.enabled})


class GemTierInput(_Strict):
    allowed: Optional[dict[str, list[str]]] = Field(
        default=None,
        description='Tier được phép theo loại gem, vd {"1": ["Common","Rare"], "4": []}. '
                    "Danh sách rỗng = tắt hết loại đó. Chỉ các loại nêu trong body mới đổi.")
    pref: Optional[dict[str, str]] = Field(
        default=None,
        description='Ưu tiên khi thay, vd {"1": "highest"}. Giá trị: highest | lowest | tên tier.')


@write_tool("owo_set_gemtier", "Đổi tier gem")
async def owo_set_gemtier(params: GemTierInput) -> str:
    """Đổi tier gem được phép / ưu tiên. Cần ít nhất 1 trong allowed hoặc pref.
    Tier hoặc loại lạ bị từ chối và không đổi gì."""
    body = {k: v for k, v in (("allowed", params.allowed), ("pref", params.pref)) if v is not None}
    if not body:
        return "Lỗi: cần ít nhất 1 trong 'allowed' hoặc 'pref'."
    return await _run("POST", "/gemtier", body=body)


class AddNoteInput(_Strict):
    text: str = Field(..., min_length=1, max_length=500, description="Nội dung ghi chú (tối đa 500 ký tự)")


@write_tool("owo_add_note", "Thêm ghi chú", idempotent=False)
async def owo_add_note(params: AddNoteInput) -> str:
    """Thêm 1 ghi chú (như `,note add`). Gọi lại sẽ thêm bản mới."""
    return await _run("POST", "/notes", body={"action": "add", "text": params.text})


class DoneNoteInput(_Strict):
    id: int = Field(..., ge=1, description="Số thứ tự ghi chú, lấy từ owo_list_notes")


@write_tool("owo_done_note", "Đánh dấu ghi chú xong")
async def owo_done_note(params: DoneNoteInput) -> str:
    """Đánh dấu 1 ghi chú đã xong."""
    return await _run("POST", "/notes", body={"action": "done", "id": params.id})


class ManualPetInput(_Strict):
    name: str = Field(..., min_length=1, max_length=60, description="Tên loài, 1 dòng")
    rank: str = Field(..., pattern=r"^[A-Za-z]{1,20}$", description="Bậc hiếm, chỉ chữ cái, vd 'legendary'")
    hp: int = Field(..., ge=0, le=100000)
    att: int = Field(..., ge=0, le=100000)
    pr: int = Field(..., ge=0, le=100000)
    wp: int = Field(..., ge=0, le=100000)
    mag: int = Field(..., ge=0, le=100000)
    mr: int = Field(..., ge=0, le=100000)


@write_tool("owo_manual_pet", "Nhập tay pet")
async def owo_manual_pet(params: ManualPetInput) -> str:
    """Nhập tay 1 pet (như `,petset`). Nhập lại cùng tên sẽ ghi đè bản cũ."""
    return await _run("POST", "/manual/pet", body=params.model_dump())


class ManualDescInput(_Strict):
    name: str = Field(..., min_length=1, max_length=60, description="Tên, 1 dòng")
    desc: str = Field(..., min_length=1, max_length=1000, description="Mô tả (cho xuống dòng)")


@write_tool("owo_manual_weapontype", "Nhập tay loại vũ khí")
async def owo_manual_weapontype(params: ManualDescInput) -> str:
    """Nhập tay 1 loại vũ khí (như `,weapontypeset`). Ghi đè nếu trùng tên."""
    return await _run("POST", "/manual/weapontype", body=params.model_dump())


@write_tool("owo_manual_passive", "Nhập tay passive")
async def owo_manual_passive(params: ManualDescInput) -> str:
    """Nhập tay 1 passive (như `,passiveset`). Ghi đè nếu trùng tên."""
    return await _run("POST", "/manual/passive", body=params.model_dump())


@write_tool("owo_clear_captcha", "Báo đã giải captcha")
async def owo_clear_captcha() -> str:
    """Báo bot rằng captcha đã giải xong (như `,captcha clear`). CHỈ gọi sau khi
    người dùng xác nhận đã tự giải captcha trong Discord."""
    return await _run("POST", "/captcha/clear")


if __name__ == "__main__":
    if not API_URL or not API_TOKEN:
        print("Thiếu OWO_API_URL / OWO_API_TOKEN (server vẫn chạy, tool sẽ báo lỗi cấu hình).", file=sys.stderr)
    mcp.run()
