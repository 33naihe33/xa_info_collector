"""P0-01: /api/health 运行态自省测试。

回归用例：曾出现"磁盘代码已修、进程未重启"的误判（旧进程仍返回 500）。
health 端点暴露 commit + 进程启动时间，便于验收时确认进程加载了新代码。
"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_health_returns_200_with_commit_and_start_time(client):
    """/api/health → 200 + commit + process_started + scheduler 字段。"""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # commit 应是字符串（git 可用时为短 hash，否则 unknown）
    assert isinstance(data["commit"], str)
    assert len(data["commit"]) > 0
    # process_started 应是 ISO 时间
    assert "process_started" in data
    assert "T" in data["process_started"]  # ISO 格式
    # scheduler 状态
    assert data["scheduler"] in ("running", "stopped", "disabled")


def test_health_commit_is_not_unknown_in_repo(client):
    """在 git 仓库内运行时，commit 应能解析到真实短 hash（非 unknown）。"""
    resp = client.get("/api/health")
    commit = resp.json()["commit"]
    # 本项目是 git 仓库，commit 应解析成功（7 位短 hash）
    assert commit != "unknown", f"应解析到 git commit，实际 {commit}"
    assert len(commit) >= 7
