import pytest
import respx
from tests.collector.fixtures import XIONGXIAN_LIST_HTML, XIONGXIAN_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_items():
    respx.get(
        "http://www.xiongxian.gov.cn/index.do"
    ).respond(text=XIONGXIAN_LIST_HTML)
    from collector.adapters.xiongxian import XiongxianAdapter

    adapter = XiongxianAdapter()
    items = adapter.fetch_list()

    assert len(items) == 2
    assert items[0].title == "雄县召开乡村振兴推进会"
    # 详情 URL 无前导斜杠，需补 '/' 后拼为绝对 URL
    assert items[0].url == "http://www.xiongxian.gov.cn/content-173-99001.html"
    assert items[0].publish_date == "2026-07-08"


@respx.mock
def test_fetch_list_since_filters():
    respx.get("http://www.xiongxian.gov.cn/index.do").respond(
        text=XIONGXIAN_LIST_HTML
    )
    from collector.adapters.xiongxian import XiongxianAdapter

    adapter = XiongxianAdapter()
    items = adapter.fetch_list(since="2026-07-05")
    titles = [i.title for i in items]
    assert "雄县召开乡村振兴推进会" in titles
    assert "雄县招商引资签约" not in titles


@respx.mock
def test_fetch_detail_extracts_title_and_body():
    respx.get(
        "http://www.xiongxian.gov.cn/content-173-99001.html"
    ).respond(text=XIONGXIAN_DETAIL_HTML)
    from collector.adapters.xiongxian import XiongxianAdapter

    adapter = XiongxianAdapter()
    raw = adapter.fetch_detail(
        "http://www.xiongxian.gov.cn/content-173-99001.html"
    )

    assert raw.title == "雄县召开乡村振兴推进会"
    assert "7月8日" in raw.text
    assert "人居环境整治" in raw.text
    assert raw.publish_date == "2026-07-08"
    assert "\u3000" not in raw.text
