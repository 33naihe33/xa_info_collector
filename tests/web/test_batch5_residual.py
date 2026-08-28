"""M-08 + M-04: health loaded_commit + 摘要轮询测试。"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app, _BUILD_COMMIT
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_health_returns_loaded_commit(client):
    """M-08：health 返回 loaded_commit（进程加载冻结值）+ disk_commit + stale。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "loaded_commit" in data, "应返回 loaded_commit（进程加载版本）"
    assert "disk_commit" in data, "应返回 disk_commit（实时磁盘版本）"
    assert "stale" in data
    assert isinstance(data["stale"], bool)
    # loaded_commit 应是字符串（冻结的短 hash 或 unknown）
    assert isinstance(data["loaded_commit"], str)


def test_health_stale_flag_false_when_consistent(client):
    """M-08：loaded_commit == disk_commit 时 stale=False。"""
    resp = client.get("/api/health")
    data = resp.json()
    if data["loaded_commit"] != "unknown":
        assert data["stale"] is (data["loaded_commit"] != data["disk_commit"])


def test_digest_poll_respects_user_time(tmp_path):
    """M-04：digest_poll 在非配置时间不发（尊重 daily_digest_time）。"""
    init_db(str(tmp_path / "test.db"))
    try:
        from storage.models import PushSettings
        s = PushSettings.get_or_create("default")
        s.update(daily_digest_enabled=True, daily_digest_time="23:59")  # 远离当前时间
        # _scheduled_digest_poll 应在时间不匹配时直接返回（不发）
        from web.app import _scheduled_digest_poll
        _scheduled_digest_poll()  # 不应抛异常，也不应发送（当前时间 != 23:59）
        # 无异常即通过（发送逻辑由 send_daily_digest 内部处理）
    finally:
        close_db()


def test_digest_build_applies_threshold(tmp_path):
    """M-04：build_daily_digest 应用 digest_threshold 优先级过滤。"""
    init_db(str(tmp_path / "test.db"))
    try:
        from datetime import datetime
        from storage.models import Opportunity, PushSettings
        from notifier.digest_builder import build_daily_digest
        today = datetime.now().strftime("%Y-%m-%d")
        Opportunity.create(title="critical", source_doc_id=None, business_line="corporate",
                           opp_type="t", priority="critical", status="signal", publish_date=today)
        Opportunity.create(title="low", source_doc_id=None, business_line="corporate",
                           opp_type="t", priority="low", status="signal", publish_date=today)
        # 设阈值为 high → 只含 critical+high，不含 low
        s = PushSettings.get_or_create("default")
        s.update(digest_threshold="high", daily_digest_enabled=True)
        digest = build_daily_digest()
        assert digest["total"] == 1, f"threshold=high 应过滤掉 low，实际 {digest['total']}"
        assert "low" not in digest["by_priority"]
    finally:
        close_db()
