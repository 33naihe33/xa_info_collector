import pytest
import respx
from tests.collector.fixtures import RONGCHENG_LIST_HTML, RONGCHENG_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_items():
    respx.get("https://www.hbrc.gov.cn/news/2/10/1.html").respond(
        text=RONGCHENG_LIST_HTML
    )
    from collector.adapters.rongcheng import RongchengAdapter

    adapter = RongchengAdapter()
    items = adapter.fetch_list()

    assert len(items) == 2
    assert items[0].title == "容城县召开第N次常务会议"
    assert items[0].url == "https://www.hbrc.gov.cn/news/00-80-67-1-10/10001.html"
    assert items[0].publish_date == "2026-07-10"


@respx.mock
def test_fetch_list_since_filters():
    respx.get("https://www.hbrc.gov.cn/news/2/10/1.html").respond(
        text=RONGCHENG_LIST_HTML
    )
    from collector.adapters.rongcheng import RongchengAdapter

    adapter = RongchengAdapter()
    items = adapter.fetch_list(since="2026-07-08")
    titles = [i.title for i in items]
    assert "容城县召开第N次常务会议" in titles
    assert "容城县2026年民生实事进展" not in titles


@respx.mock
def test_fetch_detail_extracts_title_and_body():
    respx.get(
        "https://www.hbrc.gov.cn/news/00-80-67-1-10/10001.html"
    ).respond(text=RONGCHENG_DETAIL_HTML)
    from collector.adapters.rongcheng import RongchengAdapter

    adapter = RongchengAdapter()
    raw = adapter.fetch_detail(
        "https://www.hbrc.gov.cn/news/00-80-67-1-10/10001.html"
    )

    assert raw.title == "容城县召开第N次常务会议"
    assert "7月10日" in raw.text
    assert "审议通过" in raw.text
    assert raw.publish_date == "2026-07-10"
    assert "\u3000" not in raw.text
