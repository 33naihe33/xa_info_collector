"""P1-07: enrichment runner 测试。

回归：update_banking_fields 只在测试中调用，生产无入口。
judge_opportunity 重复即 return 不更新，重跑无法补字段。
"""
import pytest
from unittest.mock import MagicMock
from storage.models import init_db, close_db, Opportunity, Document, AnalysisTaskState


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc_and_opp(six_fields_empty=True):
    """建一篇文档 + 一条缺六字段的商机。"""
    doc = Document.create(
        source="x", doc_type="新闻", title="央企落户", url="http://enrich",
        publish_date="2026-07-10", raw_html="", text="中国星网集团总部落户雄安总投资50亿",
        content_hash="h_enrich",
    )
    kwargs = dict(
        title="央企落户商机", source_doc_id=doc.id, business_line="corporate",
        opp_type="央企入驻", priority="high", status="signal", publish_date="2026-07-10",
    )
    if not six_fields_empty:
        kwargs.update(buyer_dept="国资委")
    opp = Opportunity.create(**kwargs)
    return doc, opp


def test_enrich_updates_existing_no_duplicate():
    """A-03：enrich_one 直接 UPDATE 现有商机，不创建重复记录。

    填满全部 6 字段 → succeeded；部分填充 → partial（见 test_enrich_partial_fills_pending）。
    """
    from analyzer.enrich import enrich_one
    doc, opp = _make_doc_and_opp()
    count_before = Opportunity.count()

    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "corporate",
        "opp_type": "央企入驻",
        "buyer_dept": "国资委",
        "relocate_from": "北京",
        "relocate_scale": "5000人",
        "relocate_phase": "在建",
        "timing_window": "2026年Q3",
        "deadline": "2026-09-30",
    }
    result = enrich_one(opp, mock_llm)
    assert result["status"] == "succeeded"
    # 不创建新记录
    assert Opportunity.count() == count_before
    # 六字段已更新
    refreshed = Opportunity.get_by_id(opp.id)
    assert refreshed.buyer_dept == "国资委"
    assert refreshed.relocate_from == "北京"
    assert refreshed.relocate_scale == "5000人"


def test_dry_run_does_not_modify_data():
    """dry-run 只列出候选，不调 LLM、不修改数据。"""
    from analyzer.enrich import enrich_opportunities, list_enrichment_candidates
    doc, opp = _make_doc_and_opp()

    stats = enrich_opportunities(dry_run=True, llm_client=None)
    assert stats["dry_run"] is True
    assert stats["total"] == 1
    # 数据未改
    refreshed = Opportunity.get_by_id(opp.id)
    assert refreshed.buyer_dept is None


def test_enrich_skips_already_processed():
    """H-03 断点续跑：已标记 succeeded（按 opportunity_id）的不再处理。"""
    from analyzer.enrich import list_enrichment_candidates, _enrich_state_set
    doc, opp = _make_doc_and_opp()
    # H-03：按 opportunity_id 标记（非 doc_id）
    _enrich_state_set(opp.id, "succeeded")
    candidates = list_enrichment_candidates()
    assert len(candidates) == 0, "已标记的应被排除"


def test_enrich_includes_partial_fields():
    """H-03：候选 = 任一字段为 NULL/空（原只选全空，漏掉部分缺失）。"""
    from analyzer.enrich import list_enrichment_candidates
    doc, opp = _make_doc_and_opp(six_fields_empty=False)  # buyer_dept 已设，其余 5 字段空
    candidates = list_enrichment_candidates()
    assert len(candidates) == 1, "任一字段缺失的应被选为候选（H-03）"


def test_enrich_same_doc_multiple_opps_independent():
    """H-03：同一文档两条商机各自独立处理（断点按 opportunity_id）。

    原 bug：断点用 doc_id，第一条处理后整个 doc 被标 succeeded，第二条跳过。
    """
    from analyzer.enrich import enrich_one, list_enrichment_candidates
    doc = Document.create(
        source="x", doc_type="新闻", title="多商机文档", url="http://multi",
        publish_date="2026-07-10", raw_html="", text="央企落户总投资50亿",
        content_hash="h_multi",
    )
    opp1 = Opportunity.create(
        title="商机A", source_doc_id=doc.id, business_line="corporate",
        opp_type="入驻", priority="high", status="signal", publish_date="2026-07-10",
    )
    opp2 = Opportunity.create(
        title="商机B", source_doc_id=doc.id, business_line="fintech",
        opp_type="创新", priority="medium", status="signal", publish_date="2026-07-10",
    )
    # 处理 opp1
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"is_opportunity": True, "business_line": "corporate", "opp_type": "入驻", "buyer_dept": "国资委"}
    enrich_one(opp1, mock_llm)
    # opp2 仍应是候选（断点按 opportunity_id，不因 opp1 处理完而排除）
    candidates = list_enrichment_candidates()
    opp_ids = [c.id for c in candidates]
    assert opp2.id in opp_ids, "同文档的第二条商机应独立处理（H-03）"


def test_enrich_zero_update_marks_retryable():
    """H-03：LLM 未返回任何字段 → retryable_error（不标 succeeded 永不再试）。"""
    from analyzer.enrich import enrich_one, _enrich_state_get
    doc, opp = _make_doc_and_opp()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"is_opportunity": True}  # 无六字段
    result = enrich_one(opp, mock_llm)
    assert result["status"] == "failed"
    assert _enrich_state_get(opp.id) == "retryable_error"


def test_enrich_does_not_overwrite_existing_field():
    """A-03：已有字段不被覆盖（LLM 返回不同值时忽略）。"""
    from analyzer.enrich import enrich_one
    from storage.models import Opportunity
    doc, opp = _make_doc_and_opp(six_fields_empty=False)  # buyer_dept="国资委"
    original_buyer = opp.buyer_dept
    mock_llm = MagicMock()
    # LLM 返回不同的 buyer_dept + 其余字段补全到终态
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "corporate",
        "opp_type": "入驻",
        "buyer_dept": "错误的新值",  # 应被忽略（已有值）
        "relocate_from": "北京",
        "relocate_scale": "5000人",
        "relocate_phase": "在建",
        "timing_window": "2026年Q3",
        "deadline": "2026-09-30",
    }
    enrich_one(opp, mock_llm)
    refreshed = Opportunity.get_by_id(opp.id)
    assert refreshed.buyer_dept == original_buyer, "已有字段不应被覆盖"
    assert refreshed.relocate_from == "北京"  # 新字段已填


def test_enrich_partial_fill_stays_pending():
    """A-03：部分字段填充（其余仍空）→ pending，不标 succeeded（下次补剩余）。"""
    from analyzer.enrich import enrich_one, _enrich_state_get
    doc, opp = _make_doc_and_opp()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "corporate",
        "opp_type": "入驻",
        "buyer_dept": "国资委",  # 只填 1 个，其余 5 个仍空
    }
    result = enrich_one(opp, mock_llm)
    assert result["status"] == "partial", "部分填充应标 pending，不标 succeeded"
    assert _enrich_state_get(opp.id) == "pending"
    assert "remaining" in result
    assert len(result["remaining"]) == 5
