# tests/reporter/test_exporter_fixes.py
"""F-01 和 F-27 修复测试。"""
import os
import pytest
from docx import Document
from reporter.exporter import export_to_docx


def test_export_empty_report_no_images(tmp_path):
    """F-01: 空报告（无图片）不应抛出 UnboundLocalError。"""
    report_content = {
        "title": "测试空报告",
        "summary": "本期无新增商机。",
        "sections": [],
        "recommendations": "",
        "stats": {"total": 0},
    }
    output = str(tmp_path / "empty.docx")
    result = export_to_docx(report_content, output)
    assert os.path.exists(result)
    assert os.path.getsize(result) > 0


def test_export_report_with_local_image(tmp_path):
    """F-01: 有本地图片的报告应正常嵌入。"""
    # 创建一个大于1000字节的测试图片
    from PIL import Image as PILImage
    img_path = str(tmp_path / "test.png")
    PILImage.new('RGB', (500, 500), 'red').save(img_path)  # 大图确保>1000字节
    assert os.path.getsize(img_path) > 1000, "Test image must be >1000 bytes"

    report_content = {
        "title": "测试图片报告",
        "summary": "有图片",
        "sections": [
            {"line": "测试板块", "opportunities": [
                {"title": "测试商机", "priority": "high", "images": [img_path]},
            ]},
        ],
        "recommendations": "",
        "stats": {"total": 1},
    }
    output = str(tmp_path / "with_image.docx")
    result = export_to_docx(report_content, output)
    assert os.path.exists(result)

    # 检查Word中有图片
    import zipfile
    with zipfile.ZipFile(result) as z:
        media = [n for n in z.namelist() if 'media' in n]
        assert len(media) >= 1, "Word should contain at least one image"


def test_export_report_corrupted_image(tmp_path):
    """F-01: 损坏的图片文件不应导致报告生成失败。"""
    bad_img = str(tmp_path / "corrupt.jpg")
    with open(bad_img, 'wb') as f:
        f.write(b'not an image')

    report_content = {
        "title": "测试损坏图片",
        "summary": "有损坏图片",
        "sections": [
            {"line": "测试", "opportunities": [
                {"title": "测试", "priority": "medium", "images": [bad_img]},
            ]},
        ],
        "recommendations": "",
        "stats": {"total": 1},
    }
    output = str(tmp_path / "corrupt.docx")
    result = export_to_docx(report_content, output)
    assert os.path.exists(result), "Should still produce a report despite corrupt image"


def test_export_report_remote_url_fallback(tmp_path):
    """F-01: 远程URL（不可达）不应导致报告失败。"""
    report_content = {
        "title": "测试远程URL",
        "summary": "有远程URL",
        "sections": [
            {"line": "测试", "opportunities": [
                {"title": "测试", "priority": "medium",
                 "images": ["http://nonexistent.example.com/image.jpg"]},
            ]},
        ],
        "recommendations": "",
        "stats": {"total": 1},
    }
    output = str(tmp_path / "remote.docx")
    result = export_to_docx(report_content, output)
    assert os.path.exists(result)


def test_chapter_numbering_no_duplicate_yi(tmp_path):
    """F-27: 章节编号不应与概要的'一'重复。"""
    report_content = {
        "title": "编号测试",
        "summary": "测试",
        "sections": [
            {"line": "第一板块", "opportunities": [
                {"title": "商机A", "priority": "high"},
            ]},
            {"line": "第二板块", "opportunities": [
                {"title": "商机B", "priority": "medium"},
            ]},
        ],
        "recommendations": "",
        "stats": {"total": 2},
    }
    output = str(tmp_path / "numbering.docx")
    export_to_docx(report_content, output)

    doc = Document(output)
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith('Heading')]
    # 概要应该是"一"，第一板块应该是"二"
    assert any("一、本期概要" in h for h in headings), "Should have '一、本期概要'"
    assert any("二、第一板块" in h for h in headings), "First section should be '二'"
    assert any("三、第二板块" in h for h in headings), "Second section should be '三'"
    # 不应有两个"一"
    yi_count = sum(1 for h in headings if h.startswith("一、"))
    assert yi_count == 1, f"Should have exactly one '一', got {yi_count}"
