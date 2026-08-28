"""R-02: 两态结果协议测试。

验证 entity/leadership extractor 返回 TaskResult，且：
- LLM None / 非 dict（合约不合）→ retryable_error（不再误标 succeeded）
- 明确判定"无实体/非领导调研"→ succeeded(None)（成功的分类）
- LLM 返回数组等类型错误 → retryable_error
"""
import pytest
from unittest.mock import MagicMock

from storage.models import init_db, close_db, Document, AnalysisTaskState, LeadershipVisit


@pytest.fixture
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(text="某企业落户雄安，总投资50亿", title="测试文档"):
    return Document.create(
        source="x", doc_type="新闻", title=title, url="http://t",
        publish_date="2026-07-10", raw_html="", text=text, content_hash="h_r02",
    )


def test_entity_llm_none_marks_retryable_not_succeeded(db):
    """R-02 核心：entity LLM 返回 None → retryable_error，文档不标记 is_analyzed。"""
    from analyzer.entity_extractor import extract_entities
    from analyzer.pipeline import analyze_document

    doc = _make_doc()
    mock_llm = MagicMock()
    # entity None → retryable；opportunity 正常无商机；leadership 非调研
    mock_llm.chat_json.side_effect = [
        None,  # entity: LLM None
        {"is_opportunity": False},  # opportunity: 无商机
        {"is_leadership_visit": False},  # leadership: 非调研
    ]

    result = analyze_document(doc, llm_client=mock_llm)
    # entity retryable → 文档不应被标记已分析
    assert result["analyzed"] is False
    assert Document.get_by_id(doc.id).is_analyzed is False
    # entity 任务为 retryable_error（不是 succeeded）
    entity_state = AnalysisTaskState.get_or_create(doc.id, "entity")
    assert entity_state["status"] == "retryable_error"


def test_leadership_non_visit_returns_succeeded_none(db):
    """R-02：leadership 判定为"非调研"→ succeeded(None)，记录为 succeeded。"""
    from analyzer.leadership_extractor import extract_leadership

    doc = _make_doc(text="某企业落户雄安")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"is_leadership_visit": False}

    result = extract_leadership(
        doc_id=doc.id, text="正文", publish_date="2026-07-10",
        llm_client=mock_llm, doc_title="非调研",
    )
    assert result.succeeded
    assert result.payload is None  # 成功的分类，不是错误
    # 不应创建任何 LeadershipVisit
    assert len(LeadershipVisit.list()) == 0


def test_entity_llm_returns_array_marks_retryable(db):
    """R-02：LLM 返回数组（合约不合）→ retryable_error。"""
    from analyzer.entity_extractor import extract_entities

    doc = _make_doc()
    mock_llm = MagicMock()
    # LLM 错误地返回数组而非 dict
    mock_llm.chat_json.return_value = [{"entities": []}]

    result = extract_entities(doc_id=doc.id, text="正文", llm_client=mock_llm, publish_date="2026-07-10")
    assert result.retryable
    assert not result.succeeded


def test_leadership_llm_none_marks_retryable(db):
    """R-02：leadership LLM None → retryable_error（不再误标 succeeded）。"""
    from analyzer.leadership_extractor import extract_leadership

    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = None

    result = extract_leadership(
        doc_id=doc.id, text="正文", publish_date="2026-07-10",
        llm_client=mock_llm, doc_title="LLM失败",
    )
    assert result.retryable
    assert len(LeadershipVisit.list()) == 0
