"""A-06 + A-08: true 分支合约 + permanent failure 任务类型限定测试。"""
import pytest
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


# ---- A-06: true 分支缺业务字段 → retryable ----

def test_judge_true_missing_business_line_rejected():
    """A-06：is_opportunity=true 但缺 business_line → retryable_error。"""
    from analyzer.result import validate_llm_dict, JudgeLLMResult
    bad = validate_llm_dict({"is_opportunity": True}, schema=JudgeLLMResult)
    assert bad is not None
    assert bad.retryable


def test_judge_true_missing_opp_type_rejected():
    """A-06：is_opportunity=true 有 business_line 缺 opp_type → retryable。"""
    from analyzer.result import validate_llm_dict, JudgeLLMResult
    bad = validate_llm_dict({"is_opportunity": True, "business_line": "corporate"}, schema=JudgeLLMResult)
    assert bad is not None
    assert bad.retryable


def test_judge_true_with_required_fields_accepted():
    """A-06：is_opportunity=true 有 business_line + opp_type → 通过。"""
    from analyzer.result import validate_llm_dict, JudgeLLMResult
    bad = validate_llm_dict(
        {"is_opportunity": True, "business_line": "corporate", "opp_type": "入驻"},
        schema=JudgeLLMResult,
    )
    assert bad is None


def test_leadership_true_missing_leader_name_rejected():
    """A-06：is_leadership_visit=true 缺 leader_name → retryable。"""
    from analyzer.result import validate_llm_dict, LeadershipLLMResult
    bad = validate_llm_dict({"is_leadership_visit": True}, schema=LeadershipLLMResult)
    assert bad is not None
    assert bad.retryable


def test_leadership_true_with_leader_name_accepted():
    """A-06：is_leadership_visit=true 有 leader_name → 通过。"""
    from analyzer.result import validate_llm_dict, LeadershipLLMResult
    bad = validate_llm_dict(
        {"is_leadership_visit": True, "leader_name": "张三"},
        schema=LeadershipLLMResult,
    )
    assert bad is None


# ---- A-08: permanent failure 限定核心任务类型 ----

def test_permanent_failure_ignores_non_required_task_type():
    """A-08：非核心任务（如 judge_enrich_v1）permanent_error 不触发 dead_letter。"""
    from storage.models import AnalysisTaskState, get_conn
    # 模拟一个非核心任务的 permanent_error
    conn = get_conn()
    conn.execute(
        "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, updated_at) "
        "VALUES (999, 'judge_enrich_v1', 'permanent_error', 5, '2026-01-01')",
    )
    conn.commit()
    # has_permanent_failure 应返回 False（judge_enrich_v1 非核心任务）
    assert AnalysisTaskState.has_permanent_failure(999) is False


def test_permanent_failure_detects_required_task_type():
    """A-08：核心任务（leadership）permanent_error 触发 dead_letter。"""
    from storage.models import AnalysisTaskState, get_conn
    conn = get_conn()
    conn.execute(
        "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, updated_at) "
        "VALUES (998, 'leadership', 'permanent_error', 5, '2026-01-01')",
    )
    conn.commit()
    assert AnalysisTaskState.has_permanent_failure(998) is True
