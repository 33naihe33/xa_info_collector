"""定时摘要生成器。

汇总过去 N 小时的商机，按优先级/条线统计，生成早报/周报内容。
由 APScheduler 定时调用（调度器配置见 push_rules.yaml digest_schedule）。
"""
from datetime import datetime, timedelta

from storage.models import Opportunity


def build_daily_digest(user_id: str = "default") -> dict:
    """构建每日摘要内容（汇总过去 24 小时商机）。

    M-04：应用用户 focus_lines + digest_threshold 筛选。
    Returns:
        {date, total, by_priority, by_line, opportunities[<=20]}
    """
    from storage.models import PushSettings
    import json
    settings = PushSettings.get_or_create(user_id)
    # M-04: focus_lines 是 JSON 字符串，解析为列表
    try:
        focus_lines = json.loads(settings.focus_lines) if settings.focus_lines else []
    except (json.JSONDecodeError, TypeError):
        focus_lines = []
    # M-04：digest_threshold 优先级过滤（如 high → 只含 critical+high）
    threshold = settings.digest_threshold if hasattr(settings, "digest_threshold") else None

    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # F-12：SQL 层日期过滤，无 limit 截断
    bl_filter = focus_lines if focus_lines else None
    digest_opps = Opportunity.list_for_period(date_from=yesterday, date_to=today,
                                              business_lines=bl_filter)
    # M-04: digest_threshold 优先级过滤
    if threshold:
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        max_rank = priority_rank.get(threshold, 3)
        digest_opps = [o for o in digest_opps if priority_rank.get(o.priority, 3) <= max_rank]

    by_priority = {}
    by_line = {}
    for o in digest_opps:
        by_priority[o.priority] = by_priority.get(o.priority, 0) + 1
        by_line[o.business_line] = by_line.get(o.business_line, 0) + 1

    return {
        "date": today,
        "total": len(digest_opps),
        "by_priority": by_priority,
        "by_line": by_line,
        "opportunities": [
            {
                "id": o.id,
                "title": o.title,
                "priority": o.priority,
                "business_line": o.business_line,
                "fin_scale": o.fin_scale,
            }
            for o in digest_opps[:20]
        ],
    }


def send_daily_digest(user_id: str = "default"):
    """发送每日摘要推送（定时触发）。

    遵守用户的日报开关与免打扰时段；无商机时不推送。
    """
    from notifier.push_manager import _send_to_user
    from storage.models import PushSettings, PushLog

    settings = PushSettings.get_or_create(user_id)
    if not settings.daily_digest_enabled:
        return {"sent": False, "reason": "disabled"}

    if settings.is_dnd_now():
        return {"sent": False, "reason": "dnd"}

    digest = build_daily_digest(user_id)
    if digest["total"] == 0:
        return {"sent": False, "reason": "no_opportunities"}

    title = f"📊 雄安商机早报：{digest['total']} 条新商机"
    body_parts = []
    for prio in ["critical", "high", "medium"]:
        count = digest["by_priority"].get(prio, 0)
        if count:
            body_parts.append(f"{prio}:{count}")
    body = " | ".join(body_parts) if body_parts else "详见商机列表"

    sent = _send_to_user(user_id, title, body)
    PushLog.create(
        user_id=user_id, trigger_type="scheduled", channel="web_push",
        title=title, body=body, delivered=sent,
    )
    return {"sent": sent, "digest": digest}


def build_weekly_digest(user_id: str = "default") -> dict:
    """构建每周摘要内容（汇总过去 7 天商机）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    digest_opps = Opportunity.list_for_period(date_from=week_ago, date_to=today)

    by_priority = {}
    by_line = {}
    for o in digest_opps:
        by_priority[o.priority] = by_priority.get(o.priority, 0) + 1
        by_line[o.business_line] = by_line.get(o.business_line, 0) + 1

    return {
        "date": today,
        "period_start": week_ago,
        "total": len(digest_opps),
        "by_priority": by_priority,
        "by_line": by_line,
        "opportunities": [
            {
                "title": o.title, "business_line": o.business_line,
                "priority": o.priority, "publish_date": o.publish_date,
            }
            for o in digest_opps[:20]
        ],
    }


def send_weekly_digest(user_id: str = "default"):
    """F-09：发送每周摘要推送（定时触发，每周一）。"""
    from notifier.push_manager import _send_to_user
    from storage.models import PushSettings, PushLog

    settings = PushSettings.get_or_create(user_id)
    if not settings.weekly_digest_enabled:
        return {"sent": False, "reason": "disabled"}

    if settings.is_dnd_now():
        return {"sent": False, "reason": "dnd"}

    digest = build_weekly_digest(user_id)
    if digest["total"] == 0:
        return {"sent": False, "reason": "no_opportunities"}

    title = f"📊 雄安商机周报：本周 {digest['total']} 条商机"
    body_parts = []
    for prio in ["critical", "high", "medium"]:
        count = digest["by_priority"].get(prio, 0)
        if count:
            body_parts.append(f"{prio}:{count}")
    body = " | ".join(body_parts) if body_parts else "详见商机列表"

    sent = _send_to_user(user_id, title, body)
    PushLog.create(
        user_id=user_id, trigger_type="scheduled", channel="web_push",
        title=title, body=body, delivered=sent,
    )
    return {"sent": sent, "digest": digest}
