# tests/analyzer/test_extractor_judge.py
"""实体抽取 + 商机研判测试。

DB 初始化由 tests/analyzer/conftest.py 的 autouse `_db` fixture 负责，
本文件不再重复声明 db fixture：conftest 已对每个测试初始化临时库并在结束时
close_db，而同名 `db` fixture 会覆盖 conftest 的 `_db`（不同名也不冲突）。
直接复用 conftest 的 DB 即可。
"""
import pytest
from unittest.mock import patch, MagicMock
from storage.models import init_db, close_db, Document, Entity, Opportunity


def _make_doc(text="测试正文") -> int:
    doc = Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试",
        url="http://test", publish_date="2026-07-10",
        raw_html="", text=text, content_hash="h1",
    )
    return doc.id


def test_extract_entities_creates_entities():
    """实体抽取应把 LLM 返回的实体写入 entities 表。"""
    from analyzer.entity_extractor import extract_entities

    doc_id = _make_doc("张国华调研启动区")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "entities": [
            {"name": "张国华", "type": "人物"},
            {"name": "启动区", "type": "项目"},
        ],
        "relations": [
            {"from": "张国华", "to": "启动区", "type": "调研"},
        ],
    }

    extract_entities(doc_id=doc_id, text="正文", llm_client=mock_llm)

    entities = Entity.list()
    assert len(entities) == 2
    names = {e.name for e in entities}
    assert "张国华" in names
    assert "启动区" in names


def test_extract_entities_handles_empty_result():
    """LLM 返回空实体时不崩溃。"""
    from analyzer.entity_extractor import extract_entities

    doc_id = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"entities": [], "relations": []}

    extract_entities(doc_id=doc_id, text="正文", llm_client=mock_llm)
    assert len(Entity.list()) == 0


def test_judge_opportunity_creates_opportunity():
    """商机研判应把命中商机写入 opportunities 表。"""
    from analyzer.opportunity_judge import judge_opportunity
    from storage.models import Opportunity

    doc_id = _make_doc("28家企业落地雄安")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "inclusive",
        "opp_type": "科创企业",
        "fin_scale": None,
        "fin_products": ["科创贷"],
        "target_client": "落地企业",
        "insight": "企业落地带来开户需求",
        "action_suggest": "联系落地企业",
        "priority": "medium",
        "trigger_event": "28家企业落地",
    }

    result = judge_opportunity(doc_id=doc_id, text="正文", publish_date="2026-07-10",
                               llm_client=mock_llm)

    assert result.status == "succeeded"
    assert result.opportunity is not None
    opps = Opportunity.list()
    assert len(opps) == 1
    assert opps[0].business_line == "corporate"
    assert opps[0].priority == "medium"


def test_judge_opportunity_skips_non_opportunity():
    """LLM 判断无商机时不创建。"""
    from analyzer.opportunity_judge import judge_opportunity
    from storage.models import Opportunity

    doc_id = _make_doc("天气预报")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": False,
        "business_line": None,
    }

    result = judge_opportunity(doc_id=doc_id, text="正文", publish_date="2026-07-10",
                               llm_client=mock_llm)
    assert result.status == "succeeded"
    assert result.opportunity is None
    assert Opportunity.count() == 0


def test_judge_opportunity_handles_llm_failure():
    """LLM 返回 None 时不崩溃且标记为 retryable_error。"""
    from analyzer.opportunity_judge import judge_opportunity

    doc_id = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = None

    # 不应抛异常
    result = judge_opportunity(doc_id=doc_id, text="正文", publish_date="2026-07-10",
                               llm_client=mock_llm)
    assert result.status == "retryable_error"
    assert result.opportunity is None
