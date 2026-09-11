# Source Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover date-bounded collection from the two inaccessible government sites and prevent undated WeChat search results from polluting a requested date range.

**Architecture:** Keep each adapter responsible for its source-specific transport and parsing. Rongcheng retries only its official host through the locally available `curl` binary after an `httpx` TLS handshake failure; Anxin permits certificate bypass only after confirming the request host is its official host. The WeChat adapter owns deterministic date normalization and passes list dates through the existing BaseAdapter fallback path.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup, pytest, respx, system curl.

## Global Constraints

- Preserve strict TLS verification for all adapters except the documented Anxin official-host fallback.
- Never pass a non-official hostname to the Rongcheng curl fallback or the Anxin insecure client.
- For a `since` run, discard WeChat results whose date is missing or older than `since`.
- Do not add runtime Python dependencies.

---

### Task 1: Add source-scoped government-site transport recovery

**Files:**
- Modify: `collector/adapters/rongcheng.py`
- Modify: `collector/adapters/anxin.py`
- Modify: `tests/collector/test_rongcheng.py`
- Modify: `tests/collector/test_anxin.py`

**Interfaces:**
- Produces: each adapter's `_get(url: str) -> httpx.Response` continues returning a successful HTML response or raises a request error.
- Consumes: existing `BASE` constants and `BaseAdapter._throttle()`.

- [ ] **Step 1: Write failing transport tests**

```python
def test_rongcheng_get_rejects_non_official_host():
    with pytest.raises(ValueError, match="official host"):
        RongchengAdapter()._get("https://example.com/article")

def test_anxin_get_uses_insecure_client_only_for_official_host():
    adapter = AnxinAdapter()
    with pytest.raises(ValueError, match="official host"):
        adapter._get("https://example.com/article")
```

- [ ] **Step 2: Run tests to verify the host guard is absent**

Run: `conda run -n xa-info-collector pytest tests/collector/test_rongcheng.py tests/collector/test_anxin.py -v`

Expected: FAIL because `_get()` does not reject a foreign host.

- [ ] **Step 3: Implement the smallest host-scoped recovery**

```python
from urllib.parse import urlparse

def _assert_official_host(self, url: str) -> None:
    if urlparse(url).hostname != urlparse(self.BASE).hostname:
        raise ValueError("URL is not on the official host")
```

Call this guard at the beginning of both `_get()` methods. In `RongchengAdapter`, catch only `httpx.ConnectError` containing `SSLV3_ALERT_HANDSHAKE_FAILURE`, run `curl --fail --silent --show-error --location --max-time 30 <url>`, and construct an `httpx.Response(200, content=stdout, request=httpx.Request("GET", url))`. In `AnxinAdapter`, make a second `httpx.Client(verify=False, ...)` call only after a certificate-verification `httpx.ConnectError` from the guarded official host.

- [ ] **Step 4: Run focused tests**

Run: `conda run -n xa-info-collector pytest tests/collector/test_rongcheng.py tests/collector/test_anxin.py -v`

Expected: PASS.

### Task 2: Make WeChat date-range collection deterministic

**Files:**
- Modify: `collector/adapters/wechat_search.py`
- Create: `tests/collector/test_wechat_search.py`

**Interfaces:**
- Produces: `_parse_publish_date(date_text: str, today: date | None = None) -> str` returning `YYYY-MM-DD` or `""`.
- Consumes: Sogou result date strings and `fetch_list(since)`.

- [ ] **Step 1: Write failing parser and range-filter tests**

```python
def test_parse_publish_date_supports_absolute_and_relative_dates():
    today = date(2026, 9, 11)
    assert _parse_publish_date("2026-09-09", today) == "2026-09-09"
    assert _parse_publish_date("昨天", today) == "2026-09-10"
    assert _parse_publish_date("3天前", today) == "2026-09-08"

def test_fetch_list_since_skips_undated_and_old_items():
    items = WechatSearchAdapter().fetch_list(since="2026-09-05")
    assert [item.publish_date for item in items] == ["2026-09-09"]
```

- [ ] **Step 2: Run the new test file**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py -v`

Expected: FAIL because no parser exists and undated items are retained.

- [ ] **Step 3: Implement parsing and strict `since` filtering**

```python
if since:
    if not publish_date or publish_date < since:
        continue
```

Use `_parse_publish_date()` for the Sogou date span. Preserve the parsed list date in `ListItem`; the existing `BaseAdapter._ingest_detail()` already uses it whenever WeChat's detail response has no date.

- [ ] **Step 4: Run WeChat tests**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py -v`

Expected: PASS.

### Task 3: Regression verification and bounded recovery

**Files:**
- No code changes.

- [ ] **Step 1: Run the affected collector suite**

Run: `conda run -n xa-info-collector pytest tests/collector/test_rongcheng.py tests/collector/test_anxin.py tests/collector/test_wechat_search.py -v`

Expected: all selected tests pass.

- [ ] **Step 2: Run date-bounded source recovery**

Run: `conda run -n xa-info-collector python -c 'from storage.models import init_db, close_db; from web.api.collect import _build_adapter; init_db(); [print(s, _build_adapter(s).run(since="2026-09-05")) for s in ("rongcheng_gov", "anxin_gov", "wechat_xiongan_fabu", "wechat_rongcheng_fabu", "wechat_xiongzhou_voice", "wechat_yanling_voice", "wechat_xiongan_edu")]; close_db()'`

Expected: the two government adapters complete successfully; every newly inserted WeChat document has a non-empty date on or after `2026-09-05`.

- [ ] **Step 3: Verify database bounds**

Run: `conda run -n xa-info-collector python -c 'from storage.models import init_db; from storage.database import get_conn; init_db(); c=get_conn(); print(c.execute("SELECT source, COUNT(*) FROM documents WHERE source LIKE ? AND (publish_date = ? OR publish_date < ?) GROUP BY source", ("wechat_%", "", "2026-09-05")).fetchall())'`

Expected: no newly recovered WeChat rows fall outside the requested range.
