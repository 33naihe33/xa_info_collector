import pytest
from storage.models import init_db, close_db, PushSubscription, PushSettings, PushLog


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_create_subscription():
    sub = PushSubscription.create(user_id="default", channel="web_push",
                                   endpoint="https://fcm.googleapis.com/xxx",
                                   keys='{"p256dh":"abc","auth":"def"}')
    assert sub.id is not None
    assert sub.user_id == "default"


def test_get_settings_default():
    """无设置时返回默认值。"""
    settings = PushSettings.get_or_create("default")
    assert settings.user_id == "default"
    assert settings.instant_enabled is True
    assert settings.instant_threshold == "high"


def test_update_settings():
    settings = PushSettings.get_or_create("default")
    settings.update(instant_threshold="critical", daily_digest_enabled=False)
    fetched = PushSettings.get_or_create("default")
    assert fetched.instant_threshold == "critical"
    assert fetched.daily_digest_enabled is False


def test_create_push_log():
    log = PushLog.create(user_id="default", trigger_type="instant",
                         channel="web_push", title="测试推送", body="内容")
    assert log.id is not None
    assert log.delivered is False


def test_push_log_count_today():
    # M-05：count_today 只统计 delivered=1
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                   title="a", body="a", delivered=True)
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                   title="b", body="b", delivered=True)
    count = PushLog.count_today("default", "instant")
    assert count == 2
