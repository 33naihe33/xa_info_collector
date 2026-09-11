import pytest
import respx
from tests.collector.fixtures import ANXIN_LIST_HTML, ANXIN_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_items():
    # 安新从首页抓取，模拟首页 HTML 含 /news/00- 链接
    homepage_html = """
    <html><body>
    <ul>
      <li><a href="/news/00-80-67-1-3/20001.html">安新县推进白洋淀旅游升级</a></li>
      <li><a href="/news/00-80-67-1-3/20002.html">安新县防汛工作部署会议召开</a></li>
    </ul>
    </body></html>
    """
    respx.get("https://www.anxin.gov.cn/").respond(text=homepage_html)
    from collector.adapters.anxin import AnxinAdapter

    adapter = AnxinAdapter()
    items = adapter.fetch_list()

    assert len(items) == 2
    assert items[0].title == "安新县推进白洋淀旅游升级"
    assert items[0].url == "https://www.anxin.gov.cn/news/00-80-67-1-3/20001.html"


@respx.mock
def test_fetch_list_since_filters():
    # 首页无日期，since 不过滤（靠去重保障），验证不崩溃
    homepage_html = """
    <html><body>
    <ul>
      <li><a href="/news/00-80-67-1-3/20001.html">安新县推进白洋淀旅游升级</a></li>
    </ul>
    </body></html>
    """
    respx.get("https://www.anxin.gov.cn/").respond(text=homepage_html)
    from collector.adapters.anxin import AnxinAdapter

    adapter = AnxinAdapter()
    items = adapter.fetch_list(since="2026-07-05")
    assert len(items) == 1


@respx.mock
def test_fetch_detail_extracts_title_and_body():
    respx.get(
        "https://www.anxin.gov.cn/news/00-80-67-1-3/20001.html"
    ).respond(text=ANXIN_DETAIL_HTML)
    from collector.adapters.anxin import AnxinAdapter

    adapter = AnxinAdapter()
    raw = adapter.fetch_detail(
        "https://www.anxin.gov.cn/news/00-80-67-1-3/20001.html"
    )

    # 标题来自 input[name="ArticleTitle"] 的 value
    assert raw.title == "安新县推进白洋淀旅游升级"
    assert "7月9日" in raw.text
    assert "服务品质提升" in raw.text
    # 日期来自 "发布时间：YYYY-MM-DD"
    assert raw.publish_date == "2026-07-09"
    assert "\u3000" not in raw.text


def test_get_rejects_non_official_host():
    from collector.adapters.anxin import AnxinAdapter

    with pytest.raises(ValueError, match="official host"):
        AnxinAdapter()._get("https://example.com/article")
