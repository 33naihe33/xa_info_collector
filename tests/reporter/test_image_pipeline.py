"""F-14: 图片路径三层闭环测试。

回归用例：
- LeadershipVisit.to_dict 返回裸本地路径（如 data/images/xxx.jpg），前端无法访问
- resolve_image_path_for_export 是死代码，exporter 直接 os.path.exists 处理裸路径
- generator 读 doc.images 裸路径，绕过 Document.to_dict 的 URL 转换

闭环方向：
- API 输出层（generator / LeadershipVisit.to_dict）：本地路径 → image_url_for_api → /images/...
- 导出层（exporter）：/images/... → resolve_image_path_for_export → 本地路径
"""
import os
import json
import pytest
from fastapi.testclient import TestClient
from storage.models import (
    init_db, close_db, LeadershipVisit, Document,
    image_url_for_api, resolve_image_path_for_export,
)


@pytest.fixture
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_leadership_visit_to_dict_returns_image_urls(db):
    """LeadershipVisit.to_dict 的 images 应为 /images/... URL，不是裸本地路径。"""
    # 模拟存储的 images 列（本地路径 JSON）
    LeadershipVisit.create(
        source_doc_id=None, leader_name="张三", leader_title="书记",
        visit_date="2026-07-10", visit_topic="调研", visited_entities="[]",
        summary="摘要", priority="high", publish_date="2026-07-10",
        images=json.dumps(["data/images/abc123/photo.jpg"]),
    )
    lv = LeadershipVisit.list()[0]
    d = lv.to_dict()
    assert len(d["images"]) == 1
    img = d["images"][0]
    assert img.startswith("/images/"), f"API 应返回 /images/ URL，实际 {img}"
    assert "data/images" not in img  # 不泄露本地路径


def test_leadership_report_section_uses_image_urls(db):
    """P1-08：报告领导调研章节的 images 应为 /images/... URL（对称性补丁）。

    回归：F-14 只修了商机章节（Block A），领导调研章节（Block B）仍泄露
    裸本地路径 data/images/...。
    """
    from storage.models import Document, LeadershipVisit
    from reporter.generator import generate_report

    # 建一篇带本地图片路径的文档
    doc = Document.create(
        source="xiongan_portal", doc_type="新闻", title="领导调研测试",
        url="http://lv1", publish_date="2026-07-10",
        raw_html="", text="某领导调研雄安重点项目总投资50亿",
        content_hash="h_lv_p08",
        images='["data/images/abc/lv_photo.jpg"]',
    )
    LeadershipVisit.create(
        source_doc_id=doc.id, leader_name="张三", leader_title="书记",
        visit_date="2026-07-10", visit_topic="调研", visited_entities="[]",
        summary="摘要", priority="high", publish_date="2026-07-10",
        images='["data/images/abc/lv_photo.jpg"]',
    )

    content = generate_report(
        report_type="monthly",
        period_start="2026-07-01", period_end="2026-07-31",
        llm_client=None,
    )
    # 找领导调研章节
    sections = content.get("sections", [])
    leadership_section = [s for s in sections if s.get("line") == "领导调研"]
    assert leadership_section, "报告应含领导调研章节"
    for opp in leadership_section[0].get("opportunities", []):
        for img in opp.get("images", []):
            assert img.startswith("/images/"), f"领导调研章节图片应为 /images/ URL，实际 {img}"
            assert "data/images" not in img


def test_image_url_endpoint_returns_200(tmp_path):
    """实际请求 /images/<测试文件> → 200。

    注：/images 挂载点指向项目 data/images（相对 web/app.py），
    故测试文件需放在项目 data/images 下，结束后清理。
    """
    import shutil
    project_images = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "data", "images", "f14testhash"
    )
    os.makedirs(project_images, exist_ok=True)
    test_file = os.path.join(project_images, "test.png")
    # 最小有效 PNG（1x1 透明）
    with open(test_file, "wb") as f:
        f.write(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    try:
        init_db(str(tmp_path / "test.db"))
        from web.app import create_app
        app = create_app()
        with TestClient(app) as client:
            resp = client.get("/images/f14testhash/test.png")
            assert resp.status_code == 200
            assert resp.content.startswith(b"\x89PNG"), "应返回实际 PNG 内容"
        close_db()
    finally:
        shutil.rmtree(project_images, ignore_errors=True)


def test_exporter_resolves_image_url_to_local_path(db, tmp_path):
    """exporter 能把 /images/... URL 解析回本地路径并嵌入 Word。"""
    # 准备本地图片文件
    img_dir = tmp_path / "data" / "images" / "exporthash"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "pic.jpg"
    # 写一个 >1000 字节的假 JPEG（足够通过 exporter 的 size>1000 检查）
    img_file.write_bytes(b"\xff\xd8\xff" + b"\x00" * 1100 + b"\xff\xd9")

    # resolve_image_path_for_export 应把 /images/... 转回 data/...
    url_form = "/images/exporthash/pic.jpg"
    resolved = resolve_image_path_for_export(url_form)
    assert resolved.endswith("data/images/exporthash/pic.jpg"), f"解析错误: {resolved}"

    # image_url_for_api 反向应把 data/... 转回 /images/...
    back = image_url_for_api("data/images/exporthash/pic.jpg")
    assert back == "/images/exporthash/pic.jpg"


def test_round_trip_local_to_url_to_local():
    """本地路径 → API URL → 本地路径 往返一致。"""
    local = "data/images/abc/photo.jpg"
    url = image_url_for_api(local)
    assert url == "/images/abc/photo.jpg"
    restored = resolve_image_path_for_export(url)
    assert restored.endswith("data/images/abc/photo.jpg")
