# Leadership Publish Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 向领导调研 LLM 请求传入文章发布日期，避免历史年份臆造造成当期调研漏记。

**Architecture:** 保持现有日期校验逻辑不变；只补足 LLM 上下文并收紧日期提示。已漏记的文章单独重跑领导调研提取。

**Tech Stack:** Python、pytest、SQLite、智谱 LLM。

## Global Constraints

- 不修改报告格式或报告生成器。
- 继续过滤与发布日期相差超过 7 天的回顾性报道。

---

### Task 1: 传递发布日期并覆盖回归

**Files:**
- Modify: `tests/analyzer/test_leadership_dates.py`
- Modify: `analyzer/leadership_extractor.py`
- Modify: `config/prompts/extract_leadership.txt`

- [ ] **Step 1: 写入失败测试**

```python
def test_request_context_includes_publish_date():
    mock = _mock_llm_visit("2026-07-20")
    extract_leadership(..., publish_date="2026-07-22", llm_client=mock)
    assert "发布日期：2026-07-22" in mock.chat_json.call_args.kwargs["user"]
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/analyzer/test_leadership_dates.py::test_request_context_includes_publish_date -v`

- [ ] **Step 3: 最小实现**

在 `extract_leadership` 的 LLM context 中加入 `发布日期：{publish_date}`，并要求提示词在正文没有完整日期时使用该发布日期。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/analyzer/test_leadership_dates.py -v`

### Task 2: 修复已漏记文章

**Files:**
- Runtime data: `data/xac.db`

- [ ] **Step 1: 对文档 270 重跑领导调研提取**

使用修复后的提示词及发布日期 `2026-08-28` 仅执行 leadership 子任务。

- [ ] **Step 2: 核验结果**

确认 `leadership_visits` 有 `source_doc_id=270` 的张国华记录，且 `visit_date` 为 `2026-08-28`。

