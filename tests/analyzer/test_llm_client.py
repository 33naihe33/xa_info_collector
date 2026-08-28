# tests/analyzer/test_llm_client.py
import json
import pytest
from unittest.mock import patch, MagicMock
from analyzer.llm_client import LLMClient


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_client_calls_create_with_json_format(mock_zhipuai_class):
    """LLMClient 应调用 GLM create，使用 json_object 格式。"""
    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key")
    result = client.chat_json(system="你是助手", user="你好")

    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "glm-4-flash"
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["messages"][0]["role"] == "system"
    assert result == {"result": "ok"}


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_client_handles_invalid_json(mock_zhipuai_class):
    """LLM 返回非 JSON 时应返回 None 而非崩溃。"""
    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="这不是JSON"))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key")
    result = client.chat_json(system="s", user="u")
    assert result is None


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_client_logs_to_db(mock_zhipuai_class, tmp_path):
    """每次调用应记录到 raw_llm_logs。"""
    from storage.models import init_db, close_db, get_conn
    init_db(str(tmp_path / "test.db"))

    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"a": 1}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key")
    client.chat_json(system="s", user="u", doc_id=42, task_type="test")

    rows = get_conn().execute("SELECT * FROM raw_llm_logs").fetchall()
    assert len(rows) == 1
    assert rows[0]["doc_id"] == 42
    assert rows[0]["task_type"] == "test"
    close_db()
