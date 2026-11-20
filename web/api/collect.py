import logging
from datetime import date
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from storage.models import CrawlRun

logger = logging.getLogger(__name__)
router = APIRouter()


class RangeCollectRequest(BaseModel):
    sources: list[str]
    date_from: date
    date_to: date


def _build_adapter(source: str):
    """根据 source 名称构造对应 adapter 实例。

    新增数据源时在此注册 adapter 类即可（懒导入避免启动时加载全部依赖）。
    """
    if source == "xiongan_portal":
        from collector.adapters.xiongan_portal import XionganPortalAdapter
        return XionganPortalAdapter()
    if source == "rmxiongan":
        from collector.adapters.rmxiongan import RmxionganAdapter
        return RmxionganAdapter()
    if source == "hebccw":
        from collector.adapters.hebccw import HebccwAdapter
        return HebccwAdapter()
    if source == "rongcheng_gov":
        from collector.adapters.rongcheng import RongchengAdapter
        return RongchengAdapter()
    if source == "xiongxian_gov":
        from collector.adapters.xiongxian import XiongxianAdapter
        return XiongxianAdapter()
    if source == "anxin_gov":
        from collector.adapters.anxin import AnxinAdapter
        return AnxinAdapter()
    # 微信公众号（搜狗搜索）
    if source.startswith("wechat_"):
        from collector.adapters.wechat_search import (
            XionganFabuAdapter, RongchengFabuAdapter,
            XiongzhouVoiceAdapter, YanlingVoiceAdapter, XionganEduAdapter,
        )
        adapters = {
            "wechat_xiongan_fabu": XionganFabuAdapter,
            "wechat_rongcheng_fabu": RongchengFabuAdapter,
            "wechat_xiongzhou_voice": XiongzhouVoiceAdapter,
            "wechat_yanling_voice": YanlingVoiceAdapter,
            "wechat_xiongan_edu": XionganEduAdapter,
        }
        if source in adapters:
            return adapters[source]()
    raise ValueError(f"Unknown source: {source}")


@router.post("/collect/trigger")
def trigger_collect(background_tasks: BackgroundTasks, source: str = "xiongan_portal"):
    """触发抓取（后台执行）。

    P1-10：与定时任务互斥，已在运行则返回 409。
    """
    from web.job_lock import try_acquire_collect, release_collect
    from fastapi import HTTPException

    adapter = _build_adapter(source)

    def _run():
        try:
            adapter.run()
        finally:
            release_collect()

    # 非阻塞尝试获取锁，失败说明已有抓取在运行
    if not try_acquire_collect():
        raise HTTPException(status_code=409, detail="collect already running")
    background_tasks.add_task(_run)
    return {"status": "started", "source": source}


@router.post("/collect/range")
def trigger_range_collect(request: RangeCollectRequest, background_tasks: BackgroundTasks):
    from collector.config import load_sources_config
    from web.job_lock import try_acquire_collect, release_collect

    if not request.sources or request.date_from > request.date_to:
        raise HTTPException(status_code=400, detail="invalid date range or sources")
    configured = load_sources_config()
    sources = list(dict.fromkeys(request.sources))
    if any(name not in configured or not configured[name].get("enabled") for name in sources):
        raise HTTPException(status_code=400, detail="unknown or disabled source")
    if not try_acquire_collect():
        raise HTTPException(status_code=409, detail="collect already running")

    def _run():
        try:
            for source in sources:
                try:
                    _build_adapter(source).run(since=request.date_from.isoformat(), until=request.date_to.isoformat())
                except Exception:
                    logger.exception("Range collect failed for %s", source)
        finally:
            release_collect()

    background_tasks.add_task(_run)
    return {"status": "started", "source_count": len(sources), "sources": sources}


@router.get("/collect/status")
def collect_status(source: str = "xiongan_portal"):
    """获取某数据源最近一次抓取状态（任意栏目）。"""
    run = CrawlRun.latest_run_for_source(source)
    if not run:
        return {"source": source, "last_run": None}
    return {"source": source, "last_run": run.to_dict()}


@router.get("/collect/sources")
def list_sources():
    """列出所有数据源及其配置状态和文档数量。"""
    from collector.config import load_sources_config
    from storage.models import Document

    sources = load_sources_config()
    result = []
    for name, cfg in sources.items():
        result.append({
            "name": name,
            "display_name": cfg.get("name", name),
            "enabled": cfg.get("enabled", False),
            "doc_count": Document.count(source=name) if cfg.get("enabled") else 0,
            "categories": list(cfg.get("categories", {}).keys()) if cfg.get("categories") else [],
        })
    return {"sources": result}


@router.post("/analyze/trigger")
def trigger_analyze(background_tasks: BackgroundTasks):
    """触发 LLM 分析（后台执行）。

    P1-10：与定时任务互斥，已在运行则返回 409。
    """
    from analyzer.pipeline import analyze_pending
    from analyzer.llm_client import LLMClient
    from web.job_lock import try_acquire_analyze, release_analyze
    from fastapi import HTTPException

    def _run():
        try:
            client = LLMClient()
            # A-05: LLM preflight——不可用则中止（不消耗 attempt_count）
            if not client.health_check():
                logger.warning("Manual analyze aborted: LLM health check failed")
                return
            analyze_pending(llm_client=client)
        finally:
            release_analyze()

    if not try_acquire_analyze():
        raise HTTPException(status_code=409, detail="analyze already running")
    background_tasks.add_task(_run)
    return {"status": "started"}
