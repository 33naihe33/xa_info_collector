import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Document, Entity, Relation


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    # 创建测试数据：机构-人物-项目关系网
    org = Entity.create(name="雄安集团", entity_type="机构")
    person = Entity.create(name="张国华", entity_type="人物")
    proj = Entity.create(name="启动区建设", entity_type="项目")
    Relation.create(from_entity_id=person.id, to_entity_id=org.id,
                    relation_type="调研", source_doc_id=None, publish_date="2026-07-10")
    Relation.create(from_entity_id=org.id, to_entity_id=proj.id,
                    relation_type="投资", source_doc_id=None, publish_date="2026-07-10")

    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_graph_returns_nodes_and_edges(client):
    resp = client.get("/api/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 2

def test_node_has_required_fields(client):
    resp = client.get("/api/graph")
    node = resp.json()["nodes"][0]
    assert "id" in node
    assert "name" in node
    assert "category" in node  # entity_type
    assert "symbolSize" in node  # 节点大小

def test_edge_has_required_fields(client):
    resp = client.get("/api/graph")
    edge = resp.json()["edges"][0]
    assert "source" in edge
    assert "target" in edge
    assert "relation_type" in edge

def test_graph_filter_by_entity_type(client):
    """只看机构节点。"""
    resp = client.get("/api/graph?entity_types=机构")
    data = resp.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["name"] == "雄安集团"

def test_graph_limit(client):
    """限制节点数（大数据量时只展示核心节点）。"""
    resp = client.get("/api/graph?limit=2")
    data = resp.json()
    assert len(data["nodes"]) <= 2

def test_graph_categories(client):
    """返回节点类别列表（前端图例用）。"""
    resp = client.get("/api/graph")
    data = resp.json()
    assert "categories" in data
    cat_names = [c["name"] for c in data["categories"]]
    assert "机构" in cat_names
    assert "人物" in cat_names
    assert "项目" in cat_names
