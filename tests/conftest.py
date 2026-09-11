# tests/conftest.py
"""根级 pytest 配置：默认禁止测试访问外网。

P2-12：用 transport 级守卫拦截真实外网请求（httpx.get + httpx.Client.get
+ 任何走 httpx.HTTPTransport 的请求）。TestClient 用 mock transport 不受影响。
"""
import pytest
import httpx

# 使用 respx mock 的测试模块无需网络守卫（respx 安装自己的 transport，
# 但 Client.get 守卫在 respx transport 之前拦截）
_EXEMPT_MODULES = {
    "tests.e2e.test_collect_e2e",
    "tests.e2e.test_full_stack",
    "tests.collector.test_retry_queue",
    "tests.collector.test_xiongan_portal",
    "tests.collector.test_xiongxian",
    "tests.collector.test_rmxiongan",
    "tests.collector.test_rongcheng",
    "tests.collector.test_anxin",
    "tests.collector.test_hebccw",
    "tests.collector.test_wechat_search",
}

# 允许的主机（loopback + test mock）
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver", ""}


def _is_external_url(url):
    """判断 URL 是否指向外部网络（非 loopback/test）。"""
    try:
        parsed = httpx.URL(url) if not isinstance(url, httpx.URL) else url
        return parsed.host not in _ALLOWED_HOSTS
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _block_network(request):
    """默认禁止 httpx 访问外部网络（防止测试污染和依赖外网）。

    P2-12：拦截 httpx.get 和 httpx.Client.get 中指向外网的请求。
    TestClient（用 mock transport）和 loopback 请求不受影响。
    """
    if request.module.__name__ in _EXEMPT_MODULES:
        yield
        return

    original_get = httpx.get
    original_client_get = httpx.Client.get

    def _guard(get_func):
        def _wrapped(self_or_url, *args, **kwargs):
            # httpx.get(url, ...) 和 client.get(url, ...) 的第一个参数是 url
            url = self_or_url if isinstance(self_or_url, str) else kwargs.get("url", args[0] if args else "")
            if _is_external_url(url):
                raise RuntimeError(
                    "External network access blocked in tests. Use @respx.mock. "
                    f"Called from: {url}"
                )
            return get_func(self_or_url, *args, **kwargs)
        return _wrapped

    httpx.get = _guard(original_get)
    # Client.get 是实例方法，第一个参数是 self；需保留 self 透传
    def _client_guard(self, url="...", *args, **kwargs):
        if _is_external_url(url):
            raise RuntimeError(
                f"External network access blocked in tests (Client.get): {url}"
            )
        return original_client_get(self, url, *args, **kwargs)
    httpx.Client.get = _client_guard

    yield
    httpx.get = original_get
    httpx.Client.get = original_client_get
