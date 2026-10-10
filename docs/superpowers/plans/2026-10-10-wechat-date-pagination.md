# 微信公众号按日期分页采集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不提高搜狗请求频率的前提下，分页采集指定日期范围内的公众号搜索结果，并在软封、验证码或无效页面时冻结游标。

**Architecture:** `WechatSearchAdapter` 在适配器内串行请求 1-based 搜狗页码，跨页去重并只在整页均出界时停止。反爬和无效首页以异常返回给既有 `BaseAdapter.run()`，复用其失败运行与游标冻结逻辑；正常的后续空页才被视为来源穷尽。

**Tech Stack:** Python 3.11、httpx、BeautifulSoup、pytest、respx、PyYAML、SQLite。

## Global Constraints

- 不提高现有公众号来源 `qps: 0.2`；每次 HTTP 请求都必须经 `BaseAdapter._throttle()`。
- 搜狗页码使用 `page=N`，从 1 开始；带日期下界的单轮硬上限为 5 页，绝不超过 10 页。
- `initial_page_budget: 2` 仅限制无 `since` 的冷启动；冷启动不构成完整历史回填。
- `results_per_page: 10` 与 `hard_page_limit: 5` 推导默认跨页总量上限；五个公众号来源显式设置 `max_results: 50`。
- `SogouBlockedError`、无效页和网络请求异常必须使既有 `CrawlRun` 失败，因而不得推进 `last_crawled_date`。
- 手动日期回填的游标隔离由后续范围运行 `run(since, until)` 工作承担；本任务不修改 `BaseAdapter.run()` 的签名或范围 API。

---

### Task 1: 迁移微信公众号分页配置

**Files:**
- Modify: `config/sources.yaml:75-122`
- Modify: `tests/collector/test_config.py`

**Interfaces:**
- Consumes: `collector.config.load_sources_config()`。
- Produces: 五个 `wechat_*` 来源的 `initial_page_budget: int`、`hard_page_limit: int`、`results_per_page: int` 和 `max_results: int` 配置。

- [ ] **Step 1: 写失败配置合同测试**

```python
from collector.config import load_sources_config

def test_wechat_sources_define_bounded_pagination_settings():
    sources = load_sources_config()
    for name, cfg in sources.items():
        if not name.startswith("wechat_"):
            continue
        assert cfg["initial_page_budget"] == 2
        assert cfg["hard_page_limit"] == 5
        assert cfg["results_per_page"] == 10
        assert cfg["max_results"] == 50
        assert cfg["max_results"] == cfg["results_per_page"] * cfg["hard_page_limit"]
```

- [ ] **Step 2: 确认测试失败**

Run: `conda run -n xa-info-collector pytest tests/collector/test_config.py::test_wechat_sources_define_bounded_pagination_settings -v`

Expected: FAIL，当前五个公众号来源仅有 `max_results: 10`。

- [ ] **Step 3: 迁移五个来源的配置**

将每个 `wechat_*` 条目的旧 `max_results: 10` 替换为：

```yaml
    initial_page_budget: 2
    hard_page_limit: 5
    results_per_page: 10
    max_results: 50
```

不得在任一公众号来源保留旧的单页 `max_results: 10` 语义。

- [ ] **Step 4: 验证配置合同**

Run: `conda run -n xa-info-collector pytest tests/collector/test_config.py -v`

Expected: PASS。

- [ ] **Step 5: 提交配置迁移**

Run: `git add config/sources.yaml tests/collector/test_config.py && git commit -m "feat: configure bounded WeChat pagination"`

### Task 2: 以测试先行实现分页、边界与跨页去重

**Files:**
- Modify: `collector/adapters/wechat_search.py:1-130`
- Modify: `tests/collector/test_wechat_search.py`

**Interfaces:**
- Consumes: `WechatSearchAdapter.fetch_list(since: str | None) -> list[ListItem]` 和来源分页配置。
- Produces: `SogouBlockedError(RuntimeError)`、`SogouInvalidPageError(RuntimeError)`；分页 `fetch_list` 仍返回 `list[ListItem]`。

- [ ] **Step 1: 写第二页、离群旧日期和 URL 去重的失败测试**

使用 `respx.route` 按 `request.url.params.get("page")` 返回页面。两个页面必须使用真实格式的日期：

```python
PAGE_1 = """
<div class="txt-box"><a href="/same">同一文章</a><span class="s2"><script>document.write(timeConvert('1791504000'))</script></span></div>
<div class="txt-box"><a href="/old">离群旧文章</a><span class="s2"><script>document.write(timeConvert('1790899200'))</script></span></div>
"""
PAGE_2 = """
<div class="txt-box"><a href="/same">同一文章</a><span class="s2"><script>document.write(timeConvert('1791504000'))</script></span></div>
<div class="txt-box"><a href="/second">第二页文章</a><span class="s2"><script>document.write(timeConvert('1791417600'))</script></span></div>
"""

def test_fetch_list_pages_past_single_old_outlier_and_deduplicates_urls():
    adapter = XionganFabuAdapter()
    items = adapter.fetch_list(since="2026-10-08")
    assert [item.url for item in items] == [
        "https://weixin.sogou.com/same",
        "https://weixin.sogou.com/second",
    ]
    assert requested_pages == ["1", "2"]
```

同一文件新增 `test_fetch_list_stops_after_a_full_page_is_before_since`：第 1 页有范围内文章，第 2 页所有已解析日期均早于 `since`，断言没有请求第 3 页。新增 `test_fetch_list_does_not_stop_on_an_undated_page`：第 2 页仅含无日期结果，断言仍会请求第 3 页，直至页限制或整页出界。

- [ ] **Step 2: 确认分页测试失败**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py -k "pages_past or full_page or undated_page" -v`

Expected: FAIL，当前实现没有 `page` 参数，也只请求一次首页。

- [ ] **Step 3: 实现最小分页循环**

在 `WechatSearchAdapter` 增加下列辅助方法，并让 `fetch_list` 使用它们：

```python
def _page_budget(self, since: str | None) -> int:
    configured = (self.config.get("hard_page_limit", 5) if since
                  else self.config.get("initial_page_budget", 2))
    return min(max(int(configured), 1), 10)

def _result_limit(self) -> int:
    page_size = int(self.config.get("results_per_page", 10))
    hard_limit = min(max(int(self.config.get("hard_page_limit", 5)), 1), 10)
    return min(int(self.config.get("max_results", page_size * hard_limit)),
               page_size * hard_limit)
```

每页请求参数必须为 `{"type": "2", "query": query, "ie": "utf8", "page": page}`。循环外建立 `seen_urls`，每页解析后：

```python
dated = [item.publish_date for item in page_items if item.publish_date]
in_range = [item for item in page_items if not since or item.publish_date >= since]
if since and dated and not any(value >= since for value in dated):
    break
```

将 `in_range` 中未见 URL 加入累计结果；达到 `_result_limit()` 时立即返回已截断的列表。无日期条目在带 `since` 时仍不加入结果，但不能参与日期边界的停止判定。

- [ ] **Step 4: 运行分页与原有日期回归**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py -v`

Expected: PASS。

- [ ] **Step 5: 提交分页行为**

Run: `git add collector/adapters/wechat_search.py tests/collector/test_wechat_search.py && git commit -m "feat: page WeChat search results by date"`

### Task 3: 以失败而非空结果处理反爬和可疑页面

**Files:**
- Modify: `collector/adapters/wechat_search.py`
- Modify: `tests/collector/test_wechat_search.py`

**Interfaces:**
- Consumes: `httpx.Response` 的 `status_code`、`url`、HTML 和既有 `BaseAdapter.run()` 异常分支。
- Produces: `SogouBlockedError`（验证码、`/antispider/`、403、429）、`SogouInvalidPageError`（首屏空页或无有效结构）；正常后续空页返回已累计结果。

- [ ] **Step 1: 写失败的阻断、无效页和游标保护测试**

```python
@respx.mock
def test_antispider_page_fails_run_and_preserves_previous_cursor():
    prior = CrawlRun.start("wechat_xiongan_fabu")
    prior.finish(new_count=1, error_count=0, last_crawled_date="2026-10-07")
    respx.get("https://weixin.sogou.com/weixin").respond(
        302, headers={"location": "/antispider/"})
    respx.get("https://weixin.sogou.com/antispider/").respond(
        200, text="<html><form id='seccodeForm'></form></html>")
    adapter = XionganFabuAdapter()
    with pytest.raises(SogouBlockedError):
        adapter.run(since="2026-10-08")
    assert CrawlRun.latest_by_source("wechat_xiongan_fabu").status == "failed"
    assert CrawlRun.get_last_crawled_date("wechat_xiongan_fabu") == "2026-10-07"
```

新增以下独立测试：`test_fetch_list_rejects_403_and_429_as_blocked`；`test_fetch_list_rejects_antispider_final_url_as_blocked`；`test_first_empty_result_page_is_invalid_and_does_not_advance_cursor`；`test_empty_page_after_nonempty_page_returns_collected_items`；`test_unrecognized_page_is_invalid_but_normal_result_page_is_not`；`test_timeout_or_5xx_uses_existing_request_error_path`。正常结果页负向夹具必须含 `.txt-box`，且无分页容器不得误触发无效页。

- [ ] **Step 2: 确认失败测试失败**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py -k "antispider or empty_result or unrecognized or rejects_403" -v`

Expected: FAIL，当前适配器将验证码 HTML 当作空列表返回，且没有专用异常类。

- [ ] **Step 3: 实现页面分类与异常**

```python
class SogouBlockedError(RuntimeError):
    pass

class SogouInvalidPageError(RuntimeError):
    pass

def _assert_search_page(self, response: httpx.Response, soup: BeautifulSoup,
                        page: int, saw_nonempty_page: bool) -> None:
    lowered = response.text.lower()
    if (response.status_code in (403, 429)
            or "/antispider/" in str(response.url)
            or "seccodeform" in lowered
            or "验证码" in response.text):
        raise SogouBlockedError(f"Sogou blocked search page {page}")
    boxes = soup.select("div.txt-box")
    has_search_shell = soup.select_one("#main, #main_container, #pagebar_container")
    if not boxes and not saw_nonempty_page:
        raise SogouInvalidPageError(f"suspicious_empty_first_page page={page}")
    if not boxes and not has_search_shell:
        raise SogouInvalidPageError(f"invalid_page page={page}")
```

在发起请求后、解析条目前调用该方法。让 HTTP 5xx 保持 `resp.raise_for_status()` 的现有 `httpx.HTTPStatusError`，不转为 `SogouBlockedError`。为异常日志加入来源与页码；不要吞掉异常或把异常页转换为空数组。

- [ ] **Step 4: 运行异常、游标及分页全套测试**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py tests/collector/test_crawl_retry.py -v`

Expected: PASS。

- [ ] **Step 5: 提交失败语义**

Run: `git add collector/adapters/wechat_search.py tests/collector/test_wechat_search.py && git commit -m "fix: preserve cursors on blocked WeChat pages"`

### Task 4: 集成验证与受限补采

**Files:**
- Modify: none

**Interfaces:**
- Consumes: Tasks 1–3 和现有 `scripts/backfill_range.py`。
- Produces: 经验证的按日期微信公众号采集能力。

- [ ] **Step 1: 运行受影响的完整测试集**

Run: `conda run -n xa-info-collector pytest tests/collector/test_wechat_search.py tests/collector/test_config.py tests/collector/test_crawl_retry.py -v`

Expected: PASS。

- [ ] **Step 2: 运行全量测试**

Run: `conda run -n xa-info-collector pytest -q`

Expected: PASS。

- [ ] **Step 3: 对单个公众号执行受限补采并检查游标**

Run:

```bash
PYTHONPATH=. conda run -n xa-info-collector python -c '
from storage.models import init_db, close_db
from collector.adapters.wechat_search import XionganFabuAdapter
init_db()
try:
    print(XionganFabuAdapter().run(since="2026-10-08"))
finally:
    close_db()
'
```

Expected: 仅按 5 秒间隔访问至多 5 页；若命中反爬或无效首页，命令非零退出且游标不推进；正常完成时仅保留发布日期不早于 2026-10-08 的文章。

- [ ] **Step 4: 检查工作区和提交历史**

Run: `git status --short && git log --oneline master..HEAD`

Expected: 仅有设计、计划和上述功能提交；不提交数据库、HTML 快照、图片或本地运行生成物。
