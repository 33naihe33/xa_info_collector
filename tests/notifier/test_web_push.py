import pytest
from unittest.mock import patch, MagicMock
from notifier.channels.web_push import send_web_push, get_public_key


def test_send_web_push_success():
    """mock pywebpush，验证调用。"""
    sub = {
        "endpoint": "https://fcm.googleapis.com/test",
        "keys": {"p256dh": "abc", "auth": "def"},
    }
    payload = {"title": "测试", "body": "内容"}

    with patch("notifier.channels.web_push._get_vapid_keys", return_value={
        "subject": "mailto:test@test.com", "public_key": "pk", "private_key": "priv"
    }):
        with patch("notifier.channels.web_push.webpush") as mock_push:
            result = send_web_push(sub, payload)
            assert result is True
            mock_push.assert_called_once()


def test_send_web_push_no_keys():
    """无 VAPID 密钥时返回 False。"""
    with patch("notifier.channels.web_push._get_vapid_keys", return_value=None):
        result = send_web_push({}, {"title": "t"})
        assert result is False


def test_send_web_push_exception():
    """推送异常时返回 False 不崩溃。"""
    with patch("notifier.channels.web_push._get_vapid_keys", return_value={
        "subject": "s", "public_key": "pk", "private_key": "priv"
    }):
        with patch("notifier.channels.web_push.webpush", side_effect=Exception("fail")):
            result = send_web_push({}, {"title": "t"})
            assert result is False
