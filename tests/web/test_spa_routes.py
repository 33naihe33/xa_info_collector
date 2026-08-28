"""R-01: SPA 路由回退不应产生 500。

回归用例：原 web/app.py 的 SPAStaticFiles.get_response 捕获了
未导入的 HTTPException，导致任何 SPA 404 触发 NameError → 500。
且 /api 与 /api/... 必须交回 FastAPI 路由，不能回退到 index.html。
"""
import os

import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db

# 生产构建产物必须存在，否则 SPA 测试无意义
DIST = os.path.join(os.path.dirname(__file__), "..", "..", "web", "frontend", "dist")
DIST_EXISTS = os.path.exists(os.path.join(DIST, "index.html"))


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


@pytest.mark.skipif(not DIST_EXISTS, reason="前端 dist 未构建，跳过 SPA 路由测试")
def test_spa_navigation_route_returns_html(client):
    """无扩展名的导航请求 → 200 + index.html（不能 500）。"""
    resp = client.get("/opportunities")
    assert resp.status_code == 200
    assert "<html" in resp.text.lower()
    # 确认返回的是 SPA 入口而非 JSON
    assert "雄安" in resp.text or "<div id=\"app\">" in resp.text


def test_api_unknown_returns_404_not_500(client):
    """/api/未知路由 → 404 JSON（不是 500，也不是 SPA HTML）。"""
    resp = client.get("/api/unknown-endpoint")
    assert resp.status_code == 404
    # FastAPI 默认错误是 JSON，不是 index.html
    assert resp.headers["content-type"].startswith("application/json")


def test_api_exact_path_returns_404_not_html(client):
    """精确路径 /api → 404（不能回退到 SPA HTML）。"""
    resp = client.get("/api")
    assert resp.status_code == 404
    # 不应返回 SPA HTML
    assert "<html" not in resp.text.lower()


def test_spa_route_no_name_error(client):
    """断言不再触发 NameError（回归 R-01 核心缺陷）。

    通过检查任意无扩展名路径不会返回 500 来间接验证。
    """
    if not DIST_EXISTS:
        pytest.skip("前端 dist 未构建")
    for path in ["/opportunities", "/reports", "/leadership", "/mobile"]:
        resp = client.get(path)
        assert resp.status_code != 500, f"{path} 返回 500，可能 NameError 未修复"
