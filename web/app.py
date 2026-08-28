from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# A-02: 模块级加载 .env（早于 create_app 冻结 CORS/DATA_DIR 配置）
from analyzer.env import load_env
load_env()

from web.api import documents, collect, opportunities, graph, reports, push, leadership

logger = logging.getLogger(__name__)

# 全局调度器引用（防止被 GC 回收）
_scheduler = None

# P0-01：进程启动时间（模块加载时记录），供 /api/health 自省
from datetime import datetime as _dt
_PROCESS_START = _dt.now()

# M-08：模块加载时冻结进程加载的 commit（与磁盘 HEAD 实时分对比，检测 stale）
def _capture_commit() -> str:
    import os, subprocess
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=root, capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"

_BUILD_COMMIT = _capture_commit()


def _setup_scheduler():
    """配置 APScheduler 定时任务。

    任务计划：
    - 每日凌晨 6:00 抓取全部启用的数据源
    - 每日凌晨 6:30 分析未处理文档（抓取完成后留 30 分钟）
    """
    import os
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler()

    # 每天 12:00 增量爬取 + 分析（合并为一个任务，先爬取后分析）
    scheduler.add_job(
        _scheduled_crawl_and_analyze,
        CronTrigger(hour=12, minute=0),
        id="daily_crawl_analyze",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # P0-02：独立的分析 job（12:30），确保即使当天无新文档也能消化到期 retryable backlog
    scheduler.add_job(
        _scheduled_analyze,
        CronTrigger(hour=12, minute=30),
        id="daily_analyze",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # M-04：摘要改为每分钟轮询（原 */30 无法支持 08:15 等任意 HH:MM 配置）
    scheduler.add_job(
        _scheduled_digest_poll,
        CronTrigger(minute="*"),
        id="digest_poll",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # F-09：每周摘要推送（周一 08:30）保留（周报无用户配置时间）
    scheduler.add_job(
        _scheduled_weekly_digest,
        CronTrigger(day_of_week="mon", hour=8, minute=30),
        id="weekly_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info("APScheduler started: daily_crawl_analyze@12:00, daily_analyze@12:30, digest_poll@*/30min, weekly_digest@Mon08:30")
    return scheduler


def _scheduled_crawl_and_analyze():
    """定时任务：每天 12:00 增量爬取全部数据源 + 分析新文档。

    P1-10：与手动 trigger 互斥（collect + analyze 锁）。
    """
    from collector.config import load_sources_config
    from web.api.collect import _build_adapter
    from web.job_lock import try_acquire_collect, release_collect, try_acquire_analyze, release_analyze

    logger.info("Scheduled task: starting crawl + analyze")

    # 1. 增量爬取（带互斥锁）
    if not try_acquire_collect():
        logger.info("Scheduled crawl skipped: collect lock held (manual trigger running)")
    else:
        try:
            sources = load_sources_config()
            total_new = 0
            for source_name, cfg in sources.items():
                if not cfg.get("enabled"):
                    continue
                try:
                    adapter = _build_adapter(source_name)
                    result = adapter.run()
                    total_new += result.get("new", 0)
                    logger.info(f"Scheduled crawl {source_name}: new={result['new']}, errors={result['errors']}")
                except Exception as e:
                    logger.error(f"Scheduled crawl {source_name} failed: {e}")
            logger.info(f"Scheduled crawl done: {total_new} new documents")
        finally:
            release_collect()

    # 2. 分析文档（P0-02：无条件执行；P1-10：互斥锁）
    if not try_acquire_analyze():
        logger.info("Scheduled analyze skipped: analyze lock held (manual trigger running)")
    else:
        try:
            from analyzer.pipeline import analyze_pending
            from analyzer.llm_client import LLMClient
            client = LLMClient()
            stats = analyze_pending(llm_client=client, limit=200)
            logger.info(f"Scheduled analyze done: {stats}")
        except Exception as e:
            logger.error(f"Scheduled analyze failed: {e}")
        finally:
            release_analyze()


def _scheduled_crawl_all():
    """定时任务：抓取全部启用的数据源。"""
    from collector.config import load_sources_config
    from web.api.collect import _build_adapter

    logger.info("Scheduled crawl: starting for all enabled sources")
    sources = load_sources_config()
    for source_name, cfg in sources.items():
        if not cfg.get("enabled"):
            continue
        try:
            adapter = _build_adapter(source_name)
            result = adapter.run()
            logger.info(f"Scheduled crawl {source_name}: new={result['new']}, errors={result['errors']}")
        except Exception as e:
            logger.error(f"Scheduled crawl {source_name} failed: {e}")


def _scheduled_analyze():
    """定时任务：分析全部未处理文档（P1-10：互斥锁；A-05：LLM preflight）。"""
    from analyzer.pipeline import analyze_pending
    from analyzer.llm_client import LLMClient
    from web.job_lock import try_acquire_analyze, release_analyze

    logger.info("Scheduled analyze: starting")
    if not try_acquire_analyze():
        logger.info("Scheduled analyze skipped: analyze lock held")
        return
    try:
        client = LLMClient()
        # A-05: LLM preflight——不可用则中止本轮（不消耗 attempt_count）
        if not client.health_check():
            logger.warning("Scheduled analyze aborted: LLM health check failed")
            return
        stats = analyze_pending(llm_client=client, limit=100)
        logger.info(f"Scheduled analyze done: {stats}")
    except Exception as e:
        logger.error(f"Scheduled analyze failed: {e}")
    finally:
        release_analyze()


def _scheduled_digest_poll():
    """M-04：每 30 分钟轮询——检查用户 daily_digest_time 是否到点。

    原固定 08:00 不尊重用户配置；改为轮询读 push_settings.daily_digest_time，
    到点（当前 HH:MM == 配置值）且今日未发则发送。
    """
    from datetime import datetime
    from storage.models import PushSettings, PushLog
    try:
        settings = PushSettings.get_or_create("default")
        if not settings.daily_digest_enabled:
            return
        now = datetime.now()
        configured_time = settings.daily_digest_time or "08:00"
        if now.strftime("%H:%M") != configured_time:
            return  # 未到用户配置时间
        # A-04：幂等去重——按 trigger_type=scheduled + 今日日期（不依赖标题 LIKE）
        from storage.database import get_conn
        today = now.strftime("%Y-%m-%d")
        already = get_conn().execute(
            "SELECT 1 FROM push_logs WHERE user_id='default' AND trigger_type='scheduled' "
            "AND sent_at LIKE ? AND delivered=1 LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        if already:
            return
        from notifier.digest_builder import send_daily_digest
        result = send_daily_digest()
        logger.info(f"Scheduled daily digest (poll, time={configured_time}): {result}")
    except Exception as e:
        logger.error(f"Scheduled digest poll failed: {e}")


def _scheduled_weekly_digest():
    """F-09：每周摘要推送（周一）。"""
    try:
        from notifier.digest_builder import send_weekly_digest
        result = send_weekly_digest()
        logger.info(f"Scheduled weekly digest: {result}")
    except Exception as e:
        logger.error(f"Scheduled weekly digest failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库和调度器，关闭时释放。"""
    global _scheduler
    # A-02: .env 已在模块级加载（早于 create_app 冻结配置）
    from storage.models import init_db, close_db
    init_db()  # 无参 → 从 storage.paths.db_path() 派生（尊重 XA_DATA_DIR）
    # 测试环境禁用调度器（_scheduler 被预置为 "disabled" 字符串）
    if _scheduler != "disabled":
        _scheduler = _setup_scheduler()
    yield
    # P1-09：先停止接新 job，再等待在途 job 完成后关闭 DB（避免跨线程 close 竞争）
    if _scheduler and _scheduler != "disabled":
        try:
            _scheduler.pause()  # 停止触发新 job
            _scheduler.shutdown(wait=True)  # 等待在途 job（crawl/analyze）完成
        except Exception as e:
            logger.warning(f"Scheduler shutdown error: {e}")
        _scheduler = None
    close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="雄安信息商机挖掘系统", version="0.1.0", lifespan=lifespan)
    # F-16：CORS 收窄——默认仅 loopback，生产用 CORS_ORIGINS 环境变量显式配置
    import os
    _cors_env = os.environ.get("CORS_ORIGINS", "")
    if _cors_env:
        _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    else:
        _cors_origins = ["http://127.0.0.1:8000", "http://localhost:8000"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        """P0-01 / M-08：运行态自省。

        返回 loaded_commit（进程加载时冻结）+ disk_commit（实时磁盘 HEAD）+
        stale 标志（两者不一致=代码已提交但进程未重启）+ 启动时间 + scheduler。
        """
        disk_commit = _capture_commit()  # 实时磁盘 HEAD
        return {
            "status": "ok",
            "loaded_commit": _BUILD_COMMIT,  # M-08: 进程加载版本（冻结）
            "disk_commit": disk_commit,      # 实时磁盘版本
            "commit": _BUILD_COMMIT,         # 向后兼容字段
            "stale": _BUILD_COMMIT != disk_commit and _BUILD_COMMIT != "unknown",
            "process_started": _PROCESS_START.isoformat(),
            "scheduler": "disabled" if _scheduler == "disabled" else ("running" if _scheduler else "stopped"),
        }

    app.include_router(documents.router, prefix="/api")
    app.include_router(collect.router, prefix="/api")
    app.include_router(opportunities.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(push.router, prefix="/api")
    app.include_router(leadership.router, prefix="/api")

    # 图片静态服务（在 SPA fallback 之前注册）
    # A-02: 用统一 DATA_DIR 派生 + ensure_dirs 确保目录存在 + 无条件挂载
    # （原 if os.path.exists 导致 collector 后建目录时路由缺失）
    from storage.paths import images_dir, ensure_dirs
    ensure_dirs()  # 确保 data/images/snapshots/reports 目录存在
    images_path = images_dir()
    from fastapi.staticfiles import StaticFiles as SF
    app.mount("/images", SF(directory=images_path), name="images")

    # 静态文件服务（生产模式：前端构建后由 FastAPI 直接 serve）
    from fastapi.staticfiles import StaticFiles
    from starlette.exceptions import HTTPException as StarletteHTTPException
    from starlette.responses import FileResponse

    dist_path = os.path.join(os.path.dirname(__file__), "frontend", "dist")
    if os.path.exists(dist_path):

        class SPAStaticFiles(StaticFiles):
            """自定义 StaticFiles：对无文件扩展名的路径返回 index.html（SPA 路由回退）。"""
            async def get_response(self, path: str, scope):
                # /api 与 /api/... 不走 SPA 回退：交由 FastAPI 路由处理
                if path == "api" or path.startswith("api/"):
                    return await super().get_response(path, scope)
                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as ex:
                    if ex.status_code == 404:
                        # 无扩展名的导航请求 → 返回 index.html
                        if "." not in os.path.basename(path):
                            index = os.path.join(dist_path, "index.html")
                            if os.path.exists(index):
                                return FileResponse(index)
                    raise

        app.mount("/", SPAStaticFiles(directory=dist_path, html=True), name="frontend")

    return app
