"""H-05 + M-09: 图片安全（SSRF/流式/魔数）+ DATA_DIR 统一测试。"""
import os
import pytest
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


def test_image_private_ip_redirect_rejected():
    """H-05：白名单站点重定向到私网 IP → 拒绝（防 redirect SSRF）。"""
    adapter = _make_adapter()
    raw = RawDoc(
        title="t", url="http://x", publish_date="2026-07-10",
        raw_html="", text="content",
        images='["https://www.xiongan.gov.cn/redirect-to-internal.jpg"]',
    )
    # mock：HEAD 返回 302 → 127.0.0.1；_stream_download_image 应拒绝
    import httpx as _httpx_mod
    head_resp = MagicMock()
    head_resp.status_code = 302
    head_resp.headers = {"location": "http://127.0.0.1/secret"}
    with patch.object(_httpx_mod, "head", return_value=head_resp):
        adapter.download_images(raw, "test_ssrf")
    import json
    result = json.loads(raw.images)
    assert result == [], "私网 IP 重定向应被拒绝（H-05 SSRF）"


def test_image_allowlisted_initial_host_accepts_reserved_dns(monkeypatch):
    """官方白名单图片域名被本地网络重写到保留地址时仍可下载。"""
    adapter = _make_adapter()
    import socket
    import httpx as _httpx_mod

    monkeypatch.setattr(socket, "gethostbyname", lambda _host: "198.18.2.10")
    head_resp = MagicMock()
    head_resp.status_code = 200
    head_resp.headers = {"content-type": "image/jpeg", "content-length": "2000"}
    stream_cm = MagicMock()
    stream_resp = MagicMock()
    stream_resp.status_code = 200
    stream_resp.headers = {"content-type": "image/jpeg"}
    stream_resp.iter_bytes.return_value = [b"x" * 2000]
    stream_cm.__enter__ = MagicMock(return_value=stream_resp)
    stream_cm.__exit__ = MagicMock(return_value=False)

    with patch.object(_httpx_mod, "head", return_value=head_resp), \
         patch.object(_httpx_mod, "stream", return_value=stream_cm):
        result = adapter._stream_download_image(
            "https://www.xiongan.gov.cn/image.jpg",
            max_size=5 * 1024 * 1024,
            allowed_domains={"www.xiongan.gov.cn"},
        )

    assert result == b"x" * 2000


def test_image_streaming_aborts_on_oversize():
    """H-05：流式下载累计超 5MB 立即中止（不全量入内存）。"""
    adapter = _make_adapter()
    raw = RawDoc(
        title="t", url="http://x", publish_date="2026-07-10",
        raw_html="", text="content",
        images='["https://www.xiongan.gov.cn/big.jpg"]',
    )
    import httpx as _httpx_mod
    # mock HEAD 通过（无 Content-Length），stream 返回大块数据
    head_resp = MagicMock()
    head_resp.status_code = 200
    head_resp.headers = {"content-type": "image/jpeg"}
    # mock stream context manager
    stream_cm = MagicMock()
    stream_resp = MagicMock()
    stream_resp.status_code = 200
    stream_resp.headers = {"content-type": "image/jpeg"}
    stream_resp.iter_bytes.return_value = [b"\x00" * 8192] * 1000  # 8MB+ 触发中止
    stream_cm.__enter__ = MagicMock(return_value=stream_resp)
    stream_cm.__exit__ = MagicMock(return_value=False)
    with patch.object(_httpx_mod, "head", return_value=head_resp), \
         patch.object(_httpx_mod, "stream", return_value=stream_cm):
        adapter.download_images(raw, "test_stream")
    import json
    result = json.loads(raw.images)
    assert result == [], "超 5MB 应流式中止（不全量下载）"


def test_image_bad_magic_rejected():
    """H-05：非图片字节（魔数校验失败）被拒绝。"""
    adapter = _make_adapter()
    raw = RawDoc(
        title="t", url="http://x", publish_date="2026-07-10",
        raw_html="", text="content",
        images='["https://www.xiongan.gov.cn/fake.jpg"]',
    )
    import httpx as _httpx_mod
    head_resp = MagicMock()
    head_resp.status_code = 200
    head_resp.headers = {"content-type": "image/jpeg", "content-length": "2000"}
    stream_cm = MagicMock()
    stream_resp = MagicMock()
    stream_resp.status_code = 200
    stream_resp.headers = {"content-type": "image/jpeg"}
    stream_resp.iter_bytes.return_value = [b"NOT_AN_IMAGE" * 200]  # 非图片字节
    stream_cm.__enter__ = MagicMock(return_value=stream_resp)
    stream_cm.__exit__ = MagicMock(return_value=False)
    with patch.object(_httpx_mod, "head", return_value=head_resp), \
         patch.object(_httpx_mod, "stream", return_value=stream_cm):
        adapter.download_images(raw, "test_magic")
    import json
    result = json.loads(raw.images)
    assert result == [], "非图片魔数应被拒绝"


def test_data_dir_consistency():
    """M-09：images_dir/snapshots_dir/reports_dir 同源（统一 DATA_DIR）。"""
    from storage.paths import images_dir, snapshots_dir, reports_dir, DATA_DIR
    assert images_dir() == os.path.join(DATA_DIR, "images")
    assert snapshots_dir() == os.path.join(DATA_DIR, "snapshots")
    assert reports_dir() == os.path.join(DATA_DIR, "reports")
    # 采集器与 web 用同一 images_dir
    import storage.paths as paths
    import collector.base as base
    # save_snapshot 用 snapshots_dir()
    import inspect
    src = inspect.getsource(base.BaseAdapter.save_snapshot)
    assert "snapshots_dir" in src, "save_snapshot 应用统一 snapshots_dir()"


def test_data_dir_env_override(tmp_path, monkeypatch):
    """M-09：XA_DATA_DIR 环境变量覆盖 DATA_DIR。"""
    import storage.paths as paths
    custom = str(tmp_path / "custom_data")
    monkeypatch.setenv("XA_DATA_DIR", custom)
    # 重新导入读取新值
    import importlib
    importlib.reload(paths)
    assert paths.DATA_DIR == custom
    assert paths.images_dir() == os.path.join(custom, "images")
    # 恢复
    monkeypatch.delenv("XA_DATA_DIR", raising=False)
    importlib.reload(paths)
