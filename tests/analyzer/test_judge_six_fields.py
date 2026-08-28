"""F-29: 六字段全链路 + enrichment 回填测试。

回归用例：
- prompt 从不要求 6 个银行业字段（buyer_dept/relocate_from/relocate_scale/
  relocate_phase/timing_window/deadline）
- opportunity_judge.py create 调用不传递这 6 字段
- Opportunity.to_dict 漏掉 relocate_scale，且不规范化 "null"/""
- opportunity_judge.py:61-67 重复即 return，重跑无法补字段（需 enrichment UPDATE）
"""
import pytest
from unittest.mock import MagicMock
from storage.models import init_db, close_db, Document, Opportunity, AnalysisTaskState


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(text="中国星网集团总部正式从北京迁入雄安，总投资50亿，2026年Q3前完成搬迁"):
    return Document.create(
        source="x", doc_type="新闻", title="央企落户", url="http://t",
        publish_date="2026-07-10", raw_html="", text=text, content_hash="h_f29",
    )


def test_judge_creates_opportunity_with_six_banking_fields():
    """LLM 返回含 6 字段 → create 路径入库后 6 列非空。"""
    from analyzer.opportunity_judge import judge_opportunity

    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "corporate",
        "opp_type": "央企疏解入驻",
        "fin_scale": "50亿",
        "fin_products": ["综合授信"],
        "target_client": "中国星网集团",
        "buyer_dept": "国务院国资委",
        "relocate_from": "北京",
        "relocate_scale": "5000人/总部",
        "relocate_phase": "在建",
        "timing_window": "2026年Q3前",
        "deadline": "2026-09-30",
        "insight": "央企总部迁入带来全方位金融需求",
        "action_suggest": "机构业务部对接",
        "priority": "critical",
        "trigger_event": "央企落户",
    }

    result = judge_opportunity(
        doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
        doc_title=doc.title, llm_client=mock_llm,
    )
    assert result.status == "succeeded"
    assert result.opportunity is not None

    refreshed = Opportunity.get_by_id(result.opportunity.id)
    assert refreshed.buyer_dept == "国务院国资委"
    assert refreshed.relocate_from == "北京"
    assert refreshed.relocate_scale == "5000人/总部"
    assert refreshed.relocate_phase == "在建"
    assert refreshed.timing_window == "2026年Q3前"
    assert refreshed.deadline == "2026-09-30"


def test_to_dict_normalizes_null_strings_and_includes_relocate_scale():
    """to_dict 把 'null'/''/空白 规范化为 None，并包含 relocate_scale。"""
    opp = Opportunity.create(
        title="测试", source_doc_id=None, business_line="corporate",
        opp_type="测试", priority="medium", status="signal",
        publish_date="2026-07-10",
        buyer_dept="null",        # 应规范化为 None
        relocate_from="",         # 应规范化为 None
        relocate_scale="  ",      # 应规范化为 None
        relocate_phase="在建",
        timing_window="null",
        deadline="2026-09-30",
    )
    d = opp.to_dict()
    # F-29：relocate_scale 必须存在（原 to_dict 漏掉）
    assert "relocate_scale" in d
    # "null"/""/空白 → None
    assert d["buyer_dept"] is None
    assert d["relocate_from"] is None
    assert d["relocate_scale"] is None
    assert d["timing_window"] is None
    # 有效值保留
    assert d["relocate_phase"] == "在建"
    assert d["deadline"] == "2026-09-30"


def test_enrichment_update_does_not_create_duplicate():
    """enrichment 路径直接 UPDATE 现有商机，不创建重复记录。"""
    # 先建一条 6 字段全空的商机
    opp = Opportunity.create(
        title="已有商机", source_doc_id=142, business_line="corporate",
        opp_type="央企入驻", priority="high", status="signal",
        publish_date="2026-07-10",
    )
    count_before = Opportunity.count()

    # enrichment：直接更新字段（不走 create 去重）
    opp.update_banking_fields(
        buyer_dept="国资委",
        relocate_from="北京",
        relocate_scale="5000人",
    )

    # 不应新增记录
    assert Opportunity.count() == count_before
    refreshed = Opportunity.get_by_id(opp.id)
    assert refreshed.buyer_dept == "国资委"
    assert refreshed.relocate_from == "北京"
    assert refreshed.relocate_scale == "5000人"


def test_judge_normalizes_null_strings_on_create():
    """create 路径也应规范化 LLM 返回的 'null' 字符串。"""
    from analyzer.opportunity_judge import judge_opportunity

    doc = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "corporate",
        "opp_type": "测试",
        "fin_products": [],
        "buyer_dept": "null",       # 应规范化
        "relocate_from": "",        # 应规范化
        "relocate_scale": "  ",     # 应规范化
        "relocate_phase": "规划",
        "timing_window": "2026年",
        "deadline": "null",
        "trigger_event": "事件",
        "priority": "medium",
    }
    result = judge_opportunity(
        doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
        doc_title=doc.title, llm_client=mock_llm,
    )
    opp = Opportunity.get_by_id(result.opportunity.id)
    assert opp.buyer_dept is None
    assert opp.relocate_from is None
    assert opp.relocate_scale is None
    assert opp.relocate_phase == "规划"
    assert opp.timing_window == "2026年"
    assert opp.deadline is None
