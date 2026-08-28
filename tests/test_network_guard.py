"""P2-12: 测试隔离网络守卫测试。

回归：原守卫只拦 httpx.get，不拦 httpx.Client.get（adapter 走这条路径）。
现在 transport 级守卫拦截外网请求，loopback/TestClient 不受影响。
"""
import pytest
import httpx


def test_client_get_external_blocked():
    """httpx.Client.get 外网请求应被守卫拦截（不实际访问网络）。"""
    client = httpx.Client()
    with pytest.raises(RuntimeError, match="External network access blocked"):
        client.get("https://www.example.com/test")


def test_httpx_get_external_blocked():
    """httpx.get 外网请求应被守卫拦截。"""
    with pytest.raises(RuntimeError, match="network access blocked|External"):
        httpx.get("https://www.example.com/test")


def test_loopback_not_blocked():
    """loopback URL 不应被守卫拦截（TestClient 走 mock transport）。"""
    # loopback host 应通过守卫（虽然连接会因无服务失败，但不该是 RuntimeError guard）
    try:
        httpx.get("http://127.0.0.1:1/test", timeout=0.1)
    except RuntimeError as e:
        if "blocked" in str(e):
            pytest.fail("loopback 不应被守卫拦截")
    except Exception:
        pass  # 连接失败是正常的（无服务），关键是没被 guard 拦
