# tests/analyzer/test_leadership_dates.py
"""F-22: 领导调研日期校验测试（动态年份）。"""
import pytest
from unittest.mock import MagicMock
from storage.models import init_db, close_db, Document, LeadershipVisit


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(publish_date="2026-07-22") -> int:
    doc = Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试",
        url=f"http://test/{publish_date}", publish_date=publish_date,
        raw_html="", text="测试正文", content_hash=f"h_{publish_date}",
    )
    return doc.id


def _mock_llm_visit(visit_date):
    """创建返回领导调研的 mock LLM，指定 visit_date。"""
    mock = MagicMock()
    mock.chat_json.return_value = {
        "is_leadership_visit": True,
        "leader_name": "张国华",
        "leader_title": "书记",
        "visit_date": visit_date,
        "visit_topic": "调研测试",
        "visited_entities": [],
        "summary": "摘要",
        "priority": "high",
    }
    return mock


def test_current_year_within_7_days():
    """当年日期，与发布日期相差<=7天 → 通过。"""
    from analyzer.leadership_extractor import extract_leadership
    doc_id = _make_doc("2026-07-22")
    mock = _mock_llm_visit("2026-07-20")  # 2天前
    result = extract_leadership(doc_id=doc_id, text="正文", publish_date="2026-07-22",
                                llm_client=mock, doc_title="测试")
    assert result.succeeded and result.payload is not None, "Should accept current-year visit within 7 days"


def test_request_context_includes_publish_date():
    """领导调研模型必须知道文章发布日期，才能在“近日”场景正确回填日期。"""
    from analyzer.leadership_extractor import extract_leadership
    doc_id = _make_doc("2026-07-22")
    mock = _mock_llm_visit("2026-07-20")

    extract_leadership(doc_id=doc_id, text="正文", publish_date="2026-07-22",
                       llm_client=mock, doc_title="测试")

    assert "发布日期：2026-07-22" in mock.chat_json.call_args.kwargs["user"]


def test_cross_year_within_7_days():
    """跨年但相差<=7天 → 通过（如发布12月31日，调研次年1月2日）。"""
    from analyzer.leadership_extractor import extract_leadership
    doc_id = _make_doc("2026-12-31")
    mock = _mock_llm_visit("2027-01-02")  # 跨年但2天后
    result = extract_leadership(doc_id=doc_id, text="正文", publish_date="2026-12-31",
                                llm_client=mock, doc_title="跨年测试")
    assert result.succeeded and result.payload is not None, "Should accept cross-year visit within 7 days"


def test_invalid_date_february_30():
    """R-08：无效日期 2026-02-30 → succeeded(None) 且不入库（不再恒真断言）。

    原 test 用 `assert result is not None or result is None`（恒真）。
    现改为：断言返回 succeeded + payload None + 数据库无新增记录。
    """
    from analyzer.leadership_extractor import extract_leadership
    doc_id = _make_doc("2026-07-22")
    mock = _mock_llm_visit("2026-07-20")
    # 覆盖 visit_date 为无效日期（2 月没有 30 号）
    mock.chat_json.return_value["visit_date"] = "2026-02-30"
    count_before = len(LeadershipVisit.list())
    result = extract_leadership(doc_id=doc_id, text="正文", publish_date="2026-07-22",
                                llm_client=mock, doc_title="无效日期")
    # 无效日期 → skip → succeeded(None)，不入库
    assert result.succeeded
    assert result.payload is None
    count_after = len(LeadershipVisit.list())
    assert count_after == count_before, "无效日期不应创建 LeadershipVisit 记录"


def test_far_future_year_rejected():
    """异常年份2099 → 拒绝（skip=True，返回 ok(None) 不入库）。"""
    from analyzer.leadership_extractor import extract_leadership
    doc_id = _make_doc("2026-07-22")
    mock = _mock_llm_visit("2099-07-20")
    result = extract_leadership(doc_id=doc_id, text="正文", publish_date="2026-07-22",
                                llm_client=mock, doc_title="未来年份")
    assert result.succeeded and result.payload is None, "Should reject far-future year"
