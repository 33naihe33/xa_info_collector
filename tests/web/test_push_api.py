import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_get_push_settings_default(client):
    resp = client.get("/api/push/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["instant_enabled"] is True
    assert data["instant_threshold"] == "high"


def test_update_push_settings(client):
    resp = client.put("/api/push/settings", json={
        "instant_threshold": "critical",
        "daily_limit": 3,
    })
    assert resp.status_code == 200
    assert resp.json()["instant_threshold"] == "critical"

    # 验证持久化
    resp = client.get("/api/push/settings")
    assert resp.json()["daily_limit"] == 3


def test_subscribe_push(client):
    resp = client.post("/api/push/subscribe", json={
        "endpoint": "https://fcm.googleapis.com/test",
        "keys": {"p256dh": "abc", "auth": "def"},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscribed"


def test_push_stats(client):
    resp = client.get("/api/push/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "today_count" in data
    assert "subscriptions" in data


def test_vapid_public_key(client):
    """前端需要 VAPID 公钥来订阅。"""
    resp = client.get("/api/push/vapid-key")
    assert resp.status_code == 200
    # 可能返回 null（无密钥时），但不应报错
    assert "public_key" in resp.json()
