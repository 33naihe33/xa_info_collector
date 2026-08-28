import pytest
from unittest.mock import patch, MagicMock
from storage.models import init_db, close_db, Opportunity, PushSettings, PushLog


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_send_instant_alert_high_priority():
    """高优先级商机应触发即时预警。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="重大项目", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10", insight="解读",
    )

    # 关闭免打扰，避免依赖运行时刻的默认 DND 窗口
    PushSettings.get_or_create("default").update(dnd_enabled=False)

    with patch("notifier.push_manager._send_to_user", return_value=True):
        result = send_instant_alert(opp)
    assert result["sent"] is True


def test_skip_low_priority_instant():
    """低优先级不触发即时预警。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="小商机", source_doc_id=None, business_line="inclusive",
        opp_type="sme_retail", priority="low", status="signal",
        publish_date="2026-07-10",
    )

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "below_threshold" in result["reason"]


def test_skip_dnd_period():
    """免打扰时段不推送。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="紧急", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="critical", status="signal",
        publish_date="2026-07-10",
    )

    settings = PushSettings.get_or_create("default")
    settings.update(dnd_enabled=True, dnd_start="00:00", dnd_end="23:59")

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "dnd" in result["reason"]


def test_skip_daily_limit():
    """超过每日上限不推送。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="商机", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10",
    )

    settings = PushSettings.get_or_create("default")
    settings.update(instant_enabled=True, instant_threshold="high", daily_limit=2, dnd_enabled=False)

    # 模拟已成功推送2条（M-05：count_today 只统计 delivered=1）
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push", title="a", body="a", delivered=True)
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push", title="b", body="b", delivered=True)

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "daily_limit" in result["reason"]


def test_skip_duplicate():
    """同一商机不重复推送。"""
    from notifier.push_manager import send_instant_alert
    from storage.database import get_conn

    opp = Opportunity.create(
        title="商机", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10",
    )

    # F-06：去重只认 delivered=1 的记录，故需标记 delivered=True
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                   title="a", body="a", delivered=True)
    # 直接标记已推送该商机（去重键是 opportunity_id）
    get_conn().execute(
        "UPDATE push_logs SET opportunity_id = ? WHERE id = ?", (opp.id, 1)
    )
    get_conn().commit()

    settings = PushSettings.get_or_create("default")
    settings.update(dnd_enabled=False)

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "duplicate" in result["reason"]


def test_digest_builder():
    """摘要生成器应汇总当日商机。"""
    from datetime import datetime
    from notifier.digest_builder import build_daily_digest

    today = datetime.now().strftime("%Y-%m-%d")

    Opportunity.create(
        title="商机A", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date=today,
    )
    Opportunity.create(
        title="商机B", source_doc_id=None, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date=today,
    )

    digest = build_daily_digest()
    assert digest["total"] == 2
    assert "high" in digest["by_priority"]
    assert len(digest["opportunities"]) == 2
