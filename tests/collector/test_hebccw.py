import pytest
import respx
from tests.collector.fixtures import HEBCCW_LIST_HTML, HEBCCW_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_items():
    respx.get("https://xiongan.hebccw.cn/xaxw/index.shtml").respond(
        text=HEBCCW_LIST_HTML
    )
    from collector.adapters.hebccw import HebccwAdapter

    adapter = HebccwAdapter()
    items = adapter.fetch_list()

    assert len(items) == 2
    assert items[0].title == "雄安站迎来暑运高峰"
    assert items[0].url == "https://xiongan.hebccw.cn/system/2026/07/13/123456789.shtml"
    assert items[0].publish_date == "2026-07-13"


@respx.mock
def test_fetch_list_since_filters():
    respx.get("https://xiongan.hebccw.cn/xaxw/index.shtml").respond(
        text=HEBCCW_LIST_HTML
    )
    from collector.adapters.hebccw import HebccwAdapter

    adapter = HebccwAdapter()
    items = adapter.fetch_list(since="2026-07-10")
    titles = [i.title for i in items]
    assert "雄安站迎来暑运高峰" in titles
    assert "白洋淀生态治理见成效" not in titles


@respx.mock
def test_fetch_detail_extracts_title_and_body():
    respx.get(
        "https://xiongan.hebccw.cn/system/2026/07/13/123456789.shtml"
    ).respond(text=HEBCCW_DETAIL_HTML)
    from collector.adapters.hebccw import HebccwAdapter

    adapter = HebccwAdapter()
    raw = adapter.fetch_detail(
        "https://xiongan.hebccw.cn/system/2026/07/13/123456789.shtml"
    )

    assert raw.title == "雄安站迎来暑运高峰"
    assert "7月13日" in raw.text
    assert "3万人次" in raw.text
    assert "\u3000" not in raw.text
