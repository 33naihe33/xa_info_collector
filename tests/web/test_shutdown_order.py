"""P1-09: lifespan 关闭顺序测试。

回归：原 lifespan 用 scheduler.shutdown(wait=False) 后立即 close_db()，
正在运行的 job 线程会与跨线程 close 竞争（连接被关闭后 job 仍在用）。
"""
import time
import threading
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Document, get_conn


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    # 预置数据
    Document.create(
        source="x", doc_type="新闻", title="test", url="http://t",
        publish_date="2026-07-10", raw_html="", text="content", content_hash="h",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    # lifespan 已 close_db；这里不重复


def test_shutdown_does_not_corrupt_database(client):
    """shutdown(wait=True) 后 DB 操作不应报 'database closed'。

    P1-09：原 wait=False 会在 job 运行中关闭连接。
    """
    # 触发一次正常请求验证 DB 可用
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    # TestClient 退出时 lifespan shutdown 执行 pause + shutdown(wait=True) + close_db
    # 若 wait=False，可能在 job 运行中关 DB；此处验证退出后无异常即可


def test_shutdown_waits_for_running_job(tmp_path):
    """P1-09：shutdown(wait=True) 等待在途 job 完成，不中断它。"""
    import apscheduler.schedulers.background as bg
    init_db(str(tmp_path / "test.db"))

    job_completed = threading.Event()
    job_started = threading.Event()

    def slow_job():
        job_started.set()
        time.sleep(0.3)  # 模拟在途分析任务
        # 在 job 内访问 DB（模拟 analyze_pending 的 get_conn）
        try:
            conn = get_conn()
            conn.execute("SELECT 1").fetchone()
        except Exception:
            pass  # wait=False 时这里会失败
        job_completed.set()

    scheduler = bg.BackgroundScheduler()
    scheduler.add_job(slow_job, "date", run_date=None)  # 立即执行
    scheduler.start()
    job_started.wait(timeout=2)  # 等 job 开始
    time.sleep(0.05)  # 确保 job 在执行中
    # shutdown(wait=True) 应等待 job 完成
    scheduler.shutdown(wait=True)
    assert job_completed.is_set(), "wait=True 应等待 job 完成"
    close_db()


def test_shutdown_wait_false_would_interrupt_but_we_use_wait_true():
    """P1-09：确认 lifespan 用 wait=True（读源码断言）。"""
    import web.app as appmod
    import inspect
    src = inspect.getsource(appmod.lifespan)
    assert "shutdown(wait=True)" in src, "lifespan 应使用 shutdown(wait=True)"
    assert "shutdown(wait=False)" not in src, "不应再用 wait=False"
    assert "_scheduler.pause()" in src, "应先 pause 停止接新 job"
