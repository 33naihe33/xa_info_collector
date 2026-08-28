"""SQLite 连接管理 — 每线程独立连接模型。

每个工作线程（FastAPI 请求线程、APScheduler 后台线程、测试线程）获得独立的
sqlite3.Connection，通过注册表管理。连接在首次 get_conn() 时懒创建，
close_db() 关闭所有线程的连接。

R-05 连接生命周期：
- check_same_thread=False（允许连接被任意线程关闭，但仍只交给所属线程使用）
- 应用关闭时应先 shutdown 调度器/线程池并 join 所有工作线程，再调 close_db()
- close_db() 在主线程统一关闭所有连接（check_same_thread=False 使跨线程关闭合法）
- _close_all_connections_locked 关闭失败时记录 warning（不再静默吞掉）

关键属性：
- busy_timeout=5000（写锁等待最多5秒）
- journal_mode=WAL（读写并发）
- foreign_keys=ON
"""
import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH: str | None = None
_connections: dict[int, sqlite3.Connection] = {}
_lock = threading.Lock()
_schema_ensured = False


def _create_connection(db_path: str) -> sqlite3.Connection:
    """创建一个新的 SQLite 连接并设置 PRAGMA。

    R-05：check_same_thread=False，允许主线程在 close_db() 时关闭工作线程
    创建的连接（关闭操作本身是线程安全的；日常使用仍只由所属线程访问）。
    """
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(db_path: str | None = None) -> None:
    """初始化数据库：存储路径，确保目录存在。

    A-02：db_path=None 时从 storage.paths.db_path() 派生（尊重 XA_DATA_DIR）。
    幂等："first init wins" — 如果 _DB_PATH 已设置（非None），则跳过。
    要切换数据库路径，必须先调用 close_db()。
    """
    global _DB_PATH

    if db_path is None:
        from storage.paths import db_path as _dp
        db_path = _dp()

    with _lock:
        if _DB_PATH is not None:
            return  # 幂等：已初始化，忽略后续调用（包括 lifespan 的默认参数）

        _DB_PATH = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    """获取当前线程的 SQLite 连接。不存在则懒创建。"""
    global _DB_PATH
    if _DB_PATH is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    tid = threading.get_ident()
    with _lock:
        conn = _connections.get(tid)
        if conn is not None:
            return conn

    # 在锁外创建连接（避免长时间持锁）
    conn = _create_connection(_DB_PATH)
    with _lock:
        # 双检：可能其他线程已经创建了
        existing = _connections.get(tid)
        if existing is not None:
            conn.close()
            return existing
        _connections[tid] = conn
    return conn


def get_db() -> sqlite3.Connection:
    """get_conn 的别名，供上层导入使用。"""
    return get_conn()


def _close_all_connections_locked() -> None:
    """关闭所有线程的连接（调用方必须持有 _lock）。

    R-05：关闭失败记录 warning（不再静默吞掉）。check_same_thread=False 使
    主线程关闭工作线程创建的连接合法。连接无论关闭成功与否都从注册表移除。
    """
    global _connections
    for tid, conn in _connections.items():
        try:
            conn.close()
        except Exception as e:
            logger.warning("关闭线程 %s 的数据库连接失败: %s", tid, e)
    _connections = {}


def close_thread_connection() -> None:
    """关闭当前线程的连接（工作线程退出时调用）。

    R-05：供线程池/调度器任务退出时主动清理自己的连接，避免遗留。
    """
    tid = threading.get_ident()
    with _lock:
        conn = _connections.pop(tid, None)
    if conn is not None:
        try:
            conn.close()
        except Exception as e:
            logger.warning("关闭线程 %s 的数据库连接失败: %s", tid, e)


def close_db() -> None:
    """关闭所有线程的数据库连接，重置状态。

    R-05：调用方应先 shutdown 调度器/线程池并 join 工作线程，再调用本函数。
    check_same_thread=False 允许主线程统一关闭所有连接。
    """
    global _DB_PATH, _schema_ensured
    with _lock:
        _close_all_connections_locked()
        _DB_PATH = None
        _schema_ensured = False
