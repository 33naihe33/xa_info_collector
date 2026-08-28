import pytest
import respx
from tests.collector.fixtures import RMXIONGAN_LIST_HTML, RMXIONGAN_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_items():
    respx.get("http://www.rmxiongan.com/GB/383581/index.html").respond(
        text=RMXIONGAN_LIST_HTML
    )
    from collector.adapters.rmxiongan import RmxionganAdapter

    adapter = RmxionganAdapter()
    items = adapter.fetch_list()

    assert len(items) == 3
    assert items[0].title == "容西片区安置房交付"
    assert items[0].url == "http://www.rmxiongan.com/n2/2026/0713/c383557-41637328.html"
    assert items[0].publish_date == "2026-07-13"


@respx.mock
def test_fetch_list_since_filters():
    respx.get("http://www.rmxiongan.com/GB/383581/index.html").respond(
        text=RMXIONGAN_LIST_HTML
    )
    from collector.adapters.rmxiongan import RmxionganAdapter

    adapter = RmxionganAdapter()
    items = adapter.fetch_list(since="2026-07-10")
    # 07-13、07-09 中只有 07-13 >= 2026-07-10；07-01 不带日期默认放行会保留
    # 这里校验：07-13 一定在，07-09 被过滤
    titles = [i.title for i in items]
    assert "容西片区安置房交付" in titles
    assert "启动区基础设施进展" not in titles


@respx.mock
def test_fetch_detail_extracts_title_and_body():
    respx.get(
        "http://www.rmxiongan.com/n2/2026/0713/c383557-41637328.html"
    ).respond(text=RMXIONGAN_DETAIL_HTML)
    from collector.adapters.rmxiongan import RmxionganAdapter

    adapter = RmxionganAdapter()
    raw = adapter.fetch_detail(
        "http://www.rmxiongan.com/n2/2026/0713/c383557-41637328.html"
    )

    # 标题剥掉了站点后缀
    assert raw.title == "容西片区安置房交付"
    assert "7月13日" in raw.text
    assert "配套学校" in raw.text
    assert "\u3000" not in raw.text  # 全角空格已去除
    assert raw.publish_date == "2026-07-13"
    assert raw.summary == "7月13日，容西片区首批安置房正式交付。"
