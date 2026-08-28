# tests/analyzer/test_relation_idempotent.py
"""F-28: 关系幂等 + 实体来源测试。"""
import pytest
from storage.models import init_db, close_db, Entity, Relation, get_conn


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_relation_no_duplicate():
    """同一 (from, to, type, source_doc) 不应创建重复记录。"""
    e1 = Entity.create(name="机构A", entity_type="机构")
    e2 = Entity.create(name="项目B", entity_type="项目")

    r1 = Relation.create(from_entity_id=e1.id, to_entity_id=e2.id,
                         relation_type="投资", source_doc_id=1, publish_date="2026-07-22")
    r2 = Relation.create(from_entity_id=e1.id, to_entity_id=e2.id,
                         relation_type="投资", source_doc_id=1, publish_date="2026-07-22")

    assert r1 is not None
    assert r2 is not None
    assert r1.id == r2.id, "Duplicate relation should return same record (upsert)"

    # 数据库中只有1条
    all_relations = Relation.list()
    assert len(all_relations) == 1


def test_relation_publish_date_populated():
    """关系应记录 publish_date。"""
    e1 = Entity.create(name="机构C", entity_type="机构")
    e2 = Entity.create(name="项目D", entity_type="项目")
    Relation.create(from_entity_id=e1.id, to_entity_id=e2.id,
                    relation_type="合作", source_doc_id=2, publish_date="2026-08-01")

    rels = Relation.list()
    assert len(rels) == 1
    assert rels[0].publish_date == "2026-08-01", "publish_date should be populated"


def test_entity_add_source_doc():
    """实体应记录来源文档ID。"""
    e = Entity.create(name="测试实体", entity_type="机构")
    Entity.add_source_doc(e.id, 42)
    Entity.add_source_doc(e.id, 99)
    Entity.add_source_doc(e.id, 42)  # 重复不应追加

    conn = get_conn()
    row = conn.execute("SELECT source_doc_ids FROM entities WHERE id = ?", (e.id,)).fetchone()
    import json
    doc_ids = json.loads(row["source_doc_ids"])
    assert doc_ids == [42, 99], f"Expected [42, 99], got {doc_ids}"
