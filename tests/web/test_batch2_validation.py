"""F-21 + F-15 + F-06: 报告 total/校验 + 推送去重测试。"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Report, PushLog


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def _make_report(report_type="monthly", period_start="2026-07-01", period_end="2026-07-31"):
    return Report.create(
        report_type=report_type, period_start=period_start, period_end=period_end,
        content="{}", opportunity_ids="[]",
    )


def test_report_list_total_is_true_count(client):
    """F-21：list_reports 的 total 应是真实总数，非页长度。"""
    for _ in range(25):
        _make_report()
    resp = client.get("/api/reports?limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 25, f"total 应为真实总数 25，实际 {data['total']}"
    assert len(data["items"]) == 20  # 当前页 20 条


def test_report_count_method(tmp_path):
    """F-21：Report.count() 存在且正确。"""
    init_db(str(tmp_path / "test.db"))
    try:
        assert Report.count() == 0
        _make_report()
        _make_report()
        assert Report.count() == 2
    finally:
        close_db()


def test_generate_report_rejects_invalid_date_order(client):
    """F-15：date_from > date_to → 422。"""
    resp = client.post("/api/reports/generate", json={
        "report_type": "monthly",
        "date_from": "2026-07-31",
        "date_to": "2026-07-01",  # 反序
    })
    assert resp.status_code == 422


def test_generate_report_rejects_invalid_report_type(client):
    """F-15：无效 report_type → 422。"""
    resp = client.post("/api/reports/generate", json={
        "report_type": "quarterly",  # 不在枚举内
        "date_from": "2026-07-01",
        "date_to": "2026-07-31",
    })
    assert resp.status_code == 422


def test_generate_report_rejects_bad_date_format(client):
    """F-15：日期格式错 → 422。"""
    resp = client.post("/api/reports/generate", json={
        "report_type": "monthly",
        "date_from": "07/01/2026",  # 非 YYYY-MM-DD
        "date_to": "2026-07-31",
    })
    assert resp.status_code == 422


def test_already_sent_ignores_failed_push(tmp_path):
    """F-06：delivered=0 的推送不阻断补发。"""
    init_db(str(tmp_path / "test.db"))
    try:
        # 记录一条失败推送
        PushLog.create(
            user_id="default", opportunity_id=42, trigger_type="instant",
            channel="web_push", title="t", body="b", delivered=False,
        )
        # already_sent 应返回 False（可补发）
        assert PushLog.already_sent("default", opportunity_id=42) is False
        # 记录一条成功推送
        PushLog.create(
            user_id="default", opportunity_id=43, trigger_type="instant",
            channel="web_push", title="t", body="b", delivered=True,
        )
        assert PushLog.already_sent("default", opportunity_id=43) is True
    finally:
        close_db()
