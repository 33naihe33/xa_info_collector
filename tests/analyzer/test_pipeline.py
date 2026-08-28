# tests/analyzer/test_pipeline.py
"""分析 pipeline 编排测试。

DB 初始化由 tests/analyzer/conftest.py 的 autouse `_db` fixture 负责。
"""
import pytest
from unittest.mock import patch, MagicMock
from storage.models import init_db, close_db, Document, Opportunity


def test_analyze_document_skips_irrelevant():
    """无信号文档不调 LLM。"""
    from analyzer.pipeline import analyze_document

    doc = Document.create(
        source="x", doc_type="新闻", title="天气预报",
        url="http://w", publish_date="2026-07-10",
        raw_html="", text="今天天气晴朗适合户外运动",
        content_hash="h1",
    )
    mock_llm = MagicMock()
    result = analyze_document(doc, llm_client=mock_llm)
    assert result["analyzed"] is False
    mock_llm.chat_json.assert_not_called()
    assert doc.is_analyzed is True  # 标记为已分析（跳过）


def test_analyze_document_full_pipeline():
    """有信号的文档走完整 pipeline。"""
    from analyzer.pipeline import analyze_document

    doc = Document.create(
        source="x", doc_type="新闻", title="28家企业落地雄安",
        url="http://e", publish_date="2026-07-10",
        raw_html="", text="28家科技企业正式落户雄安，总投资50亿",
        content_hash="h2",
    )
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        # 第一次调用：实体抽取
        {"entities": [{"name": "雄安", "type": "机构"}], "relations": []},
        # 第二次调用：商机研判
        {
            "is_opportunity": True,
            "business_line": "inclusive",
            "opp_type": "科创企业",
            "fin_products": ["科创贷"],
            "priority": "medium",
            "trigger_event": "企业落地",
            "insight": "开户需求",
            "action_suggest": "联系企业",
        },
        # 第三次调用：领导调研识别（本文档非领导调研新闻）
        {"is_leadership_visit": False},
    ]

    result = analyze_document(doc, llm_client=mock_llm)
    assert result["analyzed"] is True
    assert result["has_opportunity"] is True
    assert mock_llm.chat_json.call_count == 3  # 实体 + 商机 + 领导调研

    opps = Opportunity.list()
    assert len(opps) == 1
    assert opps[0].business_line == "corporate"


def test_analyze_pending_documents():
    """批量分析未分析的文档。"""
    from analyzer.pipeline import analyze_pending

    # 3篇文档：1篇有信号，2篇无信号
    Document.create(source="x", doc_type="新闻", title="项目开工",
                    url="http://1", publish_date="2026-07-10",
                    raw_html="", text="重大项目开工投资10亿", content_hash="h1")
    Document.create(source="x", doc_type="新闻", title="天气",
                    url="http://2", publish_date="2026-07-10",
                    raw_html="", text="今天天气不错", content_hash="h2")
    Document.create(source="x", doc_type="新闻", title="花开",
                    url="http://3", publish_date="2026-07-10",
                    raw_html="", text="公园的花都开了", content_hash="h3")

    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [], "relations": []},  # 实体抽取
        {"is_opportunity": True, "business_line": "corporate",
         "opp_type": "项目融资", "priority": "high",
         "trigger_event": "项目开工", "fin_products": ["项目贷"]},  # 商机
        {"is_leadership_visit": False},  # 领导调研识别（非调研新闻）
    ]

    stats = analyze_pending(llm_client=mock_llm)
    assert stats["total"] == 3
    assert stats["analyzed"] == 1  # 只有1篇有信号
    assert stats["skipped"] == 2


def test_analyze_document_not_marked_when_opportunity_fails():
    """商机研判 LLM 返回 None 时，文档不应被标记为已分析（等待重试）。"""
    from analyzer.pipeline import analyze_document
    from storage.models import AnalysisTaskState

    doc = Document.create(
        source="x", doc_type="新闻", title="28家企业落地雄安",
        url="http://f", publish_date="2026-07-10",
        raw_html="", text="28家科技企业正式落户雄安，总投资50亿",
        content_hash="hf",
    )
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        # 第一次调用：实体抽取成功
        {"entities": [], "relations": []},
        # 第二次调用：商机研判 LLM 返回 None（失败）
        None,
        # 第三次调用：领导调研识别（非调研新闻）
        {"is_leadership_visit": False},
    ]

    result = analyze_document(doc, llm_client=mock_llm)
    # R-04：返回值反映真实完成状态。opportunity=retryable → analyzed=False
    assert result["analyzed"] is False
    assert result["has_opportunity"] is False
    # 关键断言：文档未被标记为 is_analyzed=1，等待下次重试
    assert doc.is_analyzed is False
    refreshed = Document.get_by_id(doc.id)
    assert refreshed.is_analyzed is False

    # 商机任务应记录为 retryable_error，实体仍为 succeeded
    opp_state = AnalysisTaskState.get_or_create(doc.id, "opportunity")
    assert opp_state["status"] == "retryable_error"
    entity_state = AnalysisTaskState.get_or_create(doc.id, "entity")
    assert entity_state["status"] == "succeeded"

    # 没有创建任何商机
    assert Opportunity.count() == 0


def test_analyze_document_marked_when_all_tasks_succeed():
    """所有任务成功时，文档应被标记为已分析。"""
    from analyzer.pipeline import analyze_document
    from storage.models import AnalysisTaskState

    doc = Document.create(
        source="x", doc_type="新闻", title="28家企业落地雄安",
        url="http://o", publish_date="2026-07-10",
        raw_html="", text="28家科技企业正式落户雄安，总投资50亿",
        content_hash="ho",
    )
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [], "relations": []},
        {"is_opportunity": True, "business_line": "corporate",
         "opp_type": "项目融资", "priority": "high",
         "trigger_event": "企业落地", "fin_products": ["项目贷"]},
        {"is_leadership_visit": False},
    ]

    result = analyze_document(doc, llm_client=mock_llm)
    assert result["analyzed"] is True
    assert result["has_opportunity"] is True
    assert doc.is_analyzed is True
    assert AnalysisTaskState.all_succeeded(doc.id) is True
