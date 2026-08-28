"""Web Push 推送通道（PWA）。

使用 pywebpush 实现 W3C Web Push 协议。
需要 VAPID 密钥对（开发环境可自动生成）。
"""
import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

# 模块级导入以便测试 patch（缺失时降级为延迟导入）
try:
    from pywebpush import webpush, WebPushException  # noqa: F401
except Exception:  # pragma: no cover - 依赖缺失时的兜底
    webpush = None
    WebPushException = Exception

# VAPID 密钥缓存（开发环境首次访问时自动生成）
_vapid_keys: dict | None = None


def _get_vapid_keys() -> dict | None:
    """获取 VAPID 密钥，开发环境自动生成。

    优先级：环境变量 > 自动生成临时密钥。
    返回 {"subject", "public_key", "private_key"} 或 None。
    """
    global _vapid_keys
    if _vapid_keys:
        return _vapid_keys

    # 从环境变量加载（生产环境）
    public_key = os.environ.get("VAPID_PUBLIC_KEY")
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    if public_key and private_key:
        _vapid_keys = {
            "subject": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com"),
            "public_key": public_key,
            "private_key": private_key,
        }
        return _vapid_keys

    # 开发环境：生成临时密钥
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        private_pem = v.private_pem()
        if isinstance(private_pem, bytes):
            private_pem = private_pem.decode()

        # 公钥转为 Web Push 所需的未压缩点 base64url（65 字节：0x04 + X + Y）
        pub_numbers = v.public_key.public_numbers()
        raw = (
            b"\x04"
            + pub_numbers.x.to_bytes(32, "big")
            + pub_numbers.y.to_bytes(32, "big")
        )
        public_key_b64 = base64.urlsafe_b64encode(raw).decode().rstrip("=")

        _vapid_keys = {
            "subject": "mailto:admin@example.com",
            "public_key": public_key_b64,
            "private_key": private_pem,
        }
        logger.info("Generated temporary VAPID keys for development")
    except Exception as e:
        logger.error(f"Failed to generate VAPID keys: {e}")
        _vapid_keys = None

    return _vapid_keys


def get_public_key() -> str | None:
    """获取 VAPID 公钥（前端订阅用）。"""
    keys = _get_vapid_keys()
    return keys["public_key"] if keys else None


def send_web_push(subscription: dict, payload: dict) -> bool:
    """发送 Web Push 通知。

    Args:
        subscription: 订阅信息 {endpoint, keys: {p256dh, auth}}
        payload: 推送内容 {title, body, url}

    Returns:
        True 成功，False 失败（不抛异常，调用方据此记录 delivered 状态）
    """
    keys = _get_vapid_keys()
    if not keys:
        logger.warning("No VAPID keys available, skipping push")
        return False

    if webpush is None:  # pragma: no cover - 依赖缺失兜底
        logger.error("pywebpush not installed")
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=keys["private_key"],
            vapid_claims={"sub": keys["subject"]},
        )
        return True
    except WebPushException as e:
        logger.error(f"Web Push failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Push error: {e}")
        return False
