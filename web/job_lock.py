# web/job_lock.py
"""P1-10: 跨模块 job 互斥锁。

手动 trigger（collect/analyze）与 APScheduler 定时任务可重叠运行，
导致重复 LLM 计费、重复商机/调研、计数丢更新。本模块提供跨 web.api.collect
与 web.app 共享的 threading.Lock，用非阻塞 acquire 避免手动触发阻塞 cron。
"""
import threading

# 抓取互斥（手动 trigger_collect + _scheduled_crawl_and_analyze 共享）
_collect_lock = threading.Lock()

# 分析互斥（手动 trigger_analyze + _scheduled_crawl_and_analyze + _scheduled_analyze 共享）
_analyze_lock = threading.Lock()


def try_acquire_collect() -> bool:
    """非阻塞尝试获取抓取锁。成功返回 True，已锁定返回 False。"""
    return _collect_lock.acquire(blocking=False)


def release_collect() -> None:
    """释放抓取锁（仅持有者调用）。"""
    try:
        _collect_lock.release()
    except RuntimeError:
        pass  # 未持有，忽略


def try_acquire_analyze() -> bool:
    """非阻塞尝试获取分析锁。"""
    return _analyze_lock.acquire(blocking=False)


def release_analyze() -> None:
    """释放分析锁。"""
    try:
        _analyze_lock.release()
    except RuntimeError:
        pass
