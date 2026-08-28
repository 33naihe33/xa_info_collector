"""推送 API：订阅/设置/统计/VAPID 公钥。

供移动端 PWA 的推送设置页使用：
    POST /api/push/subscribe   注册 Web Push 订阅
    GET  /api/push/settings    获取用户推送偏好
    PUT  /api/push/settings    更新用户推送偏好
    GET  /api/push/stats       推送统计（今日数、订阅数）
    GET  /api/push/vapid-key   VAPID 公钥（前端订阅用）
"""
from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from storage.models import PushSubscription, PushSettings, PushLog

router = APIRouter()

# 允许更新的设置字段白名单
_VALID_FIELDS = {
    "instant_enabled", "instant_threshold", "daily_limit", "focus_lines",
    "daily_digest_enabled", "daily_digest_time", "weekly_digest_enabled",
    "digest_threshold", "dnd_enabled", "dnd_start", "dnd_end",
}

_PRIORITY_VALUES = {"critical", "high", "medium", "low"}


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict


# M-03：推送设置严格校验模型
class PushSettingsRequest(BaseModel):
    instant_enabled: bool | None = None
    instant_threshold: Literal["critical", "high", "medium", "low"] | None = None
    daily_limit: int | None = None
    focus_lines: list[str] | None = None
    daily_digest_enabled: bool | None = None
    daily_digest_time: str | None = None
    weekly_digest_enabled: bool | None = None
    digest_threshold: Literal["critical", "high", "medium", "low"] | None = None
    dnd_enabled: bool | None = None
    dnd_start: str | None = None
    dnd_end: str | None = None

    @field_validator("daily_limit")
    @classmethod
    def _valid_daily_limit(cls, v):
        if v is not None and (v < 0 or v > 100):
            raise ValueError("daily_limit 必须在 0-100 之间")
        return v

    @field_validator("daily_digest_time", "dnd_start", "dnd_end")
    @classmethod
    def _valid_hhmm(cls, v):
        if v is None:
            return v
        import re
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError("时间格式必须为 HH:MM")
        return v


@router.post("/push/subscribe")
def subscribe(req: SubscribeRequest):
    """注册 Web Push 订阅（F-20：upsert，重复不创建新行）。"""
    PushSubscription.create(
        channel="web_push", endpoint=req.endpoint, keys=req.keys,
    )
    return {"status": "subscribed"}


@router.delete("/push/subscribe")
def unsubscribe(endpoint: str):
    """F-20：退订（按 endpoint 删除订阅）。"""
    deleted = PushSubscription.delete_by_endpoint(endpoint, user_id="default")
    return {"status": "unsubscribed" if deleted else "not_found"}


@router.get("/push/settings")
def get_settings():
    return PushSettings.get_or_create("default").to_dict()


@router.put("/push/settings")
def update_settings(req: PushSettingsRequest):
    """M-03：用 Pydantic 模型严格校验（原接受任意 dict 导致非法类型入库/500）。"""
    s = PushSettings.get_or_create("default")
    updates = {k: v for k, v in req.model_dump(exclude_none=True).items() if k in _VALID_FIELDS}
    s.update(**updates)
    return PushSettings.get_or_create("default").to_dict()


@router.get("/push/stats")
def push_stats():
    subs = PushSubscription.list_by_user("default")
    today_instant = PushLog.count_today("default", "instant")
    today_scheduled = PushLog.count_today("default", "scheduled")
    return {
        "subscriptions": len(subs),
        "today_count": today_instant + today_scheduled,
        "today_instant": today_instant,
        "today_scheduled": today_scheduled,
    }


@router.get("/push/vapid-key")
def vapid_public_key():
    from notifier.channels.web_push import get_public_key
    return {"public_key": get_public_key()}
