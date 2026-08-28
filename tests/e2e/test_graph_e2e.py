"""关系图谱端到端测试：验证前端用到的图谱 API 字段完整。"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Entity, Relation


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    org = Entity.create(name="测试机构", entity_type="机构")
    person = Entity.create(name="测试人物", entity_type="人物")
    Relation.create(from_entity_id=person.id, to_entity_id=org.id,
                    relation_type="调研", publish_date="2026-07-10")
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_graph_api_frontend_contract(client):
    """验证前端 GraphView.vue 用到的每个 API 字段都存在。"""
    resp = client.get("/api/graph")
    data = resp.json()
    # nodes 字段
    for node in data["nodes"]:
        assert "id" in node
        assert "name" in node
        assert "category" in node
        assert "symbolSize" in node
    # edges 字段
    for edge in data["edges"]:
        assert "source" in edge
        assert "target" in edge
    # 顶层字段
    assert "categories" in data
    assert "total_nodes" in data
    assert "total_edges" in data
