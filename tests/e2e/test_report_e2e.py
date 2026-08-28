"""报告端到端测试：验证前端报告页用到的 API 全流程通畅。"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Opportunity


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    Opportunity.create(
        title="测试商机", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-08",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_report_frontend_contract(client):
    """验证前端报告页用到的 API 都存在且全流程通畅。"""
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "title": "周报", "summary": "概要", "sections": [],
        "recommendations": "", "stats": {"total": 1},
    }
    with patch("web.api.reports.LLMClient", return_value=mock_llm):
        # 生成
        resp = client.post("/api/reports/generate", json={
            "report_type": "weekly", "date_from": "2026-07-04", "date_to": "2026-07-10",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data
        assert "content" in data
        report_id = data["report_id"]

    # 列表
    resp = client.get("/api/reports")
    assert resp.json()["total"] >= 1

    # 详情
    resp = client.get(f"/api/reports/{report_id}")
    assert resp.status_code == 200

    # 导出 Word
    resp = client.get(f"/api/reports/{report_id}/export?format=docx")
    assert resp.status_code == 200
    assert "wordprocessingml.document" in resp.headers.get("content-type", "")
    assert resp.headers.get("content-disposition", "")
