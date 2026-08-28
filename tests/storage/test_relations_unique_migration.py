"""R-06: relations 唯一索引 NULL 安全迁移测试。

回归用例：生产库已存在旧式 idx_relations_unique（裸 source_doc_id，无 COALESCE）。
SQLite 唯一索引对 NULL 视为互异，多条 source_doc_id IS NULL 的重复关系不被去重。
迁移必须：检测旧索引 → DROP + 去重 + CREATE 表达式索引（COALESCE）。
"""
import sqlite3
import pytest
from storage.database import close_db
from storage.models import init_db, get_conn, Relation, Entity


def _open_raw(db_path):
    """绕过 init_db，直接操作原始 SQLite（用于构造旧索引场景）。"""
    return sqlite3.connect(db_path)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def _build_base_tables(conn):
    """手动建 relations/entities 表（模拟旧库已有数据）。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            entity_type TEXT NOT NULL,
            source_doc_ids TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_entity_id INTEGER NOT NULL,
            to_entity_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL,
            source_doc_id INTEGER,
            confidence REAL DEFAULT 1.0,
            publish_date TEXT,
            FOREIGN KEY (from_entity_id) REFERENCES entities(id),
            FOREIGN KEY (to_entity_id) REFERENCES entities(id)
        );
    """)


def test_old_style_index_upgraded_to_expression_index(db_path):
    """分支 A：旧式 idx_relations_unique（裸 source_doc_id）→ 升级为 COALESCE 表达式索引。"""
    # 1. 先建旧库 + 旧索引（不带 COALESCE）
    conn = _open_raw(db_path)
    _build_base_tables(conn)
    conn.execute(
        "CREATE UNIQUE INDEX idx_relations_unique ON relations("
        "from_entity_id, to_entity_id, relation_type, source_doc_id)"
    )
    conn.commit()
    conn.close()

    # 2. 跑 init_db（触发迁移）
    init_db(db_path)

    # 3. 验证索引已是 COALESCE 表达式索引
    conn = get_conn()
    idx = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_relations_unique'"
    ).fetchone()
    assert idx is not None
    assert "COALESCE" in idx["sql"].upper(), "索引应升级为 COALESCE 表达式索引"
    close_db()


def test_null_source_doc_id_duplicates_deduped(db_path):
    """分支 B：含 NULL source_doc_id 的重复关系 → 去重（COALESCE 让 NULL 可去重）。"""
    # 1. 建库 + 旧索引 + 插入重复关系（source_doc_id IS NULL）
    conn = _open_raw(db_path)
    _build_base_tables(conn)
    conn.execute("CREATE UNIQUE INDEX idx_relations_unique_old ON relations("
                 "from_entity_id, to_entity_id, relation_type, source_doc_id)")
    conn.execute("INSERT INTO entities (name, entity_type, created_at) VALUES ('实体A', '机构', '2026-01-01')")
    conn.execute("INSERT INTO entities (name, entity_type, created_at) VALUES ('实体B', '机构', '2026-01-01')")
    e1 = conn.execute("SELECT id FROM entities WHERE name='实体A'").fetchone()[0]
    e2 = conn.execute("SELECT id FROM entities WHERE name='实体B'").fetchone()[0]
    # 插入 3 条重复关系（source_doc_id NULL）—— 旧索引无法阻止
    for _ in range(3):
        conn.execute(
            "INSERT INTO relations (from_entity_id, to_entity_id, relation_type, source_doc_id) "
            "VALUES (?, ?, '投资', NULL)", (e1, e2)
        )
    conn.execute("DROP INDEX idx_relations_unique_old")  # 删旧索引，让 init_db 建新的
    conn.commit()
    conn.close()

    # 2. 跑 init_db（触发去重 + 建表达式索引）
    init_db(db_path)

    # 3. 验证：3 条重复 → 1 条
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM relations WHERE from_entity_id=? AND to_entity_id=? "
        "AND relation_type='投资' AND source_doc_id IS NULL",
        (e1, e2)
    ).fetchone()[0]
    assert count == 1, f"NULL source_doc_id 重复应去重为 1 条，实际 {count}"
    close_db()


def test_repeat_migration_is_idempotent(db_path):
    """分支 C：已是 COALESCE 表达式索引时，重复迁移幂等（0 删除）。"""
    # 第一次 init 建出表达式索引
    init_db(db_path)
    conn = get_conn()
    # 插入一条关系
    conn.execute("INSERT INTO entities (name, entity_type, created_at) VALUES ('X', '机构', '2026-01-01')")
    conn.execute("INSERT INTO entities (name, entity_type, created_at) VALUES ('Y', '机构', '2026-01-01')")
    conn.execute(
        "INSERT INTO relations (from_entity_id, to_entity_id, relation_type, source_doc_id) "
        "VALUES (1, 2, '合作', 10)"
    )
    conn.commit()
    count_before = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    close_db()

    # 第二次 init（幂等）
    init_db(db_path)
    conn = get_conn()
    count_after = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
    assert count_after == count_before, "重复迁移不应删除任何关系"
    idx = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_relations_unique'"
    ).fetchone()
    assert "COALESCE" in idx["sql"].upper()
    close_db()
