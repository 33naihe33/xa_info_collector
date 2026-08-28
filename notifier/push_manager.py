"""推送管理器：双触发核心逻辑。

即时预警：pipeline 分析完成后调用 send_instant_alert(opp)
定时摘要：APScheduler 定时调用 send_daily_digest()（见 digest_builder）

防打扰四重检查：阈值 → 去重 → 免打扰时段 → 每日上限。
"""
import logging

from storage.models import PushSettings, PushLog, PushSubscription, Opportunity

logger = logging.getLogger(__name__)


def send_instant_alert(opp: Opportunity, user_id: str = "default") -> dict:
    """评估单条商机是否需要即时推送。

    检查顺序（短路返回）：
        1. 优先级阈值（should_send_instant）
        2. 去重（already_sent）
        3. 免打扰时段（is_dnd_now）
        4. 每日上限（count_today vs daily_limit）
        5. 发送 + 记录 PushLog

    Returns:
        {"sent": bool, "reason": str} reason 为 ok / below_threshold /
        duplicate / dnd / daily_limit。
    """
    settings = PushSettings.get_or_create(user_id)

    # 1. 检查优先级阈值
    if not settings.should_send_instant(opp.priority):
        return {"sent": False, "reason": "below_threshold"}

    # 2. 去重
    if PushLog.already_sent(user_id, opp.id):
        return {"sent": False, "reason": "duplicate"}

    # 3. 免打扰
    if settings.is_dnd_now():
        return {"sent": False, "reason": "dnd"}

    # 4. 每日上限
    today_count = PushLog.count_today(user_id, "instant")
    if settings.daily_limit > 0 and today_count >= settings.daily_limit:
        return {"sent": False, "reason": "daily_limit"}

    # 5. 发送
    title = f"🔴 商机预警：{opp.title[:40]}"
    body = f"[{opp.priority}] {opp.business_line} | "
    if opp.fin_scale:
        body += f"规模:{opp.fin_scale} | "
    if opp.insight:
        body += opp.insight[:60]

    sent = _send_to_user(user_id, title, body, opp.id)
    PushLog.create(
        user_id=user_id, opportunity_id=opp.id,
        trigger_type="instant", channel="web_push",
        title=title, body=body, delivered=sent,
    )
    # A-07: 失败时返回正确 reason（原统一返回 ok 掩盖失败）
    if sent:
        return {"sent": True, "reason": "ok"}
    else:
        subs = PushSubscription.list_by_user(user_id)
        reason = "no_subscription" if not subs else "delivery_failed"
        return {"sent": False, "reason": reason}


def _send_to_user(user_id: str, title: str, body: str,
                  opportunity_id: int | None = None) -> bool:
    """向用户的所有订阅发送推送。任一成功即返回 True。

    无订阅时返回 False（不视为失败，仅记录未送达）。
    """
    subs = PushSubscription.list_by_user(user_id)
    if not subs:
        logger.info(f"No subscriptions for user {user_id}, skipping push")
        return False

    import json
    from notifier.channels.web_push import send_web_push

    any_sent = False
    for sub in subs:
        subscription = {
            "endpoint": sub.endpoint,
            "keys": json.loads(sub.keys) if sub.keys else {},
        }
        payload = {"title": title, "body": body, "url": "/m/opportunities"}
        if send_web_push(subscription, payload):
            any_sent = True
    return any_sent


def retry_failed_pushes(user_id: str = "default", limit: int = 10) -> dict:
    """A-07：重试 delivered=0 的推送（无订阅的不重试）。

    扫描最近 failed 推送记录，对有订阅的用户重试发送。
    返回 {total, retried, succeeded}。
    """
    from storage.database import get_conn
    conn = get_conn()
    # 查 delivered=0 且有 opportunity_id 的推送（可重试内容）
    rows = conn.execute(
        "SELECT pl.id, pl.opportunity_id, pl.title, pl.body, pl.user_id "
        "FROM push_logs pl WHERE pl.delivered = 0 AND pl.opportunity_id IS NOT NULL "
        "ORDER BY pl.sent_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    retried = succeeded = 0
    for r in rows:
        subs = PushSubscription.list_by_user(r["user_id"])
        if not subs:
            continue  # 无订阅，跳过
        sent = _send_to_user(r["user_id"], r["title"], r["body"], r["opportunity_id"])
        retried += 1
        if sent:
            # 更新为已送达
            conn.execute("UPDATE push_logs SET delivered=1 WHERE id=?", (r["id"],))
            conn.commit()
            succeeded += 1
    logger.info(f"retry_failed_pushes: retried={retried}, succeeded={succeeded}")
    return {"total": len(rows), "retried": retried, "succeeded": succeeded}
