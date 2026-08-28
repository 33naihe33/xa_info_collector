"""P0-03 + P0-04 回归测试。

P0-03：analyze_pending 候选饥饿。原 SQL 仅 WHERE is_analyzed=0 ORDER BY
publish_date DESC LIMIT ?，到期判断在 LIMIT 后的 Python 层。limit=1 时
最新文档若未到期 retryable 会占名额，较旧到期/新文档永不选中。

P0-04：permanent_error 被当成功。原 all_succeeded 把 permanent_error
计入成功集合 → 文档标 is_analyzed=1 → 静默丢数。现修正为 dead_letter。
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


def _set_task_state(doc_id, task_type, status, attempt_count=0, next_retry_at=None):
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


def test_candidate_starvation_not_due_does_not_block_due(db):
    """P0-03：limit=1 时，未到期 retryable 文档不应占名额阻塞较旧到期文档。

    构造：doc_newer（最新，未到期 retryable）+ doc_older（较旧，到期 retryable）。
    原 SQL 会选 doc_newer（最新），但它未到期不做任何事，doc_older 永不选中。
    修正后 SQL 在 WHERE 层排除未到期 → 选 doc_older。
    """
    from analyzer.pipeline import analyze_pending

    # doc_newer: 发布日期较新，opportunity 未到期 retryable（next_retry_at 在未来）
    doc_newer = Document.create(
        source="x", doc_type="新闻", title="较新文档", url="http://newer",
        publish_date="2026-07-20", raw_html="", text="某企业落户雄安，总投资50亿",
        content_hash="h_newer",
    )
    _set_task_state(doc_newer.id, "entity", "succeeded")
    _set_task_state(doc_newer.id, "opportunity", "retryable_error", attempt_count=1,
                    next_retry_at="2099-12-31T23:59:59")  # 未到期
    _set_task_state(doc_newer.id, "leadership", "succeeded")

    # doc_older: 发布日期较旧，opportunity 已到期 retryable
    doc_older = Document.create(
        source="x", doc_type="新闻", title="较旧文档", url="http://older",
        publish_date="2026-07-10", raw_html="", text="某企业落户雄安，总投资30亿",
        content_hash="h_older",
    )
    _set_task_state(doc_older.id, "entity", "succeeded")
    _set_task_state(doc_older.id, "opportunity", "retryable_error", attempt_count=1,
                    next_retry_at="2020-01-01T00:00:00")  # 已到期
    _set_task_state(doc_older.id, "leadership", "succeeded")

    mock_llm = MagicMock()
    # limit=1：应选 doc_older（到期重试），而非 doc_newer（未到期，占名额无用）
    mock_llm.chat_json.return_value = {"is_opportunity": False}
    stats = analyze_pending(llm_client=mock_llm, limit=1)

    # doc_older 被选中并处理（opportunity 重试成功 → analyzed True）
    assert stats["total"] == 1
    # doc_newer 不应被选（未到期）→ LLM 调用应是 doc_older 的 opportunity（1 次）
    assert mock_llm.chat_json.call_count == 1
    # doc_older 应被标记分析完成
    assert Document.get_by_id(doc_older.id).is_analyzed is True
    # doc_newer 仍未分析（未到期，留待下次）
    assert Document.get_by_id(doc_newer.id).is_analyzed is False


def test_new_document_without_task_state_is_candidate(db):
    """P0-03：新文档（无任务状态行）应被选为候选。"""
    from analyzer.pipeline import analyze_pending

    doc = Document.create(
        source="x", doc_type="新闻", title="全新文档", url="http://new",
        publish_date="2026-07-10", raw_html="", text="某企业落户雄安，总投资50亿",
        content_hash="h_new",
    )
    # 不设任何 task_state（新文档）
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [], "relations": []},  # entity
        {"is_opportunity": False},  # opportunity
        {"is_leadership_visit": False},  # leadership
    ]
    stats = analyze_pending(llm_client=mock_llm, limit=5)
    assert stats["total"] == 1
    assert stats["analyzed"] == 1
    assert Document.get_by_id(doc.id).is_analyzed is True


def test_dead_letter_excluded_from_candidates(db):
    """P0-04：dead_letter=1 的文档不进入候选池。"""
    from analyzer.pipeline import analyze_pending

    doc = Document.create(
        source="x", doc_type="新闻", title="dead letter", url="http://dl",
        publish_date="2026-07-10", raw_html="", text="某企业落户雄安，总投资50亿",
        content_hash="h_dl",
    )
    # 标记 dead_letter
    conn = get_conn()
    conn.execute("UPDATE documents SET dead_letter = 1 WHERE id = ?", (doc.id,))
    conn.commit()
    # 即便 opportunity 是 pending，dead_letter 文档不应被选
    _set_task_state(doc.id, "opportunity", "pending")

    mock_llm = MagicMock()
    stats = analyze_pending(llm_client=mock_llm, limit=5)
    assert stats["total"] == 0  # 无候选
    assert mock_llm.chat_json.call_count == 0


def test_permanent_failure_marks_dead_letter_in_analyze_document(db):
    """P0-04：analyze_document 遇 permanent_error → dead_letter=1，不标 is_analyzed。"""
    from analyzer.pipeline import analyze_document

    doc = Document.create(
        source="x", doc_type="新闻", title="will fail permanently", url="http://pf",
        publish_date="2026-07-10", raw_html="", text="某企业落户雄安，总投资50亿",
        content_hash="h_pf",
    )
    _set_task_state(doc.id, "entity", "succeeded")
    _set_task_state(doc.id, "opportunity", "permanent_error",
                    attempt_count=AnalysisTaskState.MAX_ATTEMPTS)
    # leadership 无状态（pending/缺失）

    mock_llm = MagicMock()
    result = analyze_document(doc, llm_client=mock_llm)
    assert result["analyzed"] is False
    assert result.get("dead_letter") is True
    refreshed = Document.get_by_id(doc.id)
    assert refreshed.dead_letter is True
    assert refreshed.is_analyzed is False
