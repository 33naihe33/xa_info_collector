"""分析层端到端测试：mock LLM，验证 pipeline → DB → API → 前端契约完整。"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Document, Opportunity


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_analyze_pipeline_to_api(client):
    """完整流程：插入文档 → mock分析 → 商机API能查到。"""
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="央企落户雄安",
        url="http://t1", publish_date="2026-07-10",
        raw_html="", text="中国星网集团总部正式落户雄安新区，投资50亿",
        content_hash="e2e1",
    )

    # Mock LLM（R-04：leadership 现为必要任务，需第 3 次调用返回非调研）
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [{"name": "中国星网集团", "type": "机构"}], "relations": []},
        {
            "is_opportunity": True, "business_line": "corporate",
            "opp_type": "央企入驻", "fin_scale": "50亿",
            "fin_products": ["对公开户", "综合授信"],
            "target_client": "中国星网集团",
            "insight": "央企总部迁入带来全方位金融需求",
            "action_suggest": "机构业务部对接",
            "priority": "critical",
            "trigger_event": "央企落户",
        },
        {"is_leadership_visit": False},  # 非领导调研 → succeeded(None)
    ]

    # NOTE: pipeline.py never imports LLMClient (it's injected via llm_client=),
    # so we use create=True to make the otherwise-redundant patch harmless.
    with patch("analyzer.pipeline.LLMClient", return_value=mock_llm, create=True):
        from analyzer.pipeline import analyze_pending
        stats = analyze_pending(llm_client=mock_llm)

    assert stats["analyzed"] == 1
    assert stats["opportunities"] == 1

    # API 能查到
    resp = client.get("/api/opportunities")
    assert resp.json()["total"] == 1
    opp = resp.json()["items"][0]
    assert opp["business_line"] == "corporate"
    assert opp["priority"] == "critical"
    assert "对公开户" in opp["fin_products"]

    # 统计 API
    resp = client.get("/api/opportunities/stats")
    assert resp.json()["by_line"]["corporate"] == 1

    # 详情 API
    resp = client.get(f"/api/opportunities/{opp['id']}")
    assert resp.json()["insight"] == "央企总部迁入带来全方位金融需求"


def test_frontend_opportunity_api_contract(client):
    """验证前端商机页用到的每个 API 字段都存在。"""
    from storage.models import Opportunity
    Opportunity.create(
        title="测试商机", source_doc_id=None, business_line="inclusive",
        opp_type="sme_tech", fin_scale="5亿",
        fin_products='["科创贷"]', target_client="某科技企业",
        insight="解读", action_suggest="行动",
        priority="medium", status="signal", publish_date="2026-07-10",
    )

    # GET /api/opportunities
    resp = client.get("/api/opportunities")
    item = resp.json()["items"][0]
    for field in ["id", "title", "business_line", "opp_type", "fin_scale",
                  "fin_products", "priority", "status", "publish_date", "insight"]:
        assert field in item, f"Missing field: {field}"

    # GET /api/opportunities/stats
    resp = client.get("/api/opportunities/stats")
    assert "by_line" in resp.json()
    assert "total" in resp.json()

    # GET /api/opportunities/{id}
    resp = client.get(f"/api/opportunities/{item['id']}")
    detail = resp.json()
    for field in ["action_suggest", "target_client", "fin_products"]:
        assert field in detail
