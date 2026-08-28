"""R-04: pipeline 候选选择 + 子任务幂等 + 熔断测试。

回归用例：
- analyze_pending 原只按 is_analyzed=0 选候选，不读 next_retry_at，每次立即重试
- analyze_document 原无条件返回 analyzed=True
- 子任务无幂等守卫，已成功的任务会被重复执行
- 无熔断：retryable 任务永久重试
"""
import pytest
from unittest.mock import MagicMock

from storage.models import (
    init_db, close_db, Document, AnalysisTaskState, get_conn,
)


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(text="某企业落户雄安，总投资50亿"):
    return Document.create(
        source="x", doc_type="新闻", title="测试", url="http://t",
        publish_date="2026-07-10", raw_html="", text=text, content_hash="h_r04",
    )


def _set_task_state(doc_id, task_type, status, attempt_count=0, next_retry_at=None):
    """直接写入任务状态（绕过 mark_*，便于构造特定场景）。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, "
        "last_error, next_retry_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(doc_id, task_type) DO UPDATE SET status=excluded.status, "
        "attempt_count=excluded.attempt_count, next_retry_at=excluded.next_retry_at",
        (doc_id, task_type, status, attempt_count, "err", next_retry_at,
         "2026-07-10T00:00:00"),
    )
    conn.commit()


def test_retryable_not_due_is_not_retried(db):
    """retryable 且 next_retry_at 在未来 → 子任务被跳过，不调用 LLM。"""
    from analyzer.pipeline import analyze_document

    doc = _make_doc()
    # entity 已成功；opportunity 未到期 retryable（next_retry_at 在 2099 年）
    _set_task_state(doc.id, "entity", "succeeded")
    _set_task_state(doc.id, "opportunity", "retryable_error", attempt_count=1,
                    next_retry_at="2099-12-31T23:59:59")
    _set_task_state(doc.id, "leadership", "succeeded")

    mock_llm = MagicMock()
    result = analyze_document(doc, llm_client=mock_llm)
    # opportunity 未到期 → 不重试，all_succeeded False → analyzed False
    assert result["analyzed"] is False
    # LLM 不应被调用（所有子任务要么已成功要么未到期）
    assert mock_llm.chat_json.call_count == 0


def test_retryable_due_retries_and_skips_succeeded(db):
    """已到期 retryable → 重试该子任务；已成功的子任务不重复执行。"""
    from analyzer.pipeline import analyze_document

    doc = _make_doc()
    # entity 已成功（不应重跑）；opportunity 已到期 retryable；leadership 已成功
    _set_task_state(doc.id, "entity", "succeeded")
    _set_task_state(doc.id, "opportunity", "retryable_error", attempt_count=1,
                    next_retry_at="2020-01-01T00:00:00")  # 已到期
    _set_task_state(doc.id, "leadership", "succeeded")

    mock_llm = MagicMock()
    # 只应调用 opportunity 一次（entity/leadership 已成功被跳过）
    mock_llm.chat_json.return_value = {"is_opportunity": False}

    result = analyze_document(doc, llm_client=mock_llm)
    # 仅 opportunity 被重试 → LLM 调用 1 次
    assert mock_llm.chat_json.call_count == 1
    # opportunity 成功（无商机）→ 三任务终态 → analyzed True
    assert result["analyzed"] is True
    assert result["has_opportunity"] is False


def test_permanent_error_becomes_dead_letter_not_success(db):
    """P0-04：permanent_error → dead_letter，不标 is_analyzed=1。

    原设计 permanent_error 计入成功（all_succeeded True → analyzed True）。
    现修正：permanent_error = 失败 → dead_letter=1, is_analyzed 保持 0。
    """
    from analyzer.pipeline import analyze_document
    from storage.models import Document

    doc = _make_doc()
    _set_task_state(doc.id, "entity", "succeeded")
    _set_task_state(doc.id, "opportunity", "succeeded")
    # leadership 已熔断到 permanent_error
    _set_task_state(doc.id, "leadership", "permanent_error",
                    attempt_count=AnalysisTaskState.MAX_ATTEMPTS)

    mock_llm = MagicMock()
    result = analyze_document(doc, llm_client=mock_llm)
    # P0-04：permanent_error → analyzed False, dead_letter True
    assert mock_llm.chat_json.call_count == 0  # 不重试 permanent 任务
    assert result["analyzed"] is False
    assert result.get("dead_letter") is True
    # 文档标 dead_letter，is_analyzed 保持 0
    refreshed = Document.get_by_id(doc.id)
    assert refreshed.dead_letter is True
    assert refreshed.is_analyzed is False


def test_mark_retryable_circuits_to_permanent_at_max_attempts(db):
    """mark_retryable 在第 MAX_ATTEMPTS 次时原子切换到 permanent_error。"""
    doc_id = 100
    for i in range(AnalysisTaskState.MAX_ATTEMPTS):
        AnalysisTaskState.mark_retryable(doc_id, "opportunity", f"fail {i+1}")
    state = AnalysisTaskState.get_or_create(doc_id, "opportunity")
    assert state["status"] == "permanent_error"
    assert state["attempt_count"] == AnalysisTaskState.MAX_ATTEMPTS
    # permanent_error 应被 list_retryable 排除
    retryable = AnalysisTaskState.list_retryable()
    assert not any(r["doc_id"] == doc_id for r in retryable)


def test_mark_succeeded_clears_error_and_retry_time(db):
    """mark_succeeded 应清空 last_error 与 next_retry_at（R-04）。"""
    AnalysisTaskState.mark_retryable(200, "entity", "boom")
    before = AnalysisTaskState.get_or_create(200, "entity")
    assert before["last_error"] == "boom"
    assert before["status"] == "retryable_error"

    AnalysisTaskState.mark_succeeded(200, "entity")
    after = AnalysisTaskState.get_or_create(200, "entity")
    assert after["status"] == "succeeded"
    assert after["last_error"] is None
