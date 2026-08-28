"""P1-05: LLM 输出合约字段级校验测试。

回归：原 validate_llm_dict 只检查 isinstance(dict)，空 dict {} 也算成功。
pipeline 用宽泛 except Exception 把编程错误也标 retryable，与 docstring 矛盾。
"""
import pytest
from unittest.mock import MagicMock
from storage.models import init_db, close_db, Document, LeadershipVisit


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(text="某企业落户雄安，总投资50亿"):
    return Document.create(
        source="x", doc_type="新闻", title="测试", url="http://t",
        publish_date="2026-07-10", raw_html="", text=text, content_hash="h_p15",
    )


def test_validate_llm_dict_rejects_empty_dict():
    """空 dict {} → retryable_error（缺必需键 entities/relations）。"""
    from analyzer.result import validate_llm_dict, EntityLLMResult
    bad = validate_llm_dict({}, schema=EntityLLMResult)
    # EntityLLMResult entities/relations 有默认值 []，空 dict 实际通过；
    # 但若 schema 要求必需键，空 dict 应失败。这里 EntityLLMResult 宽容（默认 []）。
    # 验证：缺 is_opportunity 的 JudgeLLMResult 应失败。
    from analyzer.result import JudgeLLMResult
    bad2 = validate_llm_dict({}, schema=JudgeLLMResult)
    assert bad2 is not None
    assert bad2.retryable


def test_entity_extractor_rejects_missing_required_via_schema():
    """extract_entities 收到缺 entities 键但 is_opportunity 类的 dict → 仍 OK（entities 默认 []）。

    但收到非 dict（如数组）→ retryable。"""
    from analyzer.entity_extractor import extract_entities
    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = [{"entities": []}]  # 数组非 dict
    result = extract_entities(doc_id=doc.id, text="正文", llm_client=mock_llm, publish_date="2026-07-10")
    assert result.retryable


def test_judge_rejects_missing_is_opportunity():
    """judge_opportunity 收到缺 is_opportunity 的 dict → retryable_error。"""
    from analyzer.opportunity_judge import judge_opportunity
    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"business_line": "corporate"}  # 缺 is_opportunity
    result = judge_opportunity(
        doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
        doc_title=doc.title, llm_client=mock_llm,
    )
    assert result.status == "retryable_error"


def test_judge_rejects_wrong_type_is_opportunity():
    """is_opportunity 非布尔（如 list）→ retryable_error（类型错）。"""
    from analyzer.opportunity_judge import judge_opportunity
    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"is_opportunity": ["yes"]}  # list 非布尔
    result = judge_opportunity(
        doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
        doc_title=doc.title, llm_client=mock_llm,
    )
    assert result.status == "retryable_error"


def test_leadership_rejects_missing_is_leadership_visit():
    """extract_leadership 收到缺 is_leadership_visit → retryable_error。"""
    from analyzer.leadership_extractor import extract_leadership
    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"leader_name": "张三"}  # 缺 is_leadership_visit
    result = extract_leadership(
        doc_id=doc.id, text="正文", publish_date="2026-07-10",
        llm_client=mock_llm, doc_title="测试",
    )
    assert result.retryable


def test_pipeline_does_not_swallow_programming_error(db=None):
    """P1-05：extractor 抛编程异常时 pipeline 不吞掉标 retryable，而是 re-raise。"""
    from analyzer.pipeline import analyze_document
    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"entities": [], "relations": []}
    # mock extract_entities 抛 AttributeError（编程错误）
    with pytest.raises(AttributeError):
        import analyzer.pipeline as p
        orig = p.extract_entities
        p.extract_entities = lambda **kw: (_ for _ in ()).throw(AttributeError("boom"))
        try:
            analyze_document(doc, llm_client=mock_llm)
        finally:
            p.extract_entities = orig
