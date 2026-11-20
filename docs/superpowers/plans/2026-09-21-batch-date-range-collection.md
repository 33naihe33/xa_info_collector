# 批量日期范围抓取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持多选已启用信息源，并以必填日期闭区间安全地发起后台抓取，且不影响日常增量游标。

**Architecture:** 采集层以 `until is not None` 标识范围运行：跳过 pending 重试，在详情前归一化列表日期并按闭区间过滤，所有范围 CrawlRun 均不写游标。批量 API 复用 collect 锁，顺序运行 adapter；Vue 弹窗负责多选和日期输入。

**Tech Stack:** Python 3.11、FastAPI、pytest、SQLite、Vue 3、Pinia、Element Plus、TypeScript、Vite。

## Global Constraints

- 日期范围必须同时提供 `date_from`、`date_to`，且两端均包含。
- 范围运行不得重试 pending URL，也不得写入或回退 `last_crawled_date`。
- 复用单一 collect 锁；锁冲突为 HTTP 409，结构错误为 HTTP 422，业务校验错误为 HTTP 400。
- 多源运行必须顺序执行；一个源失败不能阻止其余源；定时抓取遇锁跳过属预期。
- 不修改现有单源增量“立即抓取”语义。

---

### Task 1: 范围运行核心与游标隔离

**Files:**

- Modify: `collector/base.py:158-217`
- Modify: `collector/adapters/xiongan_portal.py:36-108`
- Create: `tests/collector/test_date_range_collection.py`

**Interfaces:**

- Consumes: `BaseAdapter.fetch_list(since: str | None) -> list[ListItem]`、`CrawlRun.finish(...)`。
- Produces: `BaseAdapter.run(since: str | None = None, until: str | None = None) -> dict`；`XionganPortalAdapter.run(since: str | None = None, until: str | None = None) -> dict`。

- [ ] **Step 1: 写失败测试**

```python
def test_range_run_includes_bounds_skips_pending_and_preserves_cursor():
    adapter = FakeAdapter([ListItem("low", "https://test/low", "2026-09-08"), ListItem("inside", "https://test/in", "2026-09-09"), ListItem("high", "https://test/high", "2026-09-10"), ListItem("missing", "https://test/missing", "")])
    prior = CrawlRun.start("fake")
    prior.finish(new_count=1, error_count=0, last_crawled_date="2026-09-07")
    CrawlError.log("fake", "https://test/pending", "old error")
    adapter.run(since="2026-09-08", until="2026-09-10")
    assert adapter.ingested_urls == ["https://test/low", "https://test/in", "https://test/high"]
    assert "https://test/pending" not in adapter.ingested_urls
    assert CrawlRun.get_last_crawled_date("fake") == "2026-09-07"
```

同一测试文件再定义 `test_range_run_error_paths_preserve_cursor`：分别让 fake adapter 的 `_ingest_detail` 抛出异常（断言最新运行 `status == "success_with_errors"`、`CrawlRun.latest_by_source("fake").last_crawled_date is None`，且 `CrawlRun.get_last_crawled_date("fake") == "2026-09-07"`），以及让 `fetch_list` 抛出异常（断言 `status == "failed"`、该运行行的 `last_crawled_date is None`，且游标仍为 `2026-09-07`）。定义 `test_portal_range_run_preserves_category_cursors`：预先为 `zxyw`、`zcwj` 写入不同成功游标，mock 两个栏目列表并以 `until` 运行，断言两个 `CrawlRun.get_last_crawled_date("xiongan_portal", category=...)` 均保持原值。

- [ ] **Step 2: 确认测试失败**

Run: `conda run -n xa-info-collector pytest tests/collector/test_date_range_collection.py -v`

Expected: FAIL，因为 `run()` 尚无 `until`，范围运行仍会重试 pending 并更新游标。

- [ ] **Step 3: 实现最小范围语义**

为 `BaseAdapter.run` 添加 `until`，令 `is_range_run = until is not None`。范围运行跳过 `_retry_pending`；将 `item.publish_date` 归一化为 `YYYY-MM-DD`，空值或无法归一化、低于 `since`、高于 `until` 的条目均跳过；success、success_with_errors、failed 的 `last_crawled_date` 全部写 `None`。同步扩展雄安官网的 `run` 与 `_run_category`，传播 `until`，跳过全局和栏目 pending 重试，应用相同过滤和游标规则。

- [ ] **Step 4: 运行核心回归**

Run: `conda run -n xa-info-collector pytest tests/collector/test_date_range_collection.py tests/collector/test_crawl_retry.py tests/collector/test_category_isolation.py tests/collector/test_xiongan_portal.py -v`

Expected: PASS。

- [ ] **Step 5: 提交核心范围语义**

Run: `git add collector/base.py collector/adapters/xiongan_portal.py tests/collector/test_date_range_collection.py && git commit -m "feat: isolate date-range collection runs"`

### Task 2: 批量范围抓取 API 与锁语义

**Files:**

- Modify: `web/api/collect.py:1-85`
- Modify: `tests/e2e/test_full_stack.py:25-55`
- Modify: `tests/web/test_job_lock.py:20-34`

**Interfaces:**

- Consumes: `_build_adapter(source)`、`adapter.run(since=date_from, until=date_to)`、`try_acquire_collect()`。
- Produces: `POST /api/collect/range`，JSON `{sources: string[], date_from: string, date_to: string}`，成功返回 `{status: "started", source_count: int, sources: string[]}`。

- [ ] **Step 1: 写 API 失败测试**

```python
def test_range_trigger_validates_and_runs_selected_sources_in_order(client):
    first, second = MagicMock(), MagicMock()
    with patch("web.api.collect._build_adapter", side_effect=[first, second]):
        response = client.post("/api/collect/range", json={"sources": ["xiongan_portal", "rmxiongan"], "date_from": "2026-09-08", "date_to": "2026-09-10"})
    assert response.status_code == 200
    assert response.json()["source_count"] == 2
    first.run.assert_called_once_with(since="2026-09-08", until="2026-09-10")
    second.run.assert_called_once_with(since="2026-09-08", until="2026-09-10")
```

同一文件加入以下精确断言：`test_range_trigger_rejects_empty_sources`、`test_range_trigger_rejects_reversed_dates`、`test_range_trigger_rejects_unknown_or_disabled_source` 均断言 HTTP 400；`test_range_trigger_rejects_invalid_date_format` 提交 `date_from="2026/09/08"` 并断言 HTTP 422。`tests/web/test_job_lock.py` 新增与 `tests/e2e/test_full_stack.py` 相同的临时 SQLite `client` fixture：在创建 `TestClient` 前将 `web.app._scheduler = "disabled"`，创建 app 后复位，并在 yield 后关闭数据库。该文件新增 `test_range_trigger_returns_409_when_collect_locked`：预先获取 `_collect_lock`，在 `try` 内断言范围 API 返回 409，`finally` 必须释放该锁。`tests/e2e/test_full_stack.py` 新增 `test_range_trigger_continues_after_source_failure`：让第一个 mock adapter 的 `run` 抛 `RuntimeError`，断言第二个 adapter 的 `run(since="2026-09-08", until="2026-09-10")` 仍被调用；后台任务返回后断言 `try_acquire_collect()` 成功并立即 `release_collect()`，覆盖成功和源失败后的锁释放。

- [ ] **Step 2: 确认测试失败**

Run: `conda run -n xa-info-collector pytest tests/e2e/test_full_stack.py tests/web/test_job_lock.py -v`

Expected: FAIL，因为 `/api/collect/range` 尚不存在。

- [ ] **Step 3: 实现请求模型和后台批量任务**

新增 Pydantic `RangeCollectRequest(sources: list[str], date_from: date, date_to: date)`。在 `/collect/range` 中以 `date_from > date_to`、空选、未知或未启用源返回 400；锁失败返回 409。去重后按请求顺序传给后台任务，后台逐个 `_build_adapter(source).run(since=date_from.isoformat(), until=date_to.isoformat())`，每个 source 独立捕获并记录异常，外层 finally 释放一次锁。返回去重后的 sources 及其数量。

- [ ] **Step 4: 运行 API 与全链路回归**

Run: `conda run -n xa-info-collector pytest tests/e2e/test_full_stack.py tests/web/test_job_lock.py tests/e2e/test_collect_e2e.py -v`

Expected: PASS。

- [ ] **Step 5: 提交 API**

Run: `git add web/api/collect.py tests/e2e/test_full_stack.py tests/web/test_job_lock.py && git commit -m "feat: add batch date-range collection API"`

### Task 3: 信息源页面批量选择与日期弹窗

**Files:**

- Modify: `web/frontend/src/api/client.ts:1-230`
- Modify: `web/frontend/src/stores/collector.ts:1-30`
- Modify: `web/frontend/src/views/SourceStatus.vue:1-64`

**Interfaces:**

- Consumes: `POST /api/collect/range` 成功 payload 和 HTTP error `detail`。
- Produces: `apiClient.triggerRangeCollect(sources, dateFrom, dateTo)` 和 `store.triggerRangeCollect(...)`。

- [ ] **Step 1: 增加 API 类型与 Store 状态**

```ts
export interface RangeCollectResponse { status: 'started'; source_count: number; sources: string[] }
triggerRangeCollect: (sources: string[], dateFrom: string, dateTo: string) => api.post<RangeCollectResponse>('/collect/range', { sources, date_from: dateFrom, date_to: dateTo })
```

Store 添加独立 `rangeTriggerLoading`，在 `finally` 清除；单源 `triggerLoading` 保持不变。

- [ ] **Step 2: 实现弹窗与客户端校验**

在 `SourceStatus.vue` 页头增加“按范围抓取”主按钮与 Element Plus 弹窗。弹窗仅渲染 `enabledSources` 复选框，使用 `el-date-picker` 的 `daterange` 和 `value-format="YYYY-MM-DD"`；`submitRangeCollect` 要求至少一个来源和两个日期，成功消息采用返回的 `source_count`，关闭后 3 秒刷新；失败优先显示 Axios 返回的 `detail`。

- [ ] **Step 3: 构建并回归**

Run: `npm run build`

Workdir: `web/frontend`

Expected: exit 0。

Run: `conda run -n xa-info-collector pytest tests/e2e/test_full_stack.py -v`

Expected: PASS。

- [ ] **Step 4: 提交界面**

Run: `git add web/frontend/src/api/client.ts web/frontend/src/stores/collector.ts web/frontend/src/views/SourceStatus.vue && git commit -m "feat: add date-range source selection UI"`

### Task 4: 最终验证与运行态检查

**Files:**

- Modify: none

**Interfaces:**

- Consumes: Tasks 1-3。
- Produces: 已验证的范围抓取功能。

- [ ] **Step 1: 执行完整自动化测试**

Run: `conda run -n xa-info-collector pytest -q`

Expected: PASS。

- [ ] **Step 2: 重新构建并检查工作区**

Run: `npm run build && git status --short`

Workdir: `web/frontend`

Expected: build exit 0；工作区无遗漏源码变更。
