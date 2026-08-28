# analyzer/llm_client.py
"""智谱 GLM 客户端封装。

特性：
- chat_json()：调用 GLM 返回结构化 JSON（response_format=json_object）
- 自动解析 JSON，失败返回 None
- 每次调用记录到 raw_llm_logs（可回溯）
- 支持重试（SDK 内置 max_retries）
- 超时控制：单次调用超时返回 None，不阻塞 pipeline
"""
import json
import os
import time
import logging
import threading
from pathlib import Path

from zhipuai import ZhipuAI

from analyzer.rules_loader import get_model_name
from storage.models import LLMLog

logger = logging.getLogger(__name__)

# 单次 LLM 调用超时时间（秒）。超时返回 None，不阻塞 pipeline。
# 可用 XA_LLM_TIMEOUT 环境变量覆盖（GLM 高负载时 30s 偏紧，实测 50% 超时）
LLM_TIMEOUT = int(os.environ.get("XA_LLM_TIMEOUT", "60"))
# F-18：并发超时泄漏线程上限（超时后 worker 无法取消，限制累积）
_MAX_LEAKED_THREADS = 10
_leaked_thread_count = 0
_leaked_lock = threading.Lock()


class LLMCallTimeout(Exception):
    """LLM 调用超时。"""


def _call_glm_with_timeout(client, model, messages, response_format, timeout=LLM_TIMEOUT):
    """在子线程中调用 GLM，超时则放弃结果。

    zhipuai SDK 的 create() 不支持 timeout 参数，通过线程隔离实现超时控制。
    F-18：超时后 worker 线程无法取消（daemon），用全局计数器限制泄漏累积，
    超过 _MAX_LEAKED_THREADS 时拒绝发起新调用（避免线程无限增长）。
    """
    global _leaked_thread_count
    # F-18：泄漏线程过多时拒绝新调用
    with _leaked_lock:
        if _leaked_thread_count >= _MAX_LEAKED_THREADS:
            raise LLMCallTimeout(
                f"Too many leaked timeout threads ({_leaked_thread_count}), "
                f"rejecting new call to avoid thread accumulation"
            )

    result = {"response": None, "error": None}
    done = threading.Event()

    def _worker():
        global _leaked_thread_count
        try:
            result["response"] = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format=response_format,
            )
        except Exception as e:
            result["error"] = e
        finally:
            done.set()
            # 若主线程已超时（done 被 set 时主线程可能已离开），递减泄漏计数
            with _leaked_lock:
                _leaked_thread_count = max(0, _leaked_thread_count - 1)

    thread = threading.Thread(target=_worker, daemon=True)
    with _leaked_lock:
        _leaked_thread_count += 1
    thread.start()
    if not done.wait(timeout=timeout):
        # F-18：超时——worker 仍在运行（泄漏），计数保留由 worker finally 递减
        logger.warning(
            f"GLM call exceeded {timeout}s, worker thread leaked "
            f"(total leaked: {_leaked_thread_count})"
        )
        raise LLMCallTimeout(f"GLM call exceeded {timeout}s")
    if result["error"]:
        raise result["error"]
    return result["response"]


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: int = LLM_TIMEOUT):
        self.api_key = api_key or os.environ.get("ZHIPUAI_API_KEY", "")
        self.model = model or get_model_name()
        self.timeout = timeout
        self.client = ZhipuAI(api_key=self.api_key) if self.api_key else None
        if not self.client:
            logger.warning("ZHIPUAI_API_KEY not set, LLM calls will fail")

    def chat_json(self, *, system: str, user: str,
                  doc_id: int | None = None, task_type: str = "unknown") -> dict | None:
        """调用 GLM 并返回解析后的 JSON dict。失败或超时返回 None。"""
        if not self.client:
            logger.error("LLM client not initialized (no API key)")
            return None

        start = time.time()
        try:
            response = _call_glm_with_timeout(
                self.client, self.model,
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                {"type": "json_object"},
                timeout=self.timeout,
            )
        except LLMCallTimeout:
            logger.warning(f"GLM call timed out ({self.timeout}s) for doc={doc_id} task={task_type}")
            LLMLog.log(doc_id=doc_id, task_type=task_type, model=self.model,
                       prompt=user[:500], response=f"TIMEOUT after {self.timeout}s")
            return None
        except Exception as e:
            logger.error(f"GLM API call failed: {e}")
            LLMLog.log(doc_id=doc_id, task_type=task_type, model=self.model,
                       prompt=user[:500], response=f"ERROR: {e}")
            return None

        duration_ms = int((time.time() - start) * 1000)
        content = response.choices[0].message.content
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        completion_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        # 记录日志
        LLMLog.log(
            doc_id=doc_id, task_type=task_type, model=self.model,
            prompt=user[:2000], response=content[:4000],
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )

        # 解析 JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse GLM response as JSON: {content[:200]}")
            return None

    def health_check(self) -> bool:
        """H-01：低成本 LLM 健康探测（1 token）。返回 True=可用，False=不可用。"""
        if not self.client:
            return False
        try:
            resp = _call_glm_with_timeout(
                self.client, self.model,
                [{"role": "user", "content": "ping"}],
                {"type": "json_object"},
                timeout=10,
            )
            return resp is not None
        except Exception as e:
            logger.warning(f"LLM health check failed: {e}")
            return False
