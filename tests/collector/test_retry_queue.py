"""F-04: 重试队列接入生产流 + 公共入库方法测试。

回归用例：CrawlError.list_pending/mark_retried 曾是死代码，BaseAdapter.run
从不调用。失败 URL 永不重试。本测试验证 _retry_pending 真正消费 pending。
"""
import respx
import pytest
from tests.collector.fixtures import SAMPLE_DETAIL_HTML
from storage.models import init_db, close_db, Document, CrawlError, CrawlRun
from collector.adapters.xiongan_portal import XionganPortalAdapter


DETAIL_URL = "https://www.xiongan.gov.cn/20260710/abc123/c.html"


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _seed_pending_error(url, category=None, retry_count=1):
    """预置一条 pending 错误（已到期，可被 list_pending 选中）。"""
    CrawlError.log("xiongan_portal", url, "previous failure", category=category)
    # P1-06：log 现设置 next_retry_at（退避），清空模拟到期以供 _retry_pending 选中
    from storage.database import get_conn
    conn = get_conn()
    if category is None:
        conn.execute("UPDATE crawl_errors SET next_retry_at = NULL WHERE url = ? AND category IS NULL", (url,))
    else:
        conn.execute("UPDATE crawl_errors SET next_retry_at = NULL WHERE url = ? AND category = ?", (url, category))
    conn.commit()


@respx.mock
def test_retry_pending_succeeds_marks_retried():
    """pending URL 重试成功 → status=retried + 文档入库。"""
    _seed_pending_error(DETAIL_URL, category="zxyw")
    respx.get(DETAIL_URL).respond(text=SAMPLE_DETAIL_HTML)

    adapter = XionganPortalAdapter()
    # 直接调用 _retry_pending（不跑完整 run，避免触发列表抓取）
    retried = adapter._retry_pending(category="zxyw", limit=5)

    assert retried == 1
    # URL 不再 pending
    pending = CrawlError.list_pending("xiongan_portal", category="zxyw")
    assert not any(p["url"] == DETAIL_URL for p in pending)
    # 文档已入库
    docs = Document.list(source="xiongan_portal")
    assert len(docs) == 1
    assert docs[0].url == DETAIL_URL


@respx.mock
def test_retry_pending_already_exists_marks_retried():
    """重试时文档已入库 → 幂等成功，标记 retried，不创建重复。"""
    # 先入库文档
    _seed_pending_error(DETAIL_URL, category="zxyw")
    respx.get(DETAIL_URL).respond(text=SAMPLE_DETAIL_HTML)
    adapter = XionganPortalAdapter()
    adapter._ingest_detail.__func__  # noqa  (确保方法存在)
    # 第一次：入库
    from collector.base import ListItem
    item = ListItem(title="", url=DETAIL_URL, publish_date="", summary="")
    adapter._ingest_detail(item, category="zxyw")
    assert len(Document.list(source="xiongan_portal")) == 1

    # 第二次：重试同一 URL → already_exists，不重复创建
    retried = adapter._retry_pending(category="zxyw", limit=5)
    assert retried == 1
    assert len(Document.list(source="xiongan_portal")) == 1  # 仍只有 1 条


@respx.mock
def test_retry_pending_failure_increments_to_dead():
    """retry_count=2 的 pending 再失败 → retry_count=3 → dead，不再 pending。

    注：2 次 log 后 next_retry_at 被设为 60s 后（指数退避）。为让 list_pending
    选中该行，需把 next_retry_at 置空（模拟已到期待重试）。
    """
    url = "http://example.com/will-die"
    # 预置到 retry_count=2（2 次失败）
    CrawlError.log("xiongan_portal", url, "fail 1", category="zxyw")
    CrawlError.log("xiongan_portal", url, "fail 2", category="zxyw")
    # 模拟退避已到期：清空 next_retry_at
    from storage.database import get_conn
    get_conn().execute(
        "UPDATE crawl_errors SET next_retry_at = NULL WHERE url = ? AND category = 'zxyw'",
        (url,),
    )
    get_conn().commit()

    # 重试时详情页 500 → 抛异常 → CrawlError.log 第 3 次 → dead
    respx.get(url).respond(status_code=500)
    adapter = XionganPortalAdapter()
    retried = adapter._retry_pending(category="zxyw", limit=5)

    assert retried == 0
    assert CrawlError.is_dead("xiongan_portal", url, category="zxyw")
    pending = CrawlError.list_pending("xiongan_portal", category="zxyw")
    assert not any(p["url"] == url for p in pending)


def test_retry_pending_skips_null_url_list_errors():
    """url IS NULL 的列表级错误不交 fetch_detail。"""
    # 记录一条列表级错误（url=None）
    CrawlError.log("xiongan_portal", None, "fetch_list total failure", category="zxyw")
    # list_pending 不会返回 url IS NULL 的行（查询本身过滤 url 非空？验证行为）
    adapter = XionganPortalAdapter()
    # _retry_pending 内部跳过 url IS NULL，不应抛异常
    retried = adapter._retry_pending(category="zxyw", limit=5)
    # 列表级错误不会被 _retry_pending 消化（无 url 无法重试）
    assert retried == 0
