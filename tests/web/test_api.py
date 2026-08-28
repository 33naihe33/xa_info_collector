import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, Document, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    # 插入测试数据
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试文档A",
        url="http://a", publish_date="2026-07-10",
        raw_html="", text="content-a", content_hash="hash-a",
    )
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试文档B",
        url="http://b", publish_date="2026-07-09",
        raw_html="", text="content-b", content_hash="hash-b",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_list_documents(client):
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    # 按日期降序
    assert data["items"][0]["title"] == "测试文档A"

def test_list_documents_filter_by_source(client):
    resp = client.get("/api/documents?source=xiongan_portal")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

def test_list_documents_pagination(client):
    resp = client.get("/api/documents?limit=1&offset=0")
    assert resp.json()["total"] == 2
    assert len(resp.json()["items"]) == 1

def test_get_document_detail(client):
    doc = Document.list()[0]
    resp = client.get(f"/api/documents/{doc.id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == doc.title
    assert resp.json()["text"] == doc.text


def test_collect_sources_status(client):
    resp = client.get("/api/collect/sources")
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    portal = [s for s in sources if s["name"] == "xiongan_portal"][0]
    assert portal["enabled"] is True
    assert portal["doc_count"] == 2
    assert "zxyw" in portal["categories"]

def test_collect_status_no_runs(client):
    resp = client.get("/api/collect/status?source=xiongan_portal")
    assert resp.status_code == 200
    assert resp.json()["last_run"] is None

