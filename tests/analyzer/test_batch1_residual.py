"""H-02 + M-01 + M-02 + H-01: 分析漏数/合约/重试/env 修复测试。"""
import os
import pytest
from unittest.mock import MagicMock
from storage.models import (
    init_db, close_db, Document, AnalysisTaskState, CrawlError, get_conn,
)


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(text="某企业落户雄安，总投资50亿"):
    return Document.create(
        source="x", doc_type="新闻", title="测试", url=f"http://t_{os.urandom(4).hex()}",
        publish_date="2026-07-10", raw_html="", text=text, content_hash=f"h_{os.urandom(4).hex()}",
    )


def _set_task(doc_id, task_type, status, attempt_count=0, next_retry_at=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, last_error, next_retry_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(doc_id, task_type) DO UPDATE SET status=excluded.status, attempt_count=excluded.attempt_count, next_retry_at=excluded.next_retry_at",
        (doc_id, task_type, status, attempt_count, "err", next_retry_at, "2026-07-10T00:00:00"),
    )
    conn.commit()


# ---- M-01: EntityLLMResult 空 dict 被拒 ----

def test_entity_schema_rejects_empty_dict():
    """M-01：空 dict {} 缺 entities/relations 键 → retryable_error（原默认值导致通过）。"""
    from analyzer.result import validate_llm_dict, EntityLLMResult
    bad = validate_llm_dict({}, schema=EntityLLMResult)
    assert bad is not None, "空 dict 应被拒（缺必需键）"
    assert bad.retryable


def test_entity_schema_requires_entities_key():
    """M-01：只有 relations 缺 entities → retryable。"""
    from analyzer.result import validate_llm_dict, EntityLLMResult
    bad = validate_llm_dict({"relations": []}, schema=EntityLLMResult)
    assert bad is not None
    assert bad.retryable


def test_entity_schema_accepts_valid_dict():
    """M-01：含 entities+relations 的 dict 通过。"""
    from analyzer.result import validate_llm_dict, EntityLLMResult
    bad = validate_llm_dict({"entities": [], "relations": []}, schema=EntityLLMResult)
    assert bad is None  # 通过


# ---- H-02: 崩溃恢复 reconcile ----

def test_reconcile_all_succeeded_but_not_marked():
    """H-02：三任务全 succeeded 但 is_analyzed=0 → analyze_document 补标 analyzed。"""
    from analyzer.pipeline import analyze_document
    doc = _make_doc()
    _set_task(doc.id, "entity", "succeeded")
    _set_task(doc.id, "opportunity", "succeeded")
    _set_task(doc.id, "leadership", "succeeded")
    # is_analyzed 保持 0（模拟崩溃）
    assert Document.get_by_id(doc.id).is_analyzed is False

    result = analyze_document(doc, llm_client=MagicMock())
    assert result["analyzed"] is True
    assert Document.get_by_id(doc.id).is_analyzed is True


def test_reconcile_permanent_error_not_dead_lettered():
    """H-02：permanent_error 但 dead_letter=0 → analyze_document 补标 dead_letter。"""
    from analyzer.pipeline import analyze_document
    doc = _make_doc()
    _set_task(doc.id, "entity", "succeeded")
    _set_task(doc.id, "opportunity", "permanent_error", attempt_count=5)
    _set_task(doc.id, "leadership", "succeeded")
    # dead_letter 保持 0（模拟崩溃）

    result = analyze_document(doc, llm_client=MagicMock())
    assert result.get("dead_letter") is True
    assert Document.get_by_id(doc.id).dead_letter is True


def test_candidate_selects_partial_succeeded_missing_rows():
    """H-02：部分 succeeded + 缺必要任务行 → 被 analyze_pending 选中。

    原候选 SQL 会漏掉这种状态（t.doc_id 非 NULL，无 pending/retryable）。
    """
    from analyzer.pipeline import analyze_pending
    doc = _make_doc()
    _set_task(doc.id, "entity", "succeeded")  # 只有 entity，缺 opportunity/leadership
    # 不设 has_pending/has_due_retryable → 原 SQL 会漏

    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [], "relations": []},
        {"is_opportunity": False},
        {"is_leadership_visit": False},
    ]
    stats = analyze_pending(llm_client=mock_llm, limit=5)
    assert stats["total"] >= 1, "缺任务行的文档应被选为候选（H-02）"


# ---- M-02: 空内容重试不标 retried ----

def test_retry_empty_content_not_marked_retried():
    """M-02：重试时详情页空内容 → skipped → 不标 retried（继续 pending）。"""
    from collector.base import BaseAdapter, ListItem
    # 直接测 _retry_pending 对 skipped 的处理
    url = "http://example.com/empty-retry"
    CrawlError.log("test_src", url, "first fail", category="zxyw")
    # 清 next_retry_at 模拟到期
    conn = get_conn()
    conn.execute("UPDATE crawl_errors SET next_retry_at=NULL WHERE url=?", (url,))
    conn.commit()

    # mock adapter：_ingest_detail 返回 skipped
    adapter = MagicMock(spec=BaseAdapter)
    adapter.source_name = "test_src"
    adapter._ingest_detail.return_value = MagicMock(kind="skipped", is_success=False)

    # 手动调用 _retry_pending 的逻辑（通过方法绑定）
    BaseAdapter._retry_pending(adapter, category="zxyw", limit=5)

    # M-02：应 CrawlError.log（继续 pending），不是 mark_retried
    # log 会设 next_retry_at（退避），清空模拟到期后查 pending
    conn = get_conn()
    conn.execute("UPDATE crawl_errors SET next_retry_at=NULL WHERE url=?", (url,))
    conn.commit()
    pending = CrawlError.list_pending("test_src", category="zxyw")
    assert any(p["url"] == url for p in pending), "空内容应保持 pending（不标 retried）"


# ---- H-01: LLM env 加载 ----

def test_require_api_key_exits_when_missing(monkeypatch):
    """H-01：缺 ZHIPUAI_API_KEY 时 require_api_key 抛 SystemExit。"""
    from analyzer.env import require_api_key
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ZHIPUAI_API_KEY"):
        require_api_key()


def test_load_env_loads_dotenv(tmp_path, monkeypatch):
    """H-01：load_env 能从 .env 文件加载变量。"""
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_VAR_H01=loaded_value\n")
    monkeypatch.delenv("TEST_VAR_H01", raising=False)
    import analyzer.env as envmod
    envmod._loaded = False  # 重置
    envmod.load_env(str(env_file))
    assert os.environ.get("TEST_VAR_H01") == "loaded_value"
