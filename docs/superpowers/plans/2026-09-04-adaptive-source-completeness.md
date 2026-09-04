# Adaptive Source Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent silent omissions by making every enabled source report verifiable coverage, scanning pages within a bounded adaptive budget, resuming incomplete windows, and advancing cursors only after complete coverage.

**Architecture:** Add a small coverage contract shared by collectors, persist coverage and continuation state on `crawl_runs`, then migrate every enabled adapter in one release. `BaseAdapter` owns cold-start, three-day overlap, continuation, final coverage reconciliation, and cursor safety; adapters own page discovery and source-specific block/empty-page detection.

**Tech Stack:** Python 3.11+, dataclasses, SQLite, httpx, BeautifulSoup, FastAPI, pytest, respx.

## Global Constraints

- Automatic cold start covers the most recent 7 days; older history requires explicit `scripts/backfill_range.py <since>`.
- Daily automatic runs start at the last complete cursor minus 3 days.
- Collection stays synchronous and single-threaded.
- Existing QPS limits remain: portal 2, HTML sources 1, WeChat 0.2 plus 0–2 seconds jitter.
- Page/request hard limits are never bypassed.
- A run advances the cursor only when `status = 'success'` and `coverage_status = 'complete'`.
- All currently enabled adapters migrate in this branch before deployment.
- No captcha bypass, logged-in automation, paid source, LLM, reporting, or external-notification changes.

---

## File Map

- Create `collector/coverage.py`: coverage enums, result dataclasses, date-window and adaptive-budget helpers.
- Modify `collector/base.py`: enforce the list-result contract and reconcile list/detail coverage.
- Modify `storage/models.py`: migrate and persist coverage, continuation, budget, and backoff fields.
- Modify all files under `collector/adapters/`: return the coverage contract and implement bounded pagination/exhaustion.
- Modify `config/sources.yaml`: add budgets and migrate WeChat `max_results` to `results_per_page`.
- Modify `web/api/collect.py` and `web/app.py`: expose coverage state and honor source-level backoff.
- Add focused collector/storage/web tests and fixtures; update existing tests to use the new contract.

---

### Task 1: Coverage Contract and Pure Policy Helpers

**Files:**
- Create: `collector/coverage.py`
- Create: `tests/collector/test_coverage.py`

**Interfaces:**
- Produces: `CoverageStatus`, `StopReason`, `CoverageMeta`, `ListFetchResult`, `RequestBudget`, `RequestBudgetExceeded`, `effective_since()`, `effective_page_budget()`, and `coverage_status_for()`.
- Consumes: only Python standard-library types; no database or HTTP dependencies.

- [ ] **Step 1: Write the failing policy tests**

```python
# tests/collector/test_coverage.py
from datetime import date

from collector.coverage import (
    CoverageMeta,
    ListFetchResult,
    coverage_status_for,
    effective_page_budget,
    effective_since,
    RequestBudget,
    RequestBudgetExceeded,
)


def test_effective_since_uses_seven_day_bootstrap_without_cursor():
    assert effective_since(None, today=date(2026, 9, 4)) == "2026-08-28"


def test_effective_since_overlaps_saved_cursor_by_three_days():
    assert effective_since("2026-09-04", today=date(2026, 9, 4)) == "2026-09-01"


def test_explicit_since_is_not_rewritten():
    assert effective_since("2026-08-01", explicit=True, today=date(2026, 9, 4)) == "2026-08-01"


def test_budget_doubles_after_two_incomplete_runs_and_stops_at_hard_limit():
    assert effective_page_budget(2, 10, consecutive_incomplete=0) == 2
    assert effective_page_budget(2, 10, consecutive_incomplete=2) == 4
    assert effective_page_budget(8, 10, consecutive_incomplete=4) == 10


def test_stop_reason_has_fixed_status_mapping():
    assert coverage_status_for("date_boundary") == "complete"
    assert coverage_status_for("source_exhausted") == "complete"
    assert coverage_status_for("request_budget") == "incomplete"
    assert coverage_status_for("invalid_page") == "incomplete"
    assert coverage_status_for("blocked") == "blocked"


def test_list_fetch_result_carries_items_and_resume_state():
    result = ListFetchResult(
        items=["item"],
        coverage=CoverageMeta(
            stop_reason="request_budget",
            pages_fetched=2,
            continuation_page=3,
            oldest_seen_date="2026-09-01",
            newest_seen_date="2026-09-04",
        ),
    )
    assert result.coverage.coverage_status == "incomplete"
    assert result.coverage.continuation_page == 3


def test_request_budget_raises_before_exceeding_limit():
    budget = RequestBudget(limit=2)
    budget.consume()
    budget.consume()
    with __import__("pytest").raises(RequestBudgetExceeded):
        budget.consume()
    assert budget.used == 2
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/collector/test_coverage.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'collector.coverage'`.

- [ ] **Step 3: Implement the minimal coverage module**

```python
# collector/coverage.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

CoverageStatus = Literal["complete", "incomplete", "blocked", "unknown"]
StopReason = Literal[
    "date_boundary", "source_exhausted", "request_budget", "page_limit",
    "invalid_page", "invalid_result", "detail_error", "network_error", "blocked",
]

_COMPLETE = {"date_boundary", "source_exhausted"}


def coverage_status_for(stop_reason: StopReason) -> CoverageStatus:
    if stop_reason in _COMPLETE:
        return "complete"
    if stop_reason == "blocked":
        return "blocked"
    return "incomplete"


@dataclass
class CoverageMeta:
    stop_reason: StopReason
    pages_fetched: int = 0
    oldest_seen_date: str | None = None
    newest_seen_date: str | None = None
    coverage_window_start: str | None = None
    continuation_page: int | None = None
    episode_newest_seen_date: str | None = None
    coverage_status: CoverageStatus = field(init=False)

    def __post_init__(self) -> None:
        self.coverage_status = coverage_status_for(self.stop_reason)


@dataclass
class ListFetchResult:
    items: list[Any]
    coverage: CoverageMeta


class RequestBudgetExceeded(RuntimeError):
    pass


@dataclass
class RequestBudget:
    limit: int
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.limit:
            raise RequestBudgetExceeded(f"request budget exhausted at {self.limit}")
        self.used += 1


def effective_since(
    saved_or_explicit: str | None,
    *,
    explicit: bool = False,
    today: date | None = None,
    overlap_days: int = 3,
    bootstrap_days: int = 7,
) -> str:
    if explicit and saved_or_explicit:
        return saved_or_explicit
    base = today or date.today()
    if not saved_or_explicit:
        return (base - timedelta(days=bootstrap_days)).isoformat()
    cursor = datetime.strptime(saved_or_explicit[:10], "%Y-%m-%d").date()
    return (cursor - timedelta(days=overlap_days)).isoformat()


def effective_page_budget(initial: int, hard_limit: int, consecutive_incomplete: int) -> int:
    multiplier = 2 ** max(0, consecutive_incomplete // 2)
    return min(hard_limit, initial * multiplier)
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `pytest tests/collector/test_coverage.py -q`

Expected: `7 passed`.

- [ ] **Step 5: Commit the policy layer**

```bash
git add collector/coverage.py tests/collector/test_coverage.py
git commit -m "feat: define collector coverage contract"
```

---

### Task 2: Persist Coverage, Continuation, and Backoff

**Files:**
- Modify: `storage/models.py:73-101, 292-302, 638-748`
- Create: `tests/storage/test_crawl_coverage.py`

**Interfaces:**
- Consumes: strings and counters from `CoverageMeta`.
- Produces: `CrawlRun.finish(...coverage fields...)`, `latest_incomplete_episode()`, `blocked_until()`, and strict `get_last_crawled_date()`.

- [ ] **Step 1: Write failing migration and cursor tests**

```python
# tests/storage/test_crawl_coverage.py
from datetime import datetime, timedelta

import pytest

from storage.models import CrawlRun, close_db, init_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "coverage.db"))
    yield
    close_db()


def test_only_complete_run_can_supply_cursor():
    incomplete = CrawlRun.start("source")
    incomplete.finish(
        new_count=3, error_count=0, status="success",
        last_crawled_date="2026-09-04",
        coverage_status="incomplete", stop_reason="request_budget",
    )
    assert CrawlRun.get_last_crawled_date("source") is None

    complete = CrawlRun.start("source")
    complete.finish(
        new_count=1, error_count=0, status="success",
        last_crawled_date="2026-09-03",
        coverage_status="complete", stop_reason="date_boundary",
    )
    assert CrawlRun.get_last_crawled_date("source") == "2026-09-03"


def test_incomplete_episode_round_trips_continuation_fields():
    run = CrawlRun.start("source", category="news")
    run.finish(
        new_count=10, error_count=0, status="success",
        coverage_status="incomplete", stop_reason="page_limit",
        coverage_window_start="2026-08-28", continuation_page=4,
        episode_newest_seen_date="2026-09-04", pages_fetched=2,
        consecutive_incomplete=2, effective_page_budget=4,
        needs_attention=False,
    )
    resumed = CrawlRun.latest_incomplete_episode("source", category="news")
    assert resumed.continuation_page == 4
    assert resumed.coverage_window_start == "2026-08-28"

    complete = CrawlRun.start("source", category="news")
    complete.finish(
        new_count=0, error_count=0, status="success",
        last_crawled_date="2026-09-04",
        coverage_status="complete", stop_reason="date_boundary",
    )
    assert CrawlRun.latest_incomplete_episode("source", category="news") is None


def test_blocked_until_reads_latest_future_retry():
    retry_at = (datetime.now() + timedelta(hours=6)).isoformat()
    run = CrawlRun.start("source")
    run.finish(
        new_count=0, error_count=0, status="success",
        coverage_status="blocked", stop_reason="blocked", next_retry_at=retry_at,
    )
    assert CrawlRun.blocked_until("source") == retry_at
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/storage/test_crawl_coverage.py -q`

Expected: tests fail because the coverage columns and method arguments do not exist.

- [ ] **Step 3: Extend schema and idempotent migration**

Add these columns to `crawl_runs` in `SCHEMA_SQL`, then mirror them in the existing `PRAGMA table_info(crawl_runs)` migration loop:

```sql
coverage_status TEXT NOT NULL DEFAULT 'unknown',
stop_reason TEXT,
pages_fetched INTEGER NOT NULL DEFAULT 0,
oldest_seen_date TEXT,
newest_seen_date TEXT,
coverage_window_start TEXT,
continuation_page INTEGER,
episode_newest_seen_date TEXT,
consecutive_incomplete INTEGER NOT NULL DEFAULT 0,
effective_page_budget INTEGER NOT NULL DEFAULT 0,
next_retry_at TEXT,
needs_attention INTEGER NOT NULL DEFAULT 0
```

Use this explicit migration mapping:

```python
run_migrations = {
    "coverage_status": "TEXT NOT NULL DEFAULT 'unknown'",
    "stop_reason": "TEXT",
    "pages_fetched": "INTEGER NOT NULL DEFAULT 0",
    "oldest_seen_date": "TEXT",
    "newest_seen_date": "TEXT",
    "coverage_window_start": "TEXT",
    "continuation_page": "INTEGER",
    "episode_newest_seen_date": "TEXT",
    "consecutive_incomplete": "INTEGER NOT NULL DEFAULT 0",
    "effective_page_budget": "INTEGER NOT NULL DEFAULT 0",
    "next_retry_at": "TEXT",
    "needs_attention": "INTEGER NOT NULL DEFAULT 0",
}
for column, ddl in run_migrations.items():
    if column not in cr_cols:
        conn.execute(f"ALTER TABLE crawl_runs ADD COLUMN {column} {ddl}")
```

- [ ] **Step 4: Extend `CrawlRun` without breaking old callers**

Keep all new `finish()` arguments keyword-only and optional. Add each new field to `__init__()` and `to_dict()`. Implement the strict cursor and episode queries:

```python
@classmethod
def latest_incomplete_episode(cls, source: str, category: str | None = None):
    latest = cls.latest_by_source(source, category=category)
    if (
        latest
        and latest.coverage_status == "incomplete"
        and latest.continuation_page is not None
    ):
        return latest
    return None

@classmethod
def blocked_until(cls, source: str, category: str | None = None) -> str | None:
    latest = cls.latest_by_source(source, category=category)
    if latest and latest.coverage_status == "blocked":
        return latest.next_retry_at
    return None
```

In both branches of `get_last_crawled_date()`, add:

```sql
AND coverage_status = 'complete'
```

- [ ] **Step 5: Verify storage tests and existing retry tests**

Run: `pytest tests/storage/test_crawl_coverage.py tests/collector/test_crawl_retry.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit persistence changes**

```bash
git add storage/models.py tests/storage/test_crawl_coverage.py
git commit -m "feat: persist crawl coverage state"
```

---

### Task 3: Base Adapter Orchestration, Cold Start, and Resume

**Files:**
- Modify: `collector/base.py:1-218`
- Create: `tests/collector/test_coverage_run.py`
- Modify: `tests/collector/test_crawl_retry.py`

**Interfaces:**
- Consumes: `ListFetchResult`, source budgets, `CrawlRun` episode state.
- Produces: `BaseAdapter.run(since=None, category=None)` result fields `coverage_status`, `stop_reason`, `pages_fetched`, and `effective_since`.

- [ ] **Step 1: Write a deterministic fake adapter and failing orchestration tests**

```python
# tests/collector/test_coverage_run.py
from datetime import date
from unittest.mock import patch

import pytest

from collector.base import BaseAdapter, ListItem, RawDoc
from collector.coverage import CoverageMeta, ListFetchResult
from storage.models import CrawlRun, close_db, init_db


class FakeAdapter(BaseAdapter):
    source_name = "xiongan_portal"
    coverage_contract_version = 1

    def __init__(self, result):
        super().__init__()
        self.result = result
        self.received = None

    def fetch_list(self, since=None, *, start_page=1, page_budget=None):
        self.received = (since, start_page, page_budget)
        return self.result

    def fetch_detail(self, url):
        return RawDoc("title", url, "2026-09-04", "", "body")

    def download_images(self, raw, content_hash):
        return None

    def save_snapshot(self, raw):
        return None


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "run.db"))
    yield
    close_db()


def test_cold_start_passes_seven_day_boundary():
    adapter = FakeAdapter(ListFetchResult([], CoverageMeta("source_exhausted", pages_fetched=1)))
    with patch("collector.coverage.date") as mocked_date:
        mocked_date.today.return_value = date(2026, 9, 4)
        adapter.run()
    assert adapter.received[0] == "2026-08-28"


def test_old_list_return_is_contract_error_and_does_not_create_cursor():
    adapter = FakeAdapter([])
    result = adapter.run(since="2026-09-01")
    assert result["coverage_status"] == "incomplete"
    assert result["stop_reason"] == "invalid_result"
    assert CrawlRun.get_last_crawled_date(adapter.source_name) is None


def test_detail_error_overrides_complete_list_coverage():
    item = ListItem("title", "https://example.test/a", "2026-09-04")
    adapter = FakeAdapter(ListFetchResult([item], CoverageMeta("source_exhausted", pages_fetched=1)))
    adapter.fetch_detail = lambda _url: (_ for _ in ()).throw(RuntimeError("detail failed"))
    result = adapter.run(since="2026-09-01")
    assert result["coverage_status"] == "incomplete"
    assert result["stop_reason"] == "detail_error"


def test_incomplete_run_resumes_with_one_page_overlap():
    previous = CrawlRun.start("xiongan_portal")
    previous.finish(
        new_count=0, error_count=0, status="success",
        coverage_status="incomplete", stop_reason="request_budget",
        coverage_window_start="2026-08-28", continuation_page=5,
        episode_newest_seen_date="2026-09-04", consecutive_incomplete=1,
    )
    adapter = FakeAdapter(ListFetchResult([], CoverageMeta("source_exhausted", pages_fetched=2)))
    adapter.run()
    assert adapter.received[1] == 4
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/collector/test_coverage_run.py -q`

Expected: tests fail because `BaseAdapter` does not enforce or reconcile coverage.

- [ ] **Step 3: Add run-context helpers to `BaseAdapter`**

Add these methods and use source configuration defaults from the design:

```python
def _budget_defaults(self) -> tuple[int, int, int]:
    is_wechat = self.source_name.startswith("wechat_")
    initial = int(self.config.get("initial_page_budget", 2 if is_wechat else 5))
    hard = int(self.config.get("hard_page_limit", 10 if is_wechat else 20))
    requests = int(self.config.get("max_requests_per_run", 30 if is_wechat else 100))
    return initial, hard, requests

def _before_request(self) -> None:
    self._request_budget.consume()
    self._throttle()

def _scan_context(self, explicit_since: str | None, category: str | None = None) -> dict:
    episode = CrawlRun.latest_incomplete_episode(self.source_name, category=category)
    cursor = CrawlRun.get_last_crawled_date(self.source_name, category=category)
    boundary = effective_since(
        explicit_since if explicit_since is not None else cursor,
        explicit=explicit_since is not None,
        bootstrap_days=int(self.config.get("bootstrap_lookback_days", 7)),
    )
    if episode:
        boundary = episode.coverage_window_start or boundary
    consecutive = episode.consecutive_incomplete if episode else 0
    initial, hard, max_requests = self._budget_defaults()
    return {
        "since": boundary,
        "start_page": max(1, (episode.continuation_page or 1) - 1) if episode else 1,
        "page_budget": effective_page_budget(initial, hard, consecutive),
        "max_requests": max_requests,
        "episode": episode,
    }
```

- [ ] **Step 4: Replace `run()` list handling with contract validation and final reconciliation**

Initialize `self._request_budget = RequestBudget(context["max_requests"])`, then call `fetch_list(since=context["since"], start_page=..., page_budget=...)`. Every migrated adapter `_get()` must call `_before_request()` instead of `_throttle()` so list and detail calls share the same counter. If an adapter declaring `coverage_contract_version = 1` returns anything other than `ListFetchResult`, synthesize `CoverageMeta("invalid_result")`. To keep intermediate branch commits testable before Tasks 4–6 migrate every adapter, adapters without that declaration temporarily retain the old list/cursor behavior; Task 6 removes this temporary path after the all-enabled-adapter contract test passes. While ingesting, calculate min/max non-empty `IngestResult.publish_date`; an unresolved ordinary detail error changes final reason to `detail_error`, while `RequestBudgetExceeded` changes it to `request_budget` and preserves the next unprocessed item/page continuation. Persist metadata via `CrawlRun.finish()` and return it in the result dictionary.

Use this exact finalization rule:

```python
final_reason = list_result.coverage.stop_reason
if error_count:
    final_reason = "detail_error"
final_status = coverage_status_for(final_reason)
cursor_date = None
if final_status == "complete":
    cursor_date = max(
        value for value in (
            list_result.coverage.episode_newest_seen_date,
            context["episode"].episode_newest_seen_date if context["episode"] else None,
            newest_detail_date,
        ) if value
    ) if any((
        list_result.coverage.episode_newest_seen_date,
        context["episode"].episode_newest_seen_date if context["episode"] else None,
        newest_detail_date,
    )) else context["since"]
```

For `request_budget`/`page_limit`, increment `consecutive_incomplete`, persist the next page, and set `needs_attention=True` at count 3. For `blocked`, compute `next_retry_at` as 6, 12, 24, 48, then 72 hours based on consecutive blocked runs.

- [ ] **Step 5: Run focused and existing collector tests**

Run: `pytest tests/collector/test_coverage_run.py tests/collector/test_crawl_retry.py tests/e2e/test_collect_e2e.py -q`

Expected: all tests pass after updating existing fake adapters/fixtures to return `ListFetchResult`.

- [ ] **Step 6: Commit orchestration changes**

```bash
git add collector/base.py tests/collector/test_coverage_run.py tests/collector/test_crawl_retry.py tests/e2e/test_collect_e2e.py
git commit -m "feat: enforce complete crawl windows"
```

---

### Task 4: Repair Xiongan Portal Category Coverage

**Files:**
- Modify: `collector/adapters/xiongan_portal.py`
- Modify: `config/sources.yaml:3-21`
- Modify: `tests/collector/test_xiongan_portal.py`
- Modify: `tests/collector/fixtures.py`

**Interfaces:**
- Consumes: `since`, `start_page`, `page_budget` and category configuration.
- Produces: a `ListFetchResult` for every configured category, including `tzgg`; no category is silently skipped.

- [ ] **Step 1: Add failing tests for datasource discovery and category failure**

```python
@respx.mock
def test_tzgg_discovers_datasource_and_returns_notice():
    respx.get("https://www.xiongan.gov.cn/tzgg.html").respond(
        text='<script>window.dataUrl="/ds_tzgg_test.json";</script>'
    )
    respx.get("https://www.xiongan.gov.cn/ds_tzgg_test.json").respond(json={
        "datasource": [{
            "title": "普通话水平测试公告",
            "publishUrl": "./20260829/id/c.html",
            "publishTime": "2026-08-29 09:00:00",
            "contentType": "MultiMedia",
        }]
    })
    adapter = XionganPortalAdapter()
    result = adapter.fetch_list(category="tzgg", since="2026-08-28")
    assert result.items[0].title == "普通话水平测试公告"
    assert result.coverage.stop_reason == "source_exhausted"


@respx.mock
def test_tzgg_without_datasource_or_article_links_is_invalid_page():
    respx.get("https://www.xiongan.gov.cn/tzgg.html").respond(text="<html><body>changed</body></html>")
    result = XionganPortalAdapter().fetch_list(category="tzgg", since="2026-08-28")
    assert result.coverage.stop_reason == "invalid_page"
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/collector/test_xiongan_portal.py -q`

Expected: the first test raises `ValueError` because `datasource_path` is absent; the second cannot return coverage metadata.

- [ ] **Step 3: Implement datasource discovery with HTML fallback**

Add:

```python
_DATASOURCE_RE = re.compile(r'["\']([^"\']*ds_[a-zA-Z0-9_-]+\.json)["\']')
_ARTICLE_RE = re.compile(r"/\d{8}/[a-f0-9]{20,}/c\.html$")

def _discover_category_source(self, cat_cfg: dict) -> tuple[str | None, str]:
    page_url = urljoin(self.BASE + "/", cat_cfg["list_url"])
    html = self._get(page_url).text
    match = _DATASOURCE_RE.search(html)
    if match:
        return urljoin(page_url, match.group(1)), html
    return None, html
```

If no datasource is found, extract article anchors matching `_ARTICLE_RE`; if neither a datasource nor a recognizable article-list container exists, return `invalid_page`. Iterate all datasource entries, track whether an older item was observed, and return `date_boundary` or `source_exhausted` rather than applying `INITIAL_BATCH`.

Set `coverage_contract_version = 1` and change the portal `_get()` method to call `_before_request()` so category-list and article-detail calls share the total request budget.

Add `initial_page_budget: 5`, `hard_page_limit: 20`, `max_requests_per_run: 120`, and `bootstrap_lookback_days: 7` to the portal source configuration.

- [ ] **Step 4: Remove the silent `datasource_path` skip in `run()`**

Change the category loop so every configured category calls `_run_category()`. A missing/unparseable `tzgg` produces a category run with `coverage_status=incomplete` and increments aggregate errors without blocking the other categories.

- [ ] **Step 5: Verify portal and end-to-end tests**

Run: `pytest tests/collector/test_xiongan_portal.py tests/e2e/test_collect_e2e.py tests/collector/test_retry_queue.py -q`

Expected: all tests pass; fixtures explicitly mock the `tzgg` list response.

- [ ] **Step 6: Commit portal coverage**

```bash
git add collector/adapters/xiongan_portal.py config/sources.yaml tests/collector/test_xiongan_portal.py tests/collector/fixtures.py tests/e2e/test_collect_e2e.py
git commit -m "fix: cover all xiongan portal categories"
```

---

### Task 5: Make WeChat Pagination Block-Aware and Bounded

**Files:**
- Modify: `collector/adapters/wechat_search.py`
- Create: `tests/collector/test_wechat_search.py`
- Modify: `config/sources.yaml:59-95`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: `page`, `results_per_page`, page/request budgets.
- Produces: fully deduplicated `ListFetchResult`; block pages always produce `blocked`.

- [ ] **Step 1: Add failing pagination and anti-spider tests**

```python
# tests/collector/test_wechat_search.py
import respx

from collector.adapters.wechat_search import XionganFabuAdapter


def _result_page(title, date, next_page=None):
    next_link = f'<a id="sogou_next" href="/weixin?page={next_page}">下一页</a>' if next_page else ""
    return f'''<html><body><div class="news-box"><div class="txt-box">
      <h3><a href="/link?url={title}">{title}</a></h3>
      <p class="txt-info">summary</p><div class="s-p"><span class="s2">{date}</span></div>
    </div>{next_link}</div></body></html>'''


@respx.mock
def test_fetches_multiple_pages_and_filters_only_after_scan():
    route = respx.get("https://weixin.sogou.com/weixin")
    route.side_effect = [
        __import__("httpx").Response(200, text=_result_page("old", "2026-08-01", 2)),
        __import__("httpx").Response(200, text=_result_page("new", "2026-09-03")),
    ]
    result = XionganFabuAdapter().fetch_list(since="2026-08-29", page_budget=2)
    assert [item.title for item in result.items] == ["new"]
    assert result.coverage.pages_fetched == 2
    assert result.coverage.stop_reason == "source_exhausted"


@respx.mock
def test_followed_200_antispider_page_is_blocked():
    respx.get("https://weixin.sogou.com/weixin").respond(
        200, text='<html><script src="static/js/antispider.min.js"></script><p>访问过于频繁</p></html>',
    )
    result = XionganFabuAdapter().fetch_list(since="2026-08-29", page_budget=2)
    assert result.coverage.stop_reason == "blocked"


@respx.mock
def test_budget_with_next_page_returns_continuation():
    respx.get("https://weixin.sogou.com/weixin").respond(
        200, text=_result_page("new", "2026-09-03", 2),
    )
    result = XionganFabuAdapter().fetch_list(since="2026-08-29", page_budget=1)
    assert result.coverage.stop_reason == "page_limit"
    assert result.coverage.continuation_page == 2
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/collector/test_wechat_search.py -q`

Expected: tests fail because only page 1 is requested and antispider HTML is treated as an empty success.

- [ ] **Step 3: Implement response classification and pagination**

Add `_is_blocked_response()` checking final URL path, response history locations, status 403/429, `antispider`, `captcha`, `访问过于频繁`, and `请输入验证码`. Loop from `start_page` through the effective page budget, require either recognized result boxes, a recognized no-result marker, or a next-page control, and do not stop merely because an old-dated result appears. Deduplicate by normalized `(title, publish_date)` plus the stable `url=` target when present.

Set `coverage_contract_version = 1`. Route every search and detail request through `_before_request()` before the HTTP call. Catch `RequestBudgetExceeded` in the page loop and return `CoverageMeta("request_budget", continuation_page=current_page)`.

Use the requested jitter without changing QPS:

```python
import random

def _wechat_throttle(self):
    self._throttle()
    time.sleep(random.uniform(0.0, 2.0))
```

Tests patch `time.sleep` and `random.uniform` to remain instant and deterministic.

- [ ] **Step 4: Migrate WeChat configuration**

For all five WeChat entries, replace `max_results: 10` with:

```yaml
results_per_page: 10
initial_page_budget: 2
hard_page_limit: 10
max_requests_per_run: 30
bootstrap_lookback_days: 7
```

In code, read `results_per_page`; if absent, fall back to `max_results` and emit `logger.warning("max_results is deprecated; use results_per_page")`.

- [ ] **Step 5: Verify WeChat and configuration tests**

Run: `pytest tests/collector/test_wechat_search.py tests/collector/test_config.py tests/test_network_guard.py -q`

Expected: all tests pass and no real network request occurs.

- [ ] **Step 6: Commit WeChat coverage**

```bash
git add collector/adapters/wechat_search.py config/sources.yaml tests/collector/test_wechat_search.py tests/conftest.py
git commit -m "fix: make wechat collection block aware"
```

---

### Task 6: Migrate Every HTML Adapter to Verifiable Pagination

**Files:**
- Create: `collector/adapters/pagination.py`
- Modify: `collector/adapters/rmxiongan.py`
- Modify: `collector/adapters/hebccw.py`
- Modify: `collector/adapters/rongcheng.py`
- Modify: `collector/adapters/xiongxian.py`
- Modify: `collector/adapters/anxin.py`
- Modify: `config/sources.yaml:23-57`
- Modify: corresponding `tests/collector/test_*.py`
- Modify: `tests/collector/fixtures.py`

**Interfaces:**
- Produces: `find_next_page(soup, current_url) -> tuple[str | None, bool]`, where the boolean says a recognized pagination container/control set was present.
- Every enabled HTML adapter returns `ListFetchResult` and accepts `start_page`/`page_budget`.

- [ ] **Step 1: Write failing generic pagination tests**

```python
# add to tests/collector/test_pagination.py
from bs4 import BeautifulSoup
from collector.adapters.pagination import find_next_page


def test_finds_rel_next():
    soup = BeautifulSoup('<a rel="next" href="page2.html">下一页</a>', "html.parser")
    assert find_next_page(soup, "https://example.test/news/page1.html") == (
        "https://example.test/news/page2.html", True,
    )


def test_finds_chinese_next_inside_pager():
    soup = BeautifulSoup('<div class="pagination"><a href="/news/2">下一页</a></div>', "html.parser")
    assert find_next_page(soup, "https://example.test/news/1") == (
        "https://example.test/news/2", True,
    )


def test_no_known_pager_is_not_proof_of_exhaustion():
    soup = BeautifulSoup('<ul><li>article</li></ul>', "html.parser")
    assert find_next_page(soup, "https://example.test/news") == (None, False)
```

- [ ] **Step 2: Verify RED, then implement the helper**

Run: `pytest tests/collector/test_pagination.py -q`

Expected: import fails. Implement selectors for `a[rel=next]`, `.pagination`, `.page`, `.pager`, and links whose normalized text is `下一页`, `下页`, `>` or `»`; return `(None, True)` when a known pager exists but no enabled next link remains.

- [ ] **Step 3: Add a two-page boundary test to each adapter**

Use the existing source fixture as page 1, add a recognized next link, and return page 2 containing one item older than `since`. Each assertion follows this form:

```python
result = adapter.fetch_list(since="2026-07-05", page_budget=2)
assert result.coverage.pages_fetched == 2
assert result.coverage.stop_reason == "date_boundary"
assert all(item.publish_date >= "2026-07-05" for item in result.items if item.publish_date)
```

For Anxin, add a separate test where a recognized single-page pager has no next link, list dates are blank, detail dates are returned, and `BaseAdapter.run()` finalizes `source_exhausted` as complete. An unrecognized page with articles but no known pager must return `invalid_page`, not `source_exhausted`.

- [ ] **Step 4: Verify adapter tests fail for the expected pagination reason**

Run: `pytest tests/collector/test_rmxiongan.py tests/collector/test_hebccw.py tests/collector/test_rongcheng.py tests/collector/test_xiongxian.py tests/collector/test_anxin.py -q`

Expected: new tests fail because each adapter currently reads one page and returns a list.

- [ ] **Step 5: Implement the same bounded loop in all five adapters**

Each adapter must:

```python
items = []
seen_urls = set()
current_url = first_url
pages_fetched = 0
for _ in range(page_budget):
    response = self._get(current_url)
    soup = BeautifulSoup(response.text, "html.parser")
    page_items = self._parse_list_page(soup)
    next_url, pager_known = find_next_page(soup, current_url)
    pages_fetched += 1
    # append unseen in-range items; remember whether an older dated item appeared
    if older_seen:
        return ListFetchResult(items, CoverageMeta("date_boundary", pages_fetched=pages_fetched, ...))
    if pager_known and not next_url:
        return ListFetchResult(items, CoverageMeta("source_exhausted", pages_fetched=pages_fetched, ...))
    if not pager_known:
        return ListFetchResult(items, CoverageMeta("invalid_page", pages_fetched=pages_fetched, ...))
    current_url = next_url
return ListFetchResult(items, CoverageMeta("page_limit", pages_fetched=pages_fetched, continuation_page=start_page + pages_fetched, ...))
```

Extract each adapter's existing item parsing into `_parse_list_page()` without changing title, URL, date, or detail parsing behavior. Remove every `INITIAL_BATCH` truncation.

Set `coverage_contract_version = 1` on every migrated adapter and replace each `_get()` call to `_throttle()` with `_before_request()`.

For each of the five HTML sources, add `initial_page_budget: 5`, `hard_page_limit: 20`, `max_requests_per_run: 100`, and `bootstrap_lookback_days: 7` to `config/sources.yaml`.

- [ ] **Step 6: Verify all enabled adapters satisfy the contract**

Run: `pytest tests/collector -q`

Expected: all collector tests pass, including a parametrized contract test that calls each enabled adapter with mocked responses and asserts `adapter.coverage_contract_version == 1` and `isinstance(result, ListFetchResult)`.

After that test is green, remove Task 3's temporary branch for adapters without `coverage_contract_version = 1`. Any non-`ListFetchResult` return now always produces `incomplete/invalid_result`. Re-run `pytest tests/collector tests/e2e/test_collect_e2e.py -q` and require all tests to pass before committing.

- [ ] **Step 7: Commit HTML source migration**

```bash
git add collector/adapters config/sources.yaml tests/collector
git commit -m "fix: paginate enabled html sources"
```

---

### Task 7: Scheduler Backoff, Status API, and Coverage Anomaly Signal

**Files:**
- Modify: `web/api/collect.py:50-99`
- Modify: `web/app.py:80-180`
- Modify: `storage/models.py`
- Create: `tests/web/test_collect_coverage.py`
- Modify: `tests/web/test_api.py`

**Interfaces:**
- Produces: status payload fields `coverage_status`, `stop_reason`, `next_retry_at`, `needs_attention`, and `suspected_incomplete`.
- Scheduler consumes `CrawlRun.blocked_until()` and skips a source until that timestamp.

- [ ] **Step 1: Write failing API and scheduler tests**

```python
def test_collect_status_exposes_coverage(client):
    run = CrawlRun.start("xiongan_portal")
    run.finish(
        new_count=0, error_count=0, status="success",
        coverage_status="incomplete", stop_reason="request_budget",
        consecutive_incomplete=3, needs_attention=True,
    )
    body = client.get("/api/collect/status?source=xiongan_portal").json()["last_run"]
    assert body["coverage_status"] == "incomplete"
    assert body["needs_attention"] is True


def test_scheduled_collection_skips_source_during_backoff(monkeypatch):
    monkeypatch.setattr(CrawlRun, "blocked_until", lambda *_args, **_kwargs: "2999-01-01T00:00:00")
    called = []
    monkeypatch.setattr("web.api.collect._build_adapter", lambda source: called.append(source))
    _scheduled_crawl_all()
    assert called == []
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/web/test_collect_coverage.py tests/web/test_api.py -q`

Expected: coverage fields/backoff behavior are absent.

- [ ] **Step 3: Add backoff gate used by manual and scheduled collection**

```python
def source_is_backing_off(source: str, *, now: datetime | None = None) -> bool:
    retry_at = CrawlRun.blocked_until(source)
    if not retry_at:
        return False
    return datetime.fromisoformat(retry_at) > (now or datetime.now())
```

Manual trigger returns HTTP 429 with `detail="source temporarily backed off"`. Scheduled loops log one line and continue to the next source.

- [ ] **Step 4: Add deterministic anomaly calculation**

Add `Document.daily_insert_counts(source, before_date, weekdays=4)` and mark `suspected_incomplete` only when four same-weekday historical samples exist and today's first-inserted count is less than 50% of their median. The calculation groups unique rows by `publish_date`; it never uses scan count or `crawl_runs.new_count`.

```python
def suspected_incomplete(current: int, history: list[int]) -> bool:
    if len(history) < 4:
        return False
    return current < statistics.median(history[-4:]) * 0.5
```

Expose the flag in `/collect/status`; do not send notifications.

- [ ] **Step 5: Verify web and scheduler tests**

Run: `pytest tests/web/test_collect_coverage.py tests/web/test_api.py tests/web/test_job_lock.py tests/web/test_health.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit operational safeguards**

```bash
git add web/api/collect.py web/app.py storage/models.py tests/web/test_collect_coverage.py tests/web/test_api.py
git commit -m "feat: expose crawl completeness health"
```

---

### Task 8: Full Regression, Packaging, and Live Read-Only Smoke Check

**Files:**
- Modify only files required by failures directly caused by Tasks 1–7.
- Update: `docs/technical-implementation.md` with new configuration and status fields.

**Interfaces:**
- Validates the complete system; introduces no new behavior.

- [ ] **Step 1: Run the complete offline suite**

Run: `pytest -q`

Expected: all tests pass with zero failures and no external network access.

- [ ] **Step 2: Run packaging validation**

Run: `tmp_dir=$(mktemp -d) && python -m pip wheel . --no-deps --wheel-dir "$tmp_dir/dist"`

Expected: the wheel builds successfully and includes `collector/coverage.py` plus `config/sources.yaml`.

- [ ] **Step 3: Verify schema migration on a disposable production-DB copy**

```bash
tmp_dir=$(mktemp -d)
cp data/xac.db "$tmp_dir/xac.db"
DATA_DIR="$tmp_dir" python -c 'from storage.models import init_db; init_db()'
sqlite3 "$tmp_dir/xac.db" "PRAGMA integrity_check; PRAGMA table_info(crawl_runs);"
```

Expected: `ok`, followed by all coverage columns; the real database is unchanged.

- [ ] **Step 4: Run one read-only live list smoke check per source class**

Use a temporary `DATA_DIR`, explicit `since` equal to today, the minimum page budget, and normal QPS. Do not bypass any block page. Expected outcomes are either `complete`, `incomplete` with a concrete reason, or `blocked`; an empty HTTP 200 page must never be reported as a silent complete success.

- [ ] **Step 5: Document operator-visible behavior**

Add exact YAML keys, defaults, stop-reason mapping, cold-start window, continuation behavior, and `/api/collect/status` response fields to `docs/technical-implementation.md`.

- [ ] **Step 6: Re-run focused tests after documentation-adjacent fixes**

Run: `pytest tests/collector tests/storage/test_crawl_coverage.py tests/web/test_collect_coverage.py -q`

Expected: all tests pass.

- [ ] **Step 7: Commit verification documentation**

```bash
git add docs/technical-implementation.md
git commit -m "docs: document adaptive crawl coverage"
```

- [ ] **Step 8: Record final evidence**

Run:

```bash
git status --short
git log --oneline master..HEAD
git diff --check master...HEAD
```

Expected: clean status, a readable task-by-task commit series, and no whitespace errors.
