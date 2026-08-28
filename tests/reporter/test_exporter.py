import os
import pytest
from reporter.exporter import export_to_docx


def test_export_to_docx_creates_file(tmp_path):
    """导出 Word 应生成 .docx 文件。"""
    report_content = {
        "title": "测试周报",
        "summary": "本期概要",
        "sections": [
            {
                "line": "对公业务",
                "opportunities": [
                    {"title": "商机A", "scale": "10亿", "products": "项目贷",
                     "action": "跟进", "insight": "解读"}
                ],
            },
        ],
        "recommendations": "重点跟进商机A",
        "stats": {"total": 1},
    }

    output_path = str(tmp_path / "test_report.docx")
    result = export_to_docx(report_content, output_path)

    assert os.path.exists(result)
    assert result.endswith(".docx")
    assert os.path.getsize(result) > 0


def test_export_to_docx_empty_sections(tmp_path):
    """无商机章节时也能正常导出。"""
    report_content = {
        "title": "空周报",
        "summary": "无商机",
        "sections": [],
        "recommendations": "",
        "stats": {"total": 0},
    }
    output_path = str(tmp_path / "empty.docx")
    result = export_to_docx(report_content, output_path)
    assert os.path.exists(result)
