"""H-04 + M-03 + M-05: SW注销/推送校验/count_today 修复测试。"""
import os
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, PushLog


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


# ---- H-04: index.html 不再注销 SW ----

def test_index_html_no_sw_unregister():
    """H-04：index.html 不含 getRegistrations/unregister（会注销推送 SW）。"""
    idx_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "web", "frontend", "index.html",
    )
    content = open(idx_path, encoding="utf-8").read()
    assert "getRegistrations" not in content, "index.html 不应含全局 SW 注销逻辑"
    assert "unregister" not in content


# ---- M-03: push settings 校验 ----

def test_push_settings_rejects_bad_daily_limit(client):
    """M-03：daily_limit 非法（字符串）→ 422。"""
    resp = client.put("/api/push/settings", json={"daily_limit": "oops"})
    assert resp.status_code == 422


def test_push_settings_rejects_bad_threshold(client):
    """M-03：instant_threshold 非法（数组）→ 422。"""
    resp = client.put("/api/push/settings", json={"instant_threshold": ["critical"]})
    assert resp.status_code == 422


def test_push_settings_rejects_bad_threshold_value(client):
    """M-03：instant_threshold 非法枚举值 → 422。"""
    resp = client.put("/api/push/settings", json={"instant_threshold": "urgent"})
    assert resp.status_code == 422


def test_push_settings_rejects_bad_time_format(client):
    """M-03：daily_digest_time 格式错 → 422。"""
    resp = client.put("/api/push/settings", json={"daily_digest_time": "9am"})
    assert resp.status_code == 422


def test_push_settings_accepts_valid(client):
    """M-03：合法设置 → 200。"""
    resp = client.put("/api/push/settings", json={"daily_limit": 10, "instant_threshold": "high"})
    assert resp.status_code == 200


# ---- M-03: line-briefs 校验 ----

def test_line_briefs_rejects_bad_date(client):
    """M-03：line-briefs 非法日期 → 422。"""
    resp = client.post("/api/reports/line-briefs", json={"date_from": "bad", "date_to": "2026-07-31"})
    assert resp.status_code == 422


def test_line_briefs_rejects_bad_order(client):
    """M-03：line-briefs date_from > date_to → 422。"""
    resp = client.post("/api/reports/line-briefs", json={"date_from": "2026-07-31", "date_to": "2026-07-01"})
    assert resp.status_code == 422


# ---- M-05: count_today 排除 delivered=0 ----

def test_count_today_excludes_failed(tmp_path):
    """M-05：delivered=0 的推送不计入每日上限。"""
    init_db(str(tmp_path / "test.db"))
    try:
        # 5 条失败 + 1 条成功
        for _ in range(5):
            PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                           title="fail", body="b", delivered=False)
        PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                       title="ok", body="b", delivered=True)
        # count_today 应只统计成功 = 1（原统计全部 = 6）
        assert PushLog.count_today("default", "instant") == 1
    finally:
        close_db()
