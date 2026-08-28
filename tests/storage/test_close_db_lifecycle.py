"""R-05: 连接生命周期测试。

回归用例：close_db() 在主线程关闭工作线程创建的 check_same_thread=True
连接时抛 ProgrammingError，被 except Exception: pass 静默吞掉 →
工作线程的旧连接实际未关闭，仍可被复用（连接泄漏 + 旧库残留）。

修复：check_same_thread=False 允许跨线程关闭；关闭失败记录 warning；
连接无论关闭成败都从注册表移除。
"""
import sqlite3
import threading
import pytest
from storage.models import init_db, close_db, Document
from storage.database import get_conn


def test_worker_connection_closed_after_close_db(tmp_path):
    """工作线程创建连接后，主线程 close_db → 旧引用执行 SQL 应失败。"""
    init_db(str(tmp_path / "test.db"))

    worker_conn_holder = []  # 工作线程把自己的连接放这里

    def worker():
        conn = get_conn()
        worker_conn_holder.append(conn)
        # 写一条数据确保连接活跃
        conn.execute("SELECT 1").fetchone()

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    # 工作线程的连接已被注册
    assert len(worker_conn_holder) == 1
    old_conn = worker_conn_holder[0]
    # 关闭前可用
    old_conn.execute("SELECT 1").fetchone()

    # 主线程 close_db（check_same_thread=False 允许跨线程关闭）
    close_db()

    # R-05 核心：旧引用执行 SQL 应失败（连接已关闭，不能再被复用）
    with pytest.raises(sqlite3.ProgrammingError):
        old_conn.execute("SELECT 1").fetchone()


def test_db_path_switch_invalidates_old_connection(tmp_path):
    """切库后旧连接不可访问（且旧引用执行 SQL 失败）。"""
    init_db(str(tmp_path / "first.db"))
    Document.create(
        source="x", doc_type="新闻", title="first",
        url="http://1", publish_date="2026-08-01",
        raw_html="", text="a", content_hash="h1",
    )
    old_conn = get_conn()
    assert Document.count() == 1

    close_db()
    init_db(str(tmp_path / "second.db"))

    # 旧连接引用执行 SQL 应失败
    with pytest.raises(sqlite3.ProgrammingError):
        old_conn.execute("SELECT 1").fetchone()
    close_db()


def test_close_thread_connection_cleans_own_connection(tmp_path):
    """close_thread_connection 让线程退出时关闭自己的连接。"""
    from storage.database import close_thread_connection

    init_db(str(tmp_path / "test.db"))
    holder = []

    def worker():
        conn = get_conn()
        holder.append(conn)
        close_thread_connection()  # 线程退出前主动关闭

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    # 连接已关闭
    with pytest.raises(sqlite3.ProgrammingError):
        holder[0].execute("SELECT 1").fetchone()
    # 注册表已无该线程条目（读模块全局）
    import storage.database as dbmod
    assert not any(c is holder[0] for c in dbmod._connections.values())
    close_db()


def test_close_db_resilient_to_close_failure(tmp_path):
    """连接 close() 抛异常时 close_db 不崩溃，且仍清空注册表。

    R-05：_close_all_connections_locked 捕获异常并记录 warning，连接无论关闭
    成败都从注册表移除。用 mock 注入一个 close() 抛异常的伪连接验证。
    """
    import storage.database as dbmod
    init_db(str(tmp_path / "test.db"))

    # 注入一个 close() 会抛异常的伪连接到注册表
    class BadConn:
        def close(self):
            raise RuntimeError("simulated close failure")

    with dbmod._lock:
        dbmod._connections[threading.get_ident()] = BadConn()

    # close_db 应不崩溃（异常被捕获 + warning）
    close_db()

    # 注册表已清空（读模块全局）
    assert len(dbmod._connections) == 0


def test_close_db_logs_warning_on_simulated_failure(tmp_path, caplog):
    """连接关闭失败时记录 warning（不再静默吞掉）。"""
    import logging
    import storage.database as dbmod
    init_db(str(tmp_path / "test.db"))

    class BadConn:
        def close(self):
            raise RuntimeError("simulated close failure")

    with dbmod._lock:
        dbmod._connections[threading.get_ident()] = BadConn()

    with caplog.at_level(logging.WARNING, logger="storage.database"):
        close_db()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("关闭线程" in r.message for r in warnings), \
        f"应记录关闭失败 warning，实际 logs: {[r.message for r in warnings]}"
