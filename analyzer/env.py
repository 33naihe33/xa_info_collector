# analyzer/env.py
"""H-01: 统一 .env 加载入口。

CLI（python -m analyzer）和 web lifespan 调用 load_env() 显式加载 .env，
避免依赖外部 shell 已导出的环境变量。
"""
import os
import logging

logger = logging.getLogger(__name__)

_loaded = False


def load_env(env_path: str | None = None) -> None:
    """加载 .env 到 os.environ（不覆盖已存在的环境变量）。

    优先用 python-dotenv；若未装则手写解析（兼容最小部署）。
    """
    global _loaded
    if _loaded:
        return
    path = env_path or os.environ.get("XA_ENV_PATH", ".env")
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        logger.debug(f"Loaded env from {path} via python-dotenv")
    except ImportError:
        _load_env_manual(path)
    _loaded = True


def _load_env_manual(path: str) -> None:
    """手写 .env 解析（python-dotenv 未装时的兜底）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        logger.debug(f"Loaded env from {path} via manual parser")
    except FileNotFoundError:
        logger.debug(f"No .env at {path}, skipping")


def require_api_key() -> str:
    """H-01：校验 ZHIPUAI_API_KEY 存在，缺则 raise SystemExit（CLI 非零退出）。"""
    key = os.environ.get("ZHIPUAI_API_KEY", "")
    if not key:
        raise SystemExit(
            "ZHIPUAI_API_KEY 未配置。请在 .env 设置或导出环境变量后重试。"
            "（CLI 不会在缺 key 时逐条写 retryable）"
        )
    return key
