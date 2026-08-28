import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Report, Opportunity


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    Opportunity.create(
        title="商机A", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-08",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_list_reports_empty(client):
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_generate_report(client):
    """生成报告应创建 Report 记录并返回内容。"""
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "title": "周报", "summary": "概要",
        "sections": [], "recommendations": "", "stats": {"total": 1},
    }
    with patch("web.api.reports.LLMClient", return_value=mock_llm):
        resp = client.post("/api/reports/generate", json={
            "report_type": "weekly",
            "date_from": "2026-07-04",
            "date_to": "2026-07-10",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "report_id" in data
    assert "content" in data
    assert "金融业务机会" in data["content"]["title"]

    # 列表能查到
    resp = client.get("/api/reports")
    assert resp.json()["total"] == 1


def test_get_report_detail(client):
    report = Report.create(report_type="daily", period_start="2026-07-10",
                           period_end="2026-07-10", content='{"title":"日报"}')
    resp = client.get(f"/api/reports/{report.id}")
    assert resp.status_code == 200
    assert resp.json()["content"]["title"] == "日报"


def test_get_report_404(client):
    resp = client.get("/api/reports/99999")
    assert resp.status_code == 404


def test_export_report_docx(client):
    """导出 Word 文件。"""
    report = Report.create(report_type="weekly", period_start="2026-07-04",
                           period_end="2026-07-10",
                           content='{"title":"周报","summary":"概要","sections":[],"recommendations":"","stats":{"total":1}}')
    resp = client.get(f"/api/reports/{report.id}/export?format=docx")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in resp.headers.get("content-type", "")
