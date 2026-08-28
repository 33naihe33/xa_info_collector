"""全链路端到端测试：验证前端用到的每个 API 端点都有正确的后端实现。
确保不出现「前台功能后台未实现」或「前台 icon 无接口」的情况。
"""
import respx
import pytest
from fastapi.testclient import TestClient
from tests.collector.fixtures import SAMPLE_DATASOURCE_JSON, SAMPLE_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    # 禁用调度器，避免后台线程干扰测试
    import web.app as app_module
    app_module._scheduler = "disabled"  # 阻止 _setup_scheduler 启动
    from web.app import create_app
    app = create_app()
    app_module._scheduler = None  # 清除标记
    with TestClient(app) as c:
        yield c
    close_db()


# ---- 信息源状态页用到的全部 API ----

def test_api_get_sources_returns_array(client):
    """前端 SourceStatus.vue 表格数据源：GET /api/collect/sources"""
    resp = client.get("/api/collect/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) >= 1
    portal = [s for s in data["sources"] if s["name"] == "xiongan_portal"][0]
    # 前端表格用到的每个字段都必须存在
    assert "display_name" in portal
    assert "enabled" in portal
    assert "doc_count" in portal
    assert "categories" in portal


def test_api_trigger_collect(client):
    """前端「立即抓取」按钮：POST /api/collect/trigger（mock adapter，不访问网络）"""
    from unittest.mock import patch, MagicMock
    mock_adapter = MagicMock()
    mock_adapter.run.return_value = {"new": 0, "errors": 0}
    with patch("web.api.collect._build_adapter", return_value=mock_adapter):
        resp = client.post("/api/collect/trigger", params={"source": "xiongan_portal"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    mock_adapter.run.assert_called_once()


def test_api_collect_status(client):
    """前端抓取后状态刷新：GET /api/collect/status"""
    resp = client.get("/api/collect/status", params={"source": "xiongan_portal"})
    assert resp.status_code == 200
    assert "last_run" in resp.json()


# ---- 文档列表页用到的全部 API ----

def test_api_documents_list_returns_items_and_total(client):
    """前端 DocumentList.vue：GET /api/documents"""
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_api_documents_filter_and_pagination(client):
    """前端筛选和分页参数。"""
    resp = client.get("/api/documents?source=xiongan_portal&limit=10&offset=0")
    assert resp.status_code == 200


def test_api_document_detail(client):
    """前端文档详情抽屉：GET /api/documents/{id}"""
    # 先插入数据
    from storage.models import Document
    doc = Document.create(
        source="xiongan_portal", doc_type="新闻", title="详情测试",
        url="http://detail-test", publish_date="2026-07-10",
        raw_html="<p>r</p>", text="详情正文", content_hash="detailhash",
    )
    resp = client.get(f"/api/documents/{doc.id}")
    assert resp.status_code == 200
    assert resp.json()["text"] == "详情正文"


def test_api_document_detail_404(client):
    """不存在的文档返回 404。"""
    resp = client.get("/api/documents/99999")
    assert resp.status_code == 404


# ---- 完整业务流程：抓取 → 入库 → 列表展示 ----

@respx.mock
def test_e2e_collect_then_list(client):
    """模拟真实流程：触发抓取 → 文档入库 → 列表 API 能查到。"""
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    # 直接调用 adapter（不走 background task，测试中同步执行）
    from collector.adapters.xiongan_portal import XionganPortalAdapter
    adapter = XionganPortalAdapter()
    adapter.run()

    # 列表 API 能查到
    resp = client.get("/api/documents?source=xiongan_portal")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "张国华调研重点项目"

    # 数据源统计更新
    resp = client.get("/api/collect/sources")
    portal = [s for s in resp.json()["sources"] if s["name"] == "xiongan_portal"][0]
    assert portal["doc_count"] == 1
