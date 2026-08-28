import pytest
from storage.models import init_db, close_db, Report


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_create_report():
    report = Report.create(
        report_type="weekly",
        period_start="2026-07-04",
        period_end="2026-07-10",
        content='{"summary": "测试"}',
        opportunity_ids="[1,2,3]",
    )
    assert report.id is not None
    assert report.report_type == "weekly"


def test_get_report_by_id():
    report = Report.create(
        report_type="daily", period_start="2026-07-10", period_end="2026-07-10",
        content="{}", opportunity_ids="[]",
    )
    fetched = Report.get_by_id(report.id)
    assert fetched.report_type == "daily"


def test_list_reports():
    Report.create(report_type="daily", period_start="2026-07-09", period_end="2026-07-09",
                  content="{}", opportunity_ids="[]")
    Report.create(report_type="weekly", period_start="2026-07-04", period_end="2026-07-10",
                  content="{}", opportunity_ids="[]")
    reports = Report.list()
    assert len(reports) == 2


def test_update_file_paths():
    report = Report.create(report_type="daily", period_start="2026-07-10", period_end="2026-07-10",
                           content="{}", opportunity_ids="[]")
    report.update_files(docx_path="reports/daily.docx", pdf_path="reports/daily.pdf")
    fetched = Report.get_by_id(report.id)
    assert fetched.docx_path == "reports/daily.docx"
    assert fetched.pdf_path == "reports/daily.pdf"
