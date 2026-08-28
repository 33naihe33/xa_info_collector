import pytest
from unittest.mock import MagicMock
from storage.models import init_db, close_db, Opportunity, LeadershipVisit


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_generate_report_with_opportunities():
    """生成报告应调用 LLM 汇总商机并返回结构化内容。"""
    Opportunity.create(
        title="项目融资A", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-08", insight="解读A", action_suggest="行动A",
        fin_scale="10亿", fin_products='["项目贷"]',
    )
    Opportunity.create(
        title="科创企业B", source_doc_id=None, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date="2026-07-06", insight="解读B",
    )

    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "title": "周报",
        "summary": "本期2条商机",
        "sections": [{"line": "对公", "opportunities": []}],
        "recommendations": "重点跟进A",
        "stats": {"total": 2},
    }

    from reporter.generator import generate_report
    result = generate_report(
        report_type="weekly",
        period_start="2026-07-04", period_end="2026-07-10",
        llm_client=mock_llm,
    )

    assert "金融业务机会" in result["title"]
    assert mock_llm.chat_json.call_count == 1
    # 验证商机信息被传入 prompt
    call_args = mock_llm.chat_json.call_args
    user_prompt = call_args.kwargs["user"]
    assert "项目融资A" in user_prompt


def test_generate_report_no_opportunities():
    """无商机时仍应返回基本结构。"""
    mock_llm = MagicMock()
    from reporter.generator import generate_report
    result = generate_report(
        report_type="daily",
        period_start="2026-07-10", period_end="2026-07-10",
        llm_client=mock_llm,
    )
    assert "title" in result
    assert result["summary"] == "本期无新增商机线索。"
    mock_llm.chat_json.assert_not_called()


def test_leadership_report_keeps_publish_and_visit_dates():
    """领导调研应按发布时间进入报告，并同时保留发布时间与调研时间。"""
    LeadershipVisit.create(
        leader_name="张国华", leader_title="书记",
        visit_date="2026-07-09", publish_date="2026-07-10",
        visit_topic="调研", visited_entities="[]", summary="摘要",
        priority="high",
    )

    from reporter.generator import generate_report
    result = generate_report(
        report_type="daily", period_start="2026-07-10", period_end="2026-07-10",
        llm_client=None,
    )

    section = next(s for s in result["sections"] if s["line"] == "领导调研")
    assert section["opportunities"][0]["publish_date"] == "2026-07-10"
    assert section["opportunities"][0]["visit_date"] == "2026-07-09"
