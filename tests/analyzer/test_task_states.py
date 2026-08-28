# tests/analyzer/test_task_states.py
"""analysis_task_states DAO 测试。

DB 初始化由 tests/analyzer/conftest.py 的 autouse `_db` fixture 负责。
"""
from storage.models import AnalysisTaskState


def test_get_or_create_returns_pending_defaults():
    """首次获取应创建 pending 状态、attempt_count=0 的记录。"""
    state = AnalysisTaskState.get_or_create(doc_id=1, task_type="opportunity")
    assert state == {"status": "pending", "attempt_count": 0,
                     "last_error": None, "next_retry_at": None}

    # 再次获取应返回已存在记录（幂等）
    state2 = AnalysisTaskState.get_or_create(doc_id=1, task_type="opportunity")
    assert state2 == {"status": "pending", "attempt_count": 0,
                      "last_error": None, "next_retry_at": None}


def test_mark_succeeded_makes_all_succeeded():
    """R-04：entity + opportunity + leadership 均成功时 all_succeeded 返回 True。"""
    AnalysisTaskState.mark_succeeded(2, "entity")
    assert AnalysisTaskState.all_succeeded(2) is False  # 还差 opportunity/leadership

    AnalysisTaskState.mark_succeeded(2, "opportunity")
    assert AnalysisTaskState.all_succeeded(2) is False  # 还差 leadership

    AnalysisTaskState.mark_succeeded(2, "leadership")
    assert AnalysisTaskState.all_succeeded(2) is True


def test_mark_retryable_blocks_all_succeeded():
    """存在 retryable_error 时 all_succeeded 返回 False。"""
    AnalysisTaskState.mark_succeeded(3, "entity")
    AnalysisTaskState.mark_retryable(3, "opportunity", "LLM timeout")

    state = AnalysisTaskState.get_or_create(3, "opportunity")
    assert state["status"] == "retryable_error"
    assert state["attempt_count"] == 1
    assert state["last_error"] == "LLM timeout"
    assert AnalysisTaskState.all_succeeded(3) is False


def test_mark_retryable_increments_attempt_count():
    """重复 retry 应累加 attempt_count。"""
    AnalysisTaskState.mark_retryable(4, "opportunity", "err1")
    AnalysisTaskState.mark_retryable(4, "opportunity", "err2")

    state = AnalysisTaskState.get_or_create(4, "opportunity")
    assert state["status"] == "retryable_error"
    assert state["attempt_count"] == 2
    assert state["last_error"] == "err2"


def test_mark_succeeded_overrides_retryable():
    """succeeded 状态应覆盖之前的 retryable_error。"""
    AnalysisTaskState.mark_retryable(5, "opportunity", "boom")
    assert AnalysisTaskState.all_succeeded(5) is False

    AnalysisTaskState.mark_succeeded(5, "opportunity")
    AnalysisTaskState.mark_succeeded(5, "entity")
    AnalysisTaskState.mark_succeeded(5, "leadership")
    assert AnalysisTaskState.all_succeeded(5) is True


def test_all_succeeded_false_when_no_rows():
    """无任何记录时 all_succeeded 返回 False。"""
    assert AnalysisTaskState.all_succeeded(999) is False


def test_permanent_error_is_failure_not_success():
    """P0-04：permanent_error = 失败，all_succeeded 返回 False。

    原设计把 permanent_error 计入成功集合（静默丢数）。
    现修正：只有全部 succeeded 才算成功；permanent_error 应触发 dead_letter。
    """
    AnalysisTaskState.mark_succeeded(6, "entity")
    AnalysisTaskState.mark_succeeded(6, "opportunity")
    # leadership 熔断到 permanent_error
    for _ in range(AnalysisTaskState.MAX_ATTEMPTS):
        AnalysisTaskState.mark_retryable(6, "leadership", "always fails")
    ld = AnalysisTaskState.get_or_create(6, "leadership")
    assert ld["status"] == "permanent_error"
    # P0-04：permanent_error 不再计入成功 → all_succeeded False
    assert AnalysisTaskState.all_succeeded(6) is False
    # has_permanent_failure 应检出
    assert AnalysisTaskState.has_permanent_failure(6) is True
