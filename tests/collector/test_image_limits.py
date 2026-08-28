"""F-10: 图片下载安全限制测试 + F-18 LLM 超时线程上限测试。"""
import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch
from storage.models import init_db, close_db
from collector.base import RawDoc


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_adapter():
    from collector.adapters.xiongan_portal import XionganPortalAdapter
    return XionganPortalAdapter()


def test_image_non_whitelist_domain_skipped():
    """F-10：非白名单域名的图片 URL 被跳过（防 SSRF）。"""
    adapter = _make_adapter()
    raw = RawDoc(
        title="t", url="http://x", publish_date="2026-07-10",
        raw_html="", text="content",
        images='["https://evil.com/img.jpg"]',
    )
    adapter.download_images(raw, "test_hash")
    # 非白名单 → 不下载，images 为空
    import json
    result = json.loads(raw.images)
    assert result == [], "非白名单域名应被跳过"


def test_image_oversize_skipped():
    """F-10：超过 5MB 的图片被跳过。"""
    adapter = _make_adapter()
    raw = RawDoc(
        title="t", url="http://x", publish_date="2026-07-10",
        raw_html="", text="content",
        images='["https://www.xiongan.gov.cn/big.jpg"]',
    )
    # mock httpx.get 返回 6MB 内容
    import httpx as _httpx_mod
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b"\x00" * (6 * 1024 * 1024)  # 6MB
    fake_resp.headers = {"content-type": "image/jpeg"}
    with patch.object(_httpx_mod, "get", return_value=fake_resp):
        adapter.download_images(raw, "test_hash2")
    import json
    result = json.loads(raw.images)
    assert result == [], "超 5MB 图片应被跳过"


def test_image_non_image_mime_skipped():
    """F-10：非 image/* MIME 类型被跳过。"""
    adapter = _make_adapter()
    raw = RawDoc(
        title="t", url="http://x", publish_date="2026-07-10",
        raw_html="", text="content",
        images='["https://www.xiongan.gov.cn/page.html"]',
    )
    import httpx as _httpx_mod
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b"\x00" * 5000
    fake_resp.headers = {"content-type": "text/html"}  # 非 image
    with patch.object(_httpx_mod, "get", return_value=fake_resp):
        adapter.download_images(raw, "test_hash3")
    import json
    result = json.loads(raw.images)
    assert result == [], "非 image MIME 应被跳过"


def test_llm_timeout_thread_limit():
    """F-18：并发超时泄漏线程达上限后拒绝新调用。"""
    import analyzer.llm_client as lc
    # 重置计数器
    lc._leaked_thread_count = lc._MAX_LEAKED_THREADS
    with pytest.raises(lc.LLMCallTimeout, match="Too many leaked"):
        lc._call_glm_with_timeout(MagicMock(), "model", [], {"type": "json_object"})
    # 重置
    lc._leaked_thread_count = 0
