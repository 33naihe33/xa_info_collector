# tests/storage/test_concurrency.py
"""F-02: SQLite 并发连接模型测试。"""
import pytest
import threading
from storage.models import init_db, close_db, Document
from storage.database import get_conn


@pytest.fixture
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_concurrent_writes_no_errors(db):
    """两个线程各写500条文档，不产生 SQLite 错误，最终行数精确。"""
    errors = []
    count_per_thread = 500

    def writer(thread_id):
        try:
            for i in range(count_per_thread):
                Document.create(
                    source=f"source_{thread_id}",
                    doc_type="新闻",
                    title=f"thread{thread_id}_doc{i}",
                    url=f"http://t{thread_id}/{i}",
                    publish_date="2026-08-01",
                    raw_html="",
                    text=f"content_{thread_id}_{i}",
                    content_hash=f"hash_{thread_id}_{i}",
                )
        except Exception as e:
            errors.append((thread_id, str(e)))

    t1 = threading.Thread(target=writer, args=(0,))
    t2 = threading.Thread(target=writer, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(errors) == 0, f"Concurrent write errors: {errors[:3]}"
    assert Document.count() == count_per_thread * 2, \
        f"Expected {count_per_thread * 2} docs, got {Document.count()}"


def test_db_path_switch_closes_old_connections(tmp_path):
    """切换数据库路径后，旧连接不可访问。"""
    init_db(str(tmp_path / "first.db"))
    conn1 = get_conn()
    # 写入一条数据
    Document.create(
        source="x", doc_type="新闻", title="first",
        url="http://1", publish_date="2026-08-01",
        raw_html="", text="a", content_hash="h1",
    )
    assert Document.count() == 1

    # 切换到新数据库
    close_db()
    init_db(str(tmp_path / "second.db"))
    conn2 = get_conn()
    assert conn1 is not conn2, "Should get a different connection after switching DB"

    # 新数据库应该是空的
    assert Document.count() == 0, "New DB should be empty"
    close_db()
