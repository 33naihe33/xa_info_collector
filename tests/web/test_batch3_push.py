"""F-20 + F-09: 订阅唯一性/退订 + 摘要调度注册测试。"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, PushSubscription


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_subscribe_upsert_no_duplicate(client):
    """F-20：重复订阅同一 endpoint 不创建重复行。"""
    # 订阅两次同一 endpoint
    client.post("/api/push/subscribe", json={"endpoint": "https://fcm/abc", "keys": {"p256dh": "x", "auth": "y"}})
    client.post("/api/push/subscribe", json={"endpoint": "https://fcm/abc", "keys": {"p256dh": "x", "auth": "y"}})
    subs = PushSubscription.list_by_user("default")
    assert len(subs) == 1, f"重复订阅应 upsert 为 1 条，实际 {len(subs)}"


def test_unsubscribe_endpoint(client):
    """F-20：退订按 endpoint 删除订阅。"""
    client.post("/api/push/subscribe", json={"endpoint": "https://fcm/xyz", "keys": {"p256dh": "x", "auth": "y"}})
    assert len(PushSubscription.list_by_user("default")) == 1
    # 退订
    resp = client.delete("/api/push/subscribe", params={"endpoint": "https://fcm/xyz"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsubscribed"
    assert len(PushSubscription.list_by_user("default")) == 0


def test_unsubscribe_not_found(client):
    """F-20：退订不存在的 endpoint 返回 not_found。"""
    resp = client.delete("/api/push/subscribe", params={"endpoint": "https://fcm/nonexistent"})
    assert resp.json()["status"] == "not_found"


def test_scheduler_has_digest_jobs(tmp_path):
    """F-09 / M-04：scheduler 注册了摘要相关 job。"""
    from web.app import _setup_scheduler
    sched = _setup_scheduler()
    job_ids = [j.id for j in sched.get_jobs()]
    sched.shutdown(wait=False)
    assert "daily_crawl_analyze" in job_ids
    assert "daily_analyze" in job_ids
    assert "digest_poll" in job_ids  # M-04: 改为轮询
    assert "weekly_digest" in job_ids  # F-09


def test_cors_not_wildcard(client):
    """F-16：CORS 不再是通配 *（默认 loopback）。"""
    # OPTIONS 请求带外部 Origin → 不应回显该 Origin（非允许列表）
    resp = client.options(
        "/api/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # 非允许 origin 的响应不应包含 Access-Control-Allow-Origin 头（或不含 evil 域）
    allow_origin = resp.headers.get("access-control-allow-origin", "")
    assert "evil.example.com" not in allow_origin, "CORS 不应允许任意 origin"
