# tests/analyzer/test_llm_timeout.py
"""LLM 超时控制测试。"""
import pytest
import time
from unittest.mock import patch, MagicMock
from analyzer.llm_client import LLMClient, _call_glm_with_timeout, LLMCallTimeout


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_timeout_returns_none(mock_zhipuai_class):
    """LLM 超时应返回 None 而非阻塞。"""
    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client

    def slow_create(**kwargs):
        time.sleep(2)  # 模拟慢响应
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content='{"a": 1}'))]
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return resp

    mock_client.chat.completions.create = slow_create

    client = LLMClient(api_key="fake-key", timeout=1)  # 1秒超时
    result = client.chat_json(system="s", user="u", task_type="test")
    assert result is None  # 超时返回 None


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_normal_call_succeeds(mock_zhipuai_class):
    """正常调用应返回结果。"""
    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key", timeout=30)
    result = client.chat_json(system="s", user="u", task_type="test")
    assert result == {"result": "ok"}


def test_call_glm_timeout_raises():
    """_call_glm_with_timeout 超时抛 LLMCallTimeout。"""
    mock_client = MagicMock()

    def slow(**kwargs):
        time.sleep(3)

    mock_client.chat.completions.create = slow
    with pytest.raises(LLMCallTimeout):
        _call_glm_with_timeout(mock_client, "model", [], {}, timeout=1)
