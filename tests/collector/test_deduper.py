from collector.deduper import is_duplicate, content_hash

def test_content_hash_stable():
    assert content_hash("hello") == content_hash("hello")

def test_content_hash_different():
    assert content_hash("hello") != content_hash("world")

def test_is_duplicate_true(tmp_path, monkeypatch):
    from storage.models import init_db, Document, close_db
    init_db(str(tmp_path / "t.db"))
    Document.create(
        source="x", doc_type="新闻", title="t", url="http://a",
        publish_date="2026-07-10", raw_html="", text="abc",
        content_hash=content_hash("abc"),
    )
    assert is_duplicate("abc") is True
    close_db()

def test_is_duplicate_false(tmp_path):
    from storage.models import init_db, close_db
    init_db(str(tmp_path / "t.db"))
    assert is_duplicate("xyz") is False
    close_db()
