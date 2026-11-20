"""范围采集 API：校验、顺序执行、故障隔离与锁释放。"""
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from storage.models import close_db, init_db
from web.job_lock import try_acquire_collect, release_collect


@pytest.fixture
def client(tmp_path, monkeypatch):
    import web.app as app_module

    monkeypatch.setattr(app_module, "_scheduler", "disabled")
    monkeypatch.setattr("storage.paths.DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("collector.config.load_sources_config", lambda: {
        "first": {"enabled": True}, "second": {"enabled": True},
        "disabled": {"enabled": False},
    })
    init_db(str(tmp_path / "test.db"))
    try:
        with TestClient(app_module.create_app()) as test_client:
            yield test_client
    finally:
        close_db()


def payload(**overrides):
    return {"sources": ["first", "second"], "date_from": "2026-09-08",
            "date_to": "2026-09-10", **overrides}


@pytest.mark.parametrize("overrides,status", [
    ({"sources": []}, 400), ({"sources": ["unknown"]}, 400),
    ({"sources": ["disabled"]}, 400), ({"date_from": "2026-09-11"}, 400),
    ({"date_from": "2026/09/08"}, 422), ({"date_to": "2026-02-30"}, 422),
    ({"date_to": None}, 422),
])
def test_invalid_request_never_constructs_adapter(client, monkeypatch, overrides, status):
    build = Mock(side_effect=AssertionError("invalid request must not collect"))
    monkeypatch.setattr("web.api.collect._build_adapter", build)
    response = client.post("/api/collect/range", json=payload(**overrides))
    assert response.status_code == status
    build.assert_not_called()
    assert try_acquire_collect()
    release_collect()


def test_range_conflicts_with_other_collection(client, monkeypatch):
    build = Mock()
    monkeypatch.setattr("web.api.collect._build_adapter", build)
    assert try_acquire_collect()
    try:
        response = client.post("/api/collect/range", json=payload())
        assert response.status_code == 409
        build.assert_not_called()
    finally:
        release_collect()


@pytest.mark.parametrize("failure", [None, "build", "run"])
def test_sources_deduplicated_run_in_order_and_release_lock(client, monkeypatch, failure):
    events = []

    def build(source):
        events.append(("build", source))
        if source == "first" and failure == "build":
            raise RuntimeError("adapter unavailable")

        def run(**kwargs):
            events.append(("run", source, kwargs))
            assert not try_acquire_collect(), "lock must cover whole background job"
            if source == "first" and failure == "run":
                raise RuntimeError("source unavailable")
            return {"new": 0, "errors": 0}

        return Mock(run=run)

    monkeypatch.setattr("web.api.collect._build_adapter", build)
    response = client.post("/api/collect/range", json=payload(sources=["first", "first", "second"]))
    assert response.status_code == 200
    assert response.json() == {"status": "started", "source_count": 2, "sources": ["first", "second"]}
    bounds = {"since": "2026-09-08", "until": "2026-09-10"}
    expected = [("build", "first")]
    if failure != "build":
        expected.append(("run", "first", bounds))
    assert events == expected + [("build", "second"), ("run", "second", bounds)]
    assert try_acquire_collect()
    release_collect()
