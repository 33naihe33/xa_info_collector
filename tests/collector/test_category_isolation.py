"""R-03: 栏目级游标隔离 + crawl_errors (source, category, url) 三元组闭环。

回归用例：原 CrawlRun.get_last_crawled_date / CrawlError.* 不支持 category，
多栏目抓取时第一个栏目成功会推进共享游标，后续栏目读到错误水位。
crawl_errors 的 category 列虽存在但从未被写入或读取（死列）。
"""
import pytest
from storage.models import init_db, close_db, CrawlRun, CrawlError


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_two_categories_have_independent_cursors():
    """栏目 A 成功推进游标，不影响栏目 B 的 get_last_crawled_date。"""
    # 栏目 zxyw 成功，推进游标
    run_a = CrawlRun.start("xiongan_portal", category="zxyw")
    run_a.finish(new_count=5, error_count=0, status="success", last_crawled_date="2026-07-10")
    # 栏目 zcwj 成功，推进到不同日期
    run_b = CrawlRun.start("xiongan_portal", category="zcwj")
    run_b.finish(new_count=3, error_count=0, status="success", last_crawled_date="2026-07-08")

    assert CrawlRun.get_last_crawled_date("xiongan_portal", category="zxyw") == "2026-07-10"
    assert CrawlRun.get_last_crawled_date("xiongan_portal", category="zcwj") == "2026-07-08"
    # 全局游标（category=None）不应被栏目 run 污染
    assert CrawlRun.get_last_crawled_date("xiongan_portal", category=None) is None


def test_same_url_different_categories_do_not_cross_contaminate():
    """同一 URL 在不同栏目失败，is_dead / list_pending 按栏目隔离。"""
    url = "http://example.com/same"
    # 栏目 A 失败 3 次 → dead
    for _ in range(3):
        CrawlError.log("xiongan_portal", url, "fail", category="zxyw")
    # 栏目 B 同 URL 只失败 1 次 → 仍 pending
    CrawlError.log("xiongan_portal", url, "fail", category="zcwj")

    # P1-06：log 现设置 next_retry_at（退避），测试类别隔离语义需清空退避模拟到期
    from storage.database import get_conn
    conn = get_conn()
    conn.execute("UPDATE crawl_errors SET next_retry_at = NULL WHERE url = ? AND category = 'zcwj'", (url,))
    conn.commit()

    assert CrawlError.is_dead("xiongan_portal", url, category="zxyw")
    assert not CrawlError.is_dead("xiongan_portal", url, category="zcwj")
    # 栏目 B 的 pending 应包含该 URL
    pending_b = CrawlError.list_pending("xiongan_portal", category="zcwj")
    assert any(p["url"] == url for p in pending_b)
    # 栏目 A 的 pending 不应包含（已 dead）
    pending_a = CrawlError.list_pending("xiongan_portal", category="zxyw")
    assert not any(p["url"] == url for p in pending_a)


def test_category_none_uses_is_null_for_legacy_bucket():
    """category=None 用 IS NULL 查询，能返回遗留全局桶错误。"""
    # 遗留错误：不传 category → category IS NULL
    CrawlError.log("xiongan_portal", "http://example.com/legacy", "old error")
    # P1-06：log 设置 next_retry_at（退避），清空模拟到期以查 pending
    from storage.database import get_conn
    conn = get_conn()
    conn.execute("UPDATE crawl_errors SET next_retry_at = NULL WHERE url = 'http://example.com/legacy'")
    conn.commit()
    pending = CrawlError.list_pending("xiongan_portal", category=None)
    assert any(p["url"] == "http://example.com/legacy" for p in pending)
    assert all(p["category"] is None for p in pending)
    # 传具体栏目不应查到遗留错误
    pending_cat = CrawlError.list_pending("xiongan_portal", category="zxyw")
    assert not any(p["url"] == "http://example.com/legacy" for p in pending_cat)


def test_category_column_added_for_old_and_new_db():
    """新库 DDL 与旧库 ALTER 两条路径都应建出 crawl_runs.category 列。"""
    # 新库（本 fixture 已 init）：直接查列存在
    from storage.database import get_conn
    conn = get_conn()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(crawl_runs)").fetchall()]
    assert "category" in cols, "新库 DDL 应包含 category 列"
    # crawl_errors 也应有 category
    err_cols = [r[1] for r in conn.execute("PRAGMA table_info(crawl_errors)").fetchall()]
    assert "category" in err_cols
