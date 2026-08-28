import json
import pytest
import respx
import httpx
from unittest.mock import patch
from tests.collector.fixtures import SAMPLE_DATASOURCE_JSON, SAMPLE_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_json_and_filters_links():
    """fetch_list 应解析 JSON、过滤 Link 类型、解析绝对 URL。"""
    respx.get("https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json").respond(
        json=SAMPLE_DATASOURCE_JSON
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    items = adapter.fetch_list(category="zxyw")

    # Link 类型被过滤，只剩1条
    assert len(items) == 1
    assert items[0].title == "张国华调研重点项目"
    # 相对路径 ../20260710/abc123/c.html 解析为绝对 URL
    assert items[0].url == "https://www.xiongan.gov.cn/20260710/abc123/c.html"
    assert items[0].publish_date == "2026-07-10"
    assert items[0].summary == "推进重点项目建设"


@respx.mock
def test_fetch_list_since_filters_old_items():
    """since 参数应过滤掉旧条目（遇到更早日期即停止遍历）。"""
    respx.get("https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json").respond(
        json=SAMPLE_DATASOURCE_JSON
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    # since 2026-07-10：第一条(07-10)符合，第二条是Link被过滤
    items = adapter.fetch_list(category="zxyw", since="2026-07-10")
    assert len(items) == 1
    # since 2026-07-11：当天没有更新
    items = adapter.fetch_list(category="zxyw", since="2026-07-11")
    assert len(items) == 0


@respx.mock
def test_fetch_list_initial_batch_limit():
    """首次全量（since=None）时应限制批量大小，不全量扫描。"""
    # 构造120条数据测试限制
    big_data = {
        "publishDomain": "https://www.xiongan.gov.cn",
        "isAbsolutePath": 0,
        "datasource": [
            {
                "title": f"文章{i}",
                "publishUrl": f"../2026070{i % 10}/id{i}/c.html",
                "publishTime": f"2026-07-{10 - (i // 20):02d} 09:00:00",
                "contentType": "MultiMedia",
                "contentId": f"id{i}",
            }
            for i in range(120)
        ],
    }
    respx.get("https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json").respond(
        json=big_data
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    items = adapter.fetch_list(category="zxyw", since=None)
    # 首次全量限制为 INITIAL_BATCH=50
    assert len(items) == 50


@respx.mock
def test_fetch_detail_extracts_title_and_body():
    """fetch_detail 应提取标题、正文（去掉全角空格）、来源、日期。"""
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    raw = adapter.fetch_detail("https://www.xiongan.gov.cn/20260710/abc123/c.html")

    assert raw.title == "张国华调研重点项目"
    assert "7月10日" in raw.text
    assert "调研组先后" in raw.text
    assert "\u3000" not in raw.text  # 全角空格已去除
    assert raw.source_text == "雄安发布"
    assert raw.publish_date == "2026-07-10"
