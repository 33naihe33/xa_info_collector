import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Opportunity, Document


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="原文",
        url="http://o", publish_date="2026-07-10",
        raw_html="", text="text", content_hash="h1",
    )
    Opportunity.create(
        title="荣乌高速融资", source_doc_id=1, business_line="corporate",
        opp_type="corporate_financing", fin_scale="18亿",
        fin_products='["项目贷","银团"]', priority="high", status="signal",
        publish_date="2026-07-10", insight="基建融资",
        action_suggest="机构部牵头",
    )
    Opportunity.create(
        title="科创企业入驻", source_doc_id=1, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date="2026-07-09", insight="开户需求",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_list_opportunities(client):
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

def test_list_opportunities_filter_by_line(client):
    resp = client.get("/api/opportunities?business_line=corporate")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["title"] == "荣乌高速融资"

def test_list_opportunities_filter_by_priority(client):
    resp = client.get("/api/opportunities?priority=high")
    assert resp.json()["total"] == 1

def test_get_opportunity_detail(client):
    opp = Opportunity.list()[0]
    resp = client.get(f"/api/opportunities/{opp.id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["title"] == "荣乌高速融资"
    assert detail["fin_scale"] == "18亿"
    assert "项目贷" in detail["fin_products"]
    assert detail["insight"] == "基建融资"

def test_get_opportunity_404(client):
    resp = client.get("/api/opportunities/99999")
    assert resp.status_code == 404

def test_opportunity_stats(client):
    """商机统计：按条线汇总。"""
    resp = client.get("/api/opportunities/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert "by_line" in stats
    assert stats["by_line"]["corporate"] == 1
    assert stats["by_line"]["inclusive"] == 1
    assert stats["total"] == 2
