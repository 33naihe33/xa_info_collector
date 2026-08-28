"""F-12: 无截断期查询测试。

回归用例：reports.py 用 Opportunity.list(limit=500)、generator.py 用
LeadershipVisit.list(limit=200)，超过阈值的记录被静默丢弃。
"""
import pytest
from storage.models import (
    init_db, close_db, Opportunity, LeadershipVisit,
)


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_opportunity_list_for_period_no_truncation():
    """超过 500 条商机落在日期范围内 → 全部返回（不截断）。"""
    # 插入 550 条商机（均在范围内）
    for i in range(550):
        Opportunity.create(
            title=f"商机{i}", source_doc_id=None, business_line="corporate",
            opp_type="测试", priority="medium", status="signal",
            publish_date="2026-07-10",
        )
    opps = Opportunity.list_for_period(date_from="2026-07-01", date_to="2026-07-31")
    assert len(opps) == 550, f"应返回全部 550 条，实际 {len(opps)}（原 limit=500 会丢 50 条）"


def test_leadership_visit_list_for_period_no_truncation():
    """超过 200 条领导调研落在日期范围内 → 全部返回（不截断）。"""
    for i in range(220):
        LeadershipVisit.create(
            source_doc_id=None, leader_name=f"领导{i}", leader_title="书记",
            visit_date="2026-07-10", visit_topic="调研", visited_entities="[]",
            summary="摘要", priority="medium", publish_date="2026-07-10",
            images="[]",
        )
    visits = LeadershipVisit.list_for_period(
        visit_date_from="2026-07-01", visit_date_to="2026-07-31"
    )
    assert len(visits) == 220, f"应返回全部 220 条，实际 {len(visits)}（原 limit=200 会丢 20 条）"


def test_opportunity_list_for_period_filters_by_business_line():
    """list_for_period 的 business_lines 参数在 SQL 层过滤。"""
    for bl in ["corporate", "retail", "fintech"]:
        Opportunity.create(
            title=f"{bl}商机", source_doc_id=None, business_line=bl,
            opp_type="测试", priority="medium", status="signal",
            publish_date="2026-07-10",
        )
    opps = Opportunity.list_for_period(
        date_from="2026-07-01", date_to="2026-07-31",
        business_lines=["corporate", "retail"],
    )
    assert len(opps) == 2
    assert all(o.business_line in ("corporate", "retail") for o in opps)
