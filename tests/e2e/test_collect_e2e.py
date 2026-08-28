import respx
import pytest
from tests.collector.fixtures import SAMPLE_DATASOURCE_JSON, SAMPLE_DETAIL_HTML
from storage.models import init_db, Document, CrawlRun, close_db, get_conn
from collector.adapters.xiongan_portal import XionganPortalAdapter


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_full_collect_pipeline():
    """端到端：fetch_list → fetch_detail → 去重 → 入库 → crawl_run 记录。"""
    # Mock zxyw 栏目的 JSON 列表
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    # Mock zcwj 栏目的 JSON 列表（空列表，不影响主测试）
    respx.get(
        "https://www.xiongan.gov.cn/ds_381eecba9aa042aeaf418a63c376698d.json"
    ).respond(json={"datasource": []})
    # Mock 详情页
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    adapter = XionganPortalAdapter()
    result = adapter.run()

    assert result["new"] == 1
    assert result["errors"] == 0  # zcwj 返回空列表不算错误

    # 验证文档已入库
    docs = Document.list(source="xiongan_portal")
    assert len(docs) == 1
    assert docs[0].title == "张国华调研重点项目"
    assert "7月10日" in docs[0].text

    # 验证 crawl_run 记录
    # 验证文档已入库（多栏目模式，可能有多个 crawl_run）
    # 验证 crawl_run 记录
    from storage.database import get_conn
    conn = get_conn()
    runs = conn.execute("SELECT * FROM crawl_runs WHERE source = 'xiongan_portal' AND new_count > 0 ORDER BY id DESC LIMIT 1").fetchall()
    assert len(runs) >= 1
    assert runs[0]["status"] == "success"
    assert runs[0]["new_count"] == 1


@respx.mock
def test_dedup_skips_already_collected():
    """重复运行不应产生重复文档。"""
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    respx.get(
        "https://www.xiongan.gov.cn/ds_381eecba9aa042aeaf418a63c376698d.json"
    ).respond(json={"datasource": []})
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    adapter = XionganPortalAdapter()
    adapter.run()       # 第一次：1 条
    result = adapter.run()  # 第二次：增量+去重，0 条
    assert result["new"] == 0
    assert Document.count(source="xiongan_portal") == 1


@respx.mock
def test_incremental_crawl_uses_last_crawled_date():
    """增量爬取：第二次运行应基于 last_crawled_date 只获取新增内容。"""
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    respx.get(
        "https://www.xiongan.gov.cn/ds_381eecba9aa042aeaf418a63c376698d.json"
    ).respond(json={"datasource": []})
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    adapter = XionganPortalAdapter()
    # 第一次运行
    result1 = adapter.run()
    assert result1["new"] == 1

    # 第二次运行：增量+去重，0 条
    result2 = adapter.run()
    assert result2["new"] == 0

    # R-03：crawl_run 按 (source, category) 记录栏目级游标。
    # SAMPLE_DATASOURCE_JSON 对应 zxyw 栏目（datasource_path ds_faa2...）。
    from storage.models import CrawlRun
    assert CrawlRun.get_last_crawled_date("xiongan_portal", category="zxyw") == "2026-07-10"
    # 全局游标（category=None）应为 None：栏目级抓取不写全局游标
    assert CrawlRun.get_last_crawled_date("xiongan_portal", category=None) is None
