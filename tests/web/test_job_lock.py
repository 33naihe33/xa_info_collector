"""P1-10: 并发 job 互斥测试。

回归：trigger_collect/trigger_analyze + cron job 可重叠运行，
导致重复 LLM 计费、重复商机、计数丢更新。
"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db
from web.job_lock import _collect_lock, _analyze_lock


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_trigger_collect_returns_409_when_already_running(client):
    """手动触发抓取时若锁已持有 → 409。"""
    # 模拟锁已被持有（如定时任务或前一次手动触发）
    acquired = _collect_lock.acquire(blocking=False)
    assert acquired
    try:
        resp = client.post("/api/collect/trigger", params={"source": "xiongan_portal"})
        assert resp.status_code == 409
        assert "already running" in resp.json()["detail"]
    finally:
        _collect_lock.release()


def test_trigger_analyze_returns_409_when_already_running(client):
    """手动触发分析时若锁已持有 → 409。"""
    acquired = _analyze_lock.acquire(blocking=False)
    assert acquired
    try:
        resp = client.post("/api/analyze/trigger")
        assert resp.status_code == 409
    finally:
        _analyze_lock.release()


def test_collect_and_analyze_locks_are_independent():
    """抓取锁与分析锁互不影响（可并行抓取和分析）。"""
    assert _collect_lock.acquire(blocking=False)
    try:
        # 持有 collect 锁时仍能获取 analyze 锁
        assert _analyze_lock.acquire(blocking=False)
        _analyze_lock.release()
    finally:
        _collect_lock.release()
