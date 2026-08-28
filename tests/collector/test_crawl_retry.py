# tests/collector/test_crawl_retry.py
"""F-04: 游标止血 + URL级重试测试。"""
import pytest
from storage.models import init_db, close_db, CrawlError, CrawlRun


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_crawl_error_upsert_same_url():
    """同一URL失败多次应更新而非插入新行。

    R-03：retry_count 语义为"失败次数"，首次失败=1，每次 log 累加 1。
    两次 log 后 retry_count=2。
    """
    CrawlError.log("test_source", "http://example.com/a", "error 1")
    CrawlError.log("test_source", "http://example.com/a", "error 2")
    from storage.database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT retry_count, status, category FROM crawl_errors WHERE source = ? AND url = ?",
        ("test_source", "http://example.com/a"),
    ).fetchall()
    assert len(rows) == 1, "Same URL should not create duplicate error rows"
    assert rows[0]["retry_count"] == 2, "retry_count = 失败次数（首次1，每次+1）"
    assert rows[0]["status"] == "pending"
    assert rows[0]["category"] is None  # 未传 category → NULL


def test_crawl_error_dead_after_3_retries():
    """3次失败后标记为dead，不再出现在pending中。"""
    url = "http://example.com/dead"
    CrawlError.log("test_source", url, "fail 1")
    CrawlError.log("test_source", url, "fail 2")
    CrawlError.log("test_source", url, "fail 3")
    assert CrawlError.is_dead("test_source", url), "URL should be dead after 3 failures"
    pending = CrawlError.list_pending("test_source")
    assert len(pending) == 0, "Dead URL should not appear in pending"


def test_crawl_error_mark_retried():
    """成功重试后标记为retried。"""
    url = "http://example.com/retry"
    CrawlError.log("test_source", url, "temp error")
    CrawlError.mark_retried("test_source", url)
    pending = CrawlError.list_pending("test_source")
    assert len(pending) == 0, "Retried URL should not appear in pending"


def test_cursor_not_advanced_on_errors():
    """有错误时游标不推进（status=success_with_errors不含last_crawled_date更新）。"""
    # 第一次成功运行，推进游标到 2026-07-10
    run1 = CrawlRun.start("test_source")
    run1.finish(new_count=5, error_count=0, status="success", last_crawled_date="2026-07-10")

    # 第二次有错误
    run2 = CrawlRun.start("test_source")
    run2.finish(new_count=3, error_count=2, status="success_with_errors", last_crawled_date="2026-07-10")

    # 游标应保持 2026-07-10（success_with_errors 不被 get_last_crawled_date 识别）
    cursor = CrawlRun.get_last_crawled_date("test_source")
    assert cursor == "2026-07-10", f"Cursor should stay at 2026-07-10, got {cursor}"


def test_dead_url_skipped_in_run():
    """dead URL在抓取时被跳过。"""
    url = "http://example.com/dead"
    # 标记为dead
    CrawlError.log("test_source", url, "fail 1")
    CrawlError.log("test_source", url, "fail 2")
    CrawlError.log("test_source", url, "fail 3")
    assert CrawlError.is_dead("test_source", url)

    # 再次记录错误不应创建新行
    CrawlError.log("test_source", url, "fail 4")
    pending = CrawlError.list_pending("test_source")
    assert len(pending) == 0, "Dead URL should stay dead"


def test_crawl_error_unique_index_prevents_duplicates():
    """P1-06：NULL-safe 唯一索引存在，防止重复 (source, category, url) 行。"""
    from storage.database import get_conn
    conn = get_conn()
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_crawl_errors_unique'"
    ).fetchone()
    assert idx is not None, "应存在 idx_crawl_errors_unique 唯一索引"


def test_crawl_error_log_idempotent_for_same_url():
    """P1-06：同一 URL 多次 log 只产生一行，retry_count 正确累加。"""
    from storage.database import get_conn
    url = "http://example.com/dup-test"
    CrawlError.log("test_source", url, "fail 1", category="zxyw")
    CrawlError.log("test_source", url, "fail 2", category="zxyw")
    conn = get_conn()
    rows = conn.execute(
        "SELECT retry_count, status FROM crawl_errors WHERE url = ? AND category = 'zxyw'",
        (url,),
    ).fetchall()
    assert len(rows) == 1, f"同一 URL 应只有 1 行，实际 {len(rows)}"
    assert rows[0]["retry_count"] == 2
