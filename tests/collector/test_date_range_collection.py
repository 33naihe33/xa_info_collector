import pytest

from collector.base import BaseAdapter, ListItem, RawDoc
from storage.models import CrawlError, CrawlRun, Document, close_db, init_db


@pytest.fixture(autouse=True)
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("storage.paths.DATA_DIR", str(tmp_path / "data"))
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


class FakeAdapter(BaseAdapter):
    source_name = "rmxiongan"

    def __init__(self, items, fail_list=False, fail_url=None):
        super().__init__()
        self.items, self.fail_list, self.fail_url = items, fail_list, fail_url
        self.ingested_urls = []

    def fetch_list(self, since=None):
        if self.fail_list:
            raise RuntimeError("list failed")
        return self.items

    def fetch_detail(self, url):
        if url == self.fail_url:
            raise RuntimeError("detail failed")
        self.ingested_urls.append(url)
        return RawDoc(title=url, url=url, publish_date="", raw_html="", text=url)


def _prior_cursor():
    run = CrawlRun.start("rmxiongan")
    run.finish(new_count=1, error_count=0, last_crawled_date="2026-09-07")


def test_range_run_includes_bounds_skips_pending_and_preserves_cursor():
    _prior_cursor()
    CrawlError.log("rmxiongan", "https://test/pending", "old error")
    adapter = FakeAdapter([
        ListItem("low", "https://test/low", "2026-09-08"),
        ListItem("inside", "https://test/in", "2026-09-09"),
        ListItem("high", "https://test/high", "2026-09-10"),
        ListItem("missing", "https://test/missing", ""),
        ListItem("old", "https://test/old", "2026-09-07"),
        ListItem("future", "https://test/future", "2026-09-11"),
        ListItem("invalid", "https://test/invalid", "not-a-date"),
    ])
    adapter.run(since="2026-09-08", until="2026-09-10")
    assert adapter.ingested_urls == ["https://test/low", "https://test/in", "https://test/high"]
    assert CrawlRun.get_last_crawled_date("rmxiongan") == "2026-09-07"


@pytest.mark.parametrize("detail_date,expected", [
    ("2026-09-07", 0), ("2026-09-11", 0), ("invalid", 0),
    ("2026-09-08", 1), ("2026-09-10T12:00:00", 1), ("", 1),
])
def test_range_checks_final_detail_date_before_inserting(monkeypatch, detail_date, expected):
    adapter = FakeAdapter([ListItem("inside", "https://test/in", "2026-09-09")])
    monkeypatch.setattr(adapter, "fetch_detail", lambda url: RawDoc(
        title=url, url=url, publish_date=detail_date, raw_html="", text=url,
    ))
    result = adapter.run(since="2026-09-08", until="2026-09-10")
    assert result["new"] == expected
    documents = Document.list()
    assert len(documents) == expected
    for document in documents:
        assert "2026-09-08" <= document.publish_date <= "2026-09-10"


@pytest.mark.parametrize("since,until", [
    (None, "2026-09-10"), ("2026-09-11", "2026-09-10"),
    ("bad", "2026-09-10"), ("2026-09-08", "bad"),
])
def test_range_rejects_invalid_bounds_before_fetch(monkeypatch, since, until):
    adapter = FakeAdapter([])
    monkeypatch.setattr(adapter, "fetch_list", lambda **kwargs: pytest.fail("must validate before fetching"))
    with pytest.raises(ValueError):
        adapter.run(since=since, until=until)


@pytest.mark.parametrize("failure", [None, "detail", "list"])
def test_portal_range_preserves_each_category_cursor_and_skips_pending(monkeypatch, failure):
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    adapter.config = {"categories": {
        name: {"datasource_path": "/unused"} for name in ("zxyw", "zcwj")
    }}
    for category, cursor in [("zxyw", "2026-09-06"), ("zcwj", "2026-09-07")]:
        run = CrawlRun.start(adapter.source_name, category=category)
        run.finish(new_count=1, error_count=0, last_crawled_date=cursor)
    monkeypatch.setattr(adapter, "_retry_pending", lambda **kwargs: pytest.fail("range must skip pending"))

    def fetch_list(since=None, category=None):
        if failure == "list" and category == "zxyw":
            raise RuntimeError("list failed")
        return [
            ListItem(category, f"https://test/{category}", "2026-09-09"),
            ListItem("old", "https://test/old", "2026-09-07"),
            ListItem("future", "https://test/future", "2026-09-11"),
            ListItem("unknown", "https://test/unknown", ""),
        ]

    def fetch_detail(url):
        if failure == "detail" and url.endswith("zxyw"):
            raise RuntimeError("detail failed")
        return RawDoc(url, url, "2026-09-09", "", url)

    monkeypatch.setattr(adapter, "fetch_list", fetch_list)
    monkeypatch.setattr(adapter, "fetch_detail", fetch_detail)
    result = adapter.run(since="2026-09-08", until="2026-09-10")
    assert result["new"] == (2 if failure is None else 1)
    assert result["errors"] == (0 if failure is None else 1)
    for category, cursor in [("zxyw", "2026-09-06"), ("zcwj", "2026-09-07")]:
        run = CrawlRun.latest_by_source(adapter.source_name, category=category)
        assert run.last_crawled_date is None
        assert CrawlRun.get_last_crawled_date(adapter.source_name, category=category) == cursor


@pytest.mark.parametrize("fail_list,fail_url,expected", [(False, "https://test/in", "success_with_errors"), (True, None, "failed")])
def test_range_run_error_paths_write_no_cursor(fail_list, fail_url, expected):
    _prior_cursor()
    adapter = FakeAdapter([ListItem("inside", "https://test/in", "2026-09-09")], fail_list, fail_url)
    if fail_list:
        with pytest.raises(RuntimeError):
            adapter.run(since="2026-09-08", until="2026-09-10")
    else:
        adapter.run(since="2026-09-08", until="2026-09-10")
    run = CrawlRun.latest_by_source("rmxiongan")
    assert run.status == expected
    assert run.last_crawled_date is None
    assert CrawlRun.get_last_crawled_date("rmxiongan") == "2026-09-07"
