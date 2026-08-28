from __future__ import annotations
import os
import sqlite3
import hashlib
import logging
from datetime import datetime, timedelta
from storage.database import get_conn, close_db  # noqa: F401  (re-exported for callers)

logger = logging.getLogger(__name__)


def image_url_for_api(local_path: str) -> str:
    """将本地图片路径转换为前端可访问的 /images/ URL。

    A-02：从 storage.paths.images_dir() 派生，不硬编码 "data/images/"。
    """
    if not local_path:
        return ""
    if local_path.startswith("http"):
        return local_path  # 远程URL直接返回
    from storage.paths import images_dir
    img_base = images_dir()
    # {DATA_DIR}/images/hash/file.jpg → /images/hash/file.jpg
    if local_path.startswith(img_base + "/"):
        return "/images/" + local_path[len(img_base) + 1:]
    if "data/images/" in local_path:  # 向后兼容旧路径
        return "/" + local_path.split("data/", 1)[1]
    return local_path


def resolve_image_path_for_export(url_or_path: str) -> str:
    """将 API URL 或本地路径解析为服务器可读的本地文件路径（仅 exporter 使用）。

    A-02：从 storage.paths.images_dir() 派生。
    """
    if not url_or_path:
        return ""
    if url_or_path.startswith("http"):
        return url_or_path  # 远程URL
    from storage.paths import images_dir
    img_base = images_dir()
    if url_or_path.startswith("/images/"):
        return img_base + "/" + url_or_path[len("/images/"):]  # /images/hash/file → {DATA_DIR}/images/hash/file
    return url_or_path  # 已经是本地路径

class IntegrityError(sqlite3.IntegrityError):
    pass


# ---- DDL ----
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    doc_type TEXT NOT NULL DEFAULT '新闻',
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    publish_date TEXT NOT NULL,
    crawled_at TEXT NOT NULL,
    raw_html TEXT,
    text TEXT,
    content_hash TEXT NOT NULL,
    is_analyzed INTEGER NOT NULL DEFAULT 0,
    dead_letter INTEGER NOT NULL DEFAULT 0  -- P0-04: 必要任务 permanent_error，需人工介入
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

-- 迁移：添加 images 字段（存储文章图片URL列表的JSON）
-- 使用 ALTER TABLE 兼容已有数据库


CREATE TABLE IF NOT EXISTS crawl_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT,
    error TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    retried INTEGER NOT NULL DEFAULT 0,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    category TEXT
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    new_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_crawled_date TEXT,  -- 上次成功抓取到的最新日期，增量爬取基准
    category TEXT
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    aliases TEXT DEFAULT '[]',
    source_doc_ids TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity_id INTEGER NOT NULL,
    to_entity_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    source_doc_id INTEGER,
    confidence REAL DEFAULT 1.0,
    publish_date TEXT,
    FOREIGN KEY (from_entity_id) REFERENCES entities(id),
    FOREIGN KEY (to_entity_id) REFERENCES entities(id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_doc_id INTEGER,
    business_line TEXT NOT NULL,
    opp_type TEXT NOT NULL,
    fin_scale TEXT,
    fin_products TEXT DEFAULT '[]',
    target_client TEXT,
    buyer_dept TEXT,
    relocate_from TEXT,
    relocate_scale TEXT,
    relocate_phase TEXT,
    trigger_event TEXT,
    timing_window TEXT,
    insight TEXT,
    action_suggest TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'signal',
    publish_date TEXT,
    deadline TEXT,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_llm_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER,
    task_type TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt TEXT,
    response TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    content TEXT DEFAULT '{}',
    opportunity_ids TEXT DEFAULT '[]',
    docx_path TEXT,
    pdf_path TEXT,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    channel TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    keys TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_settings (
    user_id TEXT PRIMARY KEY DEFAULT 'default',
    instant_enabled INTEGER NOT NULL DEFAULT 1,
    instant_threshold TEXT NOT NULL DEFAULT 'high',
    daily_limit INTEGER NOT NULL DEFAULT 5,
    focus_lines TEXT DEFAULT '[]',
    daily_digest_enabled INTEGER NOT NULL DEFAULT 1,
    daily_digest_time TEXT NOT NULL DEFAULT '08:00',
    weekly_digest_enabled INTEGER NOT NULL DEFAULT 1,
    digest_threshold TEXT NOT NULL DEFAULT 'medium',
    dnd_enabled INTEGER NOT NULL DEFAULT 1,
    dnd_start TEXT NOT NULL DEFAULT '22:00',
    dnd_end TEXT NOT NULL DEFAULT '07:00'
);

CREATE TABLE IF NOT EXISTS push_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    opportunity_id INTEGER,
    trigger_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0,
    clicked INTEGER NOT NULL DEFAULT 0,
    clicked_at TEXT
);

CREATE TABLE IF NOT EXISTS leadership_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_doc_id INTEGER,
    leader_name TEXT NOT NULL,
    leader_title TEXT,
    visit_date TEXT,
    visit_topic TEXT,
    visited_entities TEXT DEFAULT '[]',
    summary TEXT,
    priority TEXT DEFAULT 'medium',
    publish_date TEXT,
    images TEXT DEFAULT '[]',
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_task_states (
    doc_id INTEGER NOT NULL,
    task_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_retry_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (doc_id, task_type)
);

-- H-03: enrichment 独立状态表（按 opportunity_id + version，同文档多商机各自独立）
CREATE TABLE IF NOT EXISTS opportunity_enrichment_states (
    opportunity_id INTEGER NOT NULL,
    version TEXT NOT NULL DEFAULT 'v1',
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (opportunity_id, version)
);
"""


def init_db(db_path: str | None = None) -> None:
    """初始化数据库路径 + 确保 schema 存在。

    A-02：db_path=None 时从 storage.paths.db_path() 派生（尊重 XA_DATA_DIR）。
    幂等：如果 database 模块标记 schema 已确保，则跳过。
    """
    from storage.database import init_db as _init, _schema_ensured
    if db_path is None:
        from storage.paths import db_path as _dp
        db_path = _dp()
    _init(db_path)
    # 在首次连接上执行 schema（幂等 CREATE IF NOT EXISTS）
    conn = get_conn()
    conn.executescript(SCHEMA_SQL)
    # 迁移：添加 images 列（如果不存在）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(documents)").fetchall()]
    if "images" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN images TEXT DEFAULT '[]'")
    # P0-04 迁移：添加 dead_letter 列（必要任务 permanent_error 的文档标记）
    if "dead_letter" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN dead_letter INTEGER NOT NULL DEFAULT 0")
    # 迁移：crawl_errors 添加重试列
    err_cols = [r[1] for r in conn.execute("PRAGMA table_info(crawl_errors)").fetchall()]
    if "retry_count" not in err_cols:
        conn.execute("ALTER TABLE crawl_errors ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
    if "next_retry_at" not in err_cols:
        conn.execute("ALTER TABLE crawl_errors ADD COLUMN next_retry_at TEXT")
    if "status" not in err_cols:
        conn.execute("ALTER TABLE crawl_errors ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
    if "category" not in err_cols:
        conn.execute("ALTER TABLE crawl_errors ADD COLUMN category TEXT")
    # 迁移：crawl_runs 添加 category 列（R-03 栏目级游标）
    cr_cols = [r[1] for r in conn.execute("PRAGMA table_info(crawl_runs)").fetchall()]
    if "category" not in cr_cols:
        conn.execute("ALTER TABLE crawl_runs ADD COLUMN category TEXT")
    # 迁移：retry_count 语义修正——历史记录从 0 开始，首次失败现写 1。
    # 把已有 pending 且 retry_count=0 的记录纠正为 1（已 retried/dead 的不动）。
    conn.execute(
        "UPDATE crawl_errors SET retry_count = 1 "
        "WHERE status = 'pending' AND (retry_count = 0 OR retry_count IS NULL)"
    )
    # P1-06 迁移：crawl_errors NULL-safe 唯一索引（防止重复 URL 行）
    # 去重：按 (source, COALESCE(category,''), url) 保留 MIN(id)，仅 url 非空的去重
    # （url IS NULL 的列表级错误允许多条，因 url 是唯一键组成部分）
    ce_idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_crawl_errors_unique'"
    ).fetchone()
    if not ce_idx:
        dup_count = conn.execute(
            "SELECT COUNT(*) FROM crawl_errors WHERE url IS NOT NULL AND id NOT IN ("
            "SELECT MIN(id) FROM crawl_errors WHERE url IS NOT NULL "
            "GROUP BY source, COALESCE(category, ''), url)"
        ).fetchone()[0]
        if dup_count > 0:
            conn.execute(
                "DELETE FROM crawl_errors WHERE url IS NOT NULL AND id NOT IN ("
                "SELECT MIN(id) FROM crawl_errors WHERE url IS NOT NULL "
                "GROUP BY source, COALESCE(category, ''), url)"
            )
            logger.info("crawl_errors 去重：删除 %d 条重复 URL", dup_count)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_crawl_errors_unique "
            "ON crawl_errors(source, COALESCE(category, ''), url) WHERE url IS NOT NULL"
        )
        logger.info("crawl_errors 唯一索引已创建（NULL 安全，仅 url 非空）")
    # F-20 迁移：push_subscriptions (user_id, endpoint) 唯一索引 + 去重
    ps_idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_push_sub_unique'"
    ).fetchone()
    if not ps_idx:
        ps_dup = conn.execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE id NOT IN ("
            "SELECT MIN(id) FROM push_subscriptions GROUP BY user_id, endpoint)"
        ).fetchone()[0]
        if ps_dup > 0:
            conn.execute(
                "DELETE FROM push_subscriptions WHERE id NOT IN ("
                "SELECT MIN(id) FROM push_subscriptions GROUP BY user_id, endpoint)"
            )
            logger.info("push_subscriptions 去重：删除 %d 条重复", ps_dup)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_push_sub_unique "
            "ON push_subscriptions(user_id, endpoint)"
        )
    # 迁移：relations 唯一索引（NULL 安全 + 兼容旧索引）
    # R-06：生产库可能已存在旧式 idx_relations_unique（裸 source_doc_id，无 COALESCE），
    # 需检测定义后分支处理：
    #   A. 旧索引（无 COALESCE）→ DROP + 去重 + CREATE 表达式索引（同事务）
    #   B. 索引不存在 → 去重 + CREATE 表达式索引
    #   C. 已是 COALESCE 表达式索引 → 仅幂等去重
    # NULL 安全：表达式索引用 COALESCE(source_doc_id, -1)，SQLite 唯一索引对 NULL 视为互异。
    idx_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_relations_unique'"
    ).fetchone()
    idx_sql = idx_row["sql"] if idx_row else None
    has_coalesce = idx_sql and "COALESCE" in idx_sql.upper()

    # 去重（幂等）：按 (from_entity_id, to_entity_id, relation_type, COALESCE(source_doc_id,-1))
    # 保留 MIN(id)。放在事务中，仅在需要 DROP/CREATE 索引时记录删除数。
    if idx_sql is None or not has_coalesce:
        # 需要建/重建索引 → 先去重
        dup_count = conn.execute(
            "SELECT COUNT(*) FROM relations WHERE id NOT IN ("
            "SELECT MIN(id) FROM relations GROUP BY from_entity_id, to_entity_id, "
            "relation_type, COALESCE(source_doc_id, -1))"
        ).fetchone()[0]
        if dup_count > 0:
            conn.execute(
                "DELETE FROM relations WHERE id NOT IN ("
                "SELECT MIN(id) FROM relations GROUP BY from_entity_id, to_entity_id, "
                "relation_type, COALESCE(source_doc_id, -1))"
            )
            logger.info("relations 去重：删除 %d 条重复关系", dup_count)

    if idx_sql is not None and not has_coalesce:
        # 分支 A：旧索引 → DROP + CREATE 表达式索引
        conn.execute("DROP INDEX IF EXISTS idx_relations_unique")
        conn.execute(
            "CREATE UNIQUE INDEX idx_relations_unique ON relations("
            "from_entity_id, to_entity_id, relation_type, COALESCE(source_doc_id, -1))"
        )
        logger.info("relations 唯一索引升级为 NULL 安全（COALESCE）表达式索引")
    elif idx_sql is None:
        # 分支 B：索引不存在 → 创建
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_relations_unique ON relations("
            "from_entity_id, to_entity_id, relation_type, COALESCE(source_doc_id, -1))"
        )
        logger.info("relations 唯一索引已创建（NULL 安全表达式索引）")
    # 分支 C：已是 COALESCE 表达式索引 → 无需动作（去重已在上面幂等执行）
    # H-03 迁移：确保 opportunity_enrichment_states 表存在（独立 enrichment 断点）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS opportunity_enrichment_states ("
        "opportunity_id INTEGER NOT NULL, version TEXT NOT NULL DEFAULT 'v1', "
        "status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0, "
        "last_error TEXT, updated_at TEXT NOT NULL, "
        "PRIMARY KEY (opportunity_id, version))"
    )
    # 迁移：确保 leadership_visits 表存在
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    if "leadership_visits" not in tables:
        conn.execute(
            """CREATE TABLE leadership_visits (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               source_doc_id INTEGER,
               leader_name TEXT NOT NULL,
               leader_title TEXT,
               visit_date TEXT,
               visit_topic TEXT,
               visited_entities TEXT DEFAULT '[]',
               summary TEXT,
               priority TEXT DEFAULT 'medium',
               publish_date TEXT,
               images TEXT DEFAULT '[]',
               extracted_at TEXT NOT NULL
            )"""
        )
    conn.commit()


class Document:
    """documents 表的数据访问对象。"""

    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.source = row["source"]
        self.doc_type = row["doc_type"]
        self.title = row["title"]
        self.url = row["url"]
        self.publish_date = row["publish_date"]
        self.crawled_at = row["crawled_at"]
        self.raw_html = row["raw_html"]
        self.text = row["text"]
        self.content_hash = row["content_hash"]
        self.is_analyzed = bool(row["is_analyzed"])
        self.dead_letter = bool(row["dead_letter"]) if "dead_letter" in row.keys() else False
        self.images = row["images"] if "images" in row.keys() else "[]"

    @classmethod
    def create(cls, *, source, doc_type, title, url, publish_date,
               raw_html, text, content_hash, images="[]") -> "Document":
        conn = get_conn()
        crawled_at = datetime.now().isoformat()
        try:
            cur = conn.execute(
                """INSERT INTO documents
                   (source, doc_type, title, url, publish_date, crawled_at,
                    raw_html, text, content_hash, is_analyzed, images)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (source, doc_type, title, url, publish_date, crawled_at,
                 raw_html, text, content_hash, images),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, doc_id: int) -> "Document | None":
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_by_url(cls, url: str) -> "Document | None":
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM documents WHERE url = ?", (url,)
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, *, source: str | None = None, limit: int = 50,
             offset: int = 0) -> list["Document"]:
        conn = get_conn()
        if source:
            rows = conn.execute(
                """SELECT * FROM documents WHERE source = ?
                   ORDER BY publish_date DESC LIMIT ? OFFSET ?""",
                (source, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM documents
                   ORDER BY publish_date DESC LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def count(cls, source: str | None = None) -> int:
        conn = get_conn()
        if source:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM documents WHERE source = ?", (source,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM documents").fetchone()
        return row["c"]

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        import json
        # images: 本地路径转换为 /images/ URL 供前端访问
        raw_images = self.images if "images" in dir(self) and self.images else "[]"
        try:
            img_list = json.loads(raw_images) if isinstance(raw_images, str) else raw_images
        except (json.JSONDecodeError, TypeError):
            img_list = []
        api_images = [image_url_for_api(p) for p in img_list]
        return {
            "id": self.id, "source": self.source, "doc_type": self.doc_type,
            "title": self.title, "url": self.url,
            "publish_date": self.publish_date, "is_analyzed": self.is_analyzed,
            "images": api_images,
        }


class CrawlError:
    # retry_count 语义：失败次数（首次失败=1，每次 log 累加 1）
    # dead 阈值：失败 >= 3 次（retry_count >= 3）
    DEAD_THRESHOLD = 3

    @staticmethod
    def log(source: str, url: str | None, error: str, category: str | None = None) -> None:
        """原子 upsert：按 (source, COALESCE(category,''), url) 唯一键记录错误。

        P1-06：改为 ON CONFLICT 原子操作（消除 read-then-write 竞争）。
        retry_count 为"失败次数"：首次失败=1，每次 log 累加 1。
        达 DEAD_THRESHOLD(3) 次转为 dead。已 dead 的 (source, category, url) 不再记录。
        """
        if url and CrawlError.is_dead(source, url, category):
            return  # 死信URL不再处理
        if not url:
            # 无 URL 的错误（如 fetch_list 整体失败）直接插入（允许多条）
            conn = get_conn()
            conn.execute(
                """INSERT INTO crawl_errors (source, url, error, timestamp, retry_count, status, category)
                   VALUES (?, ?, ?, ?, 1, 'pending', ?)""",
                (source, url, error[:500], datetime.now().isoformat(), category),
            )
            conn.commit()
            return

        conn = get_conn()
        now = datetime.now()
        # P1-06：BEGIN IMMEDIATE 获取写锁，保证 read-then-write 原子性（防并发重复行）
        conn.execute("BEGIN IMMEDIATE")
        try:
            # 按 (source, category, url) 查找既有记录（category IS NULL 安全）
            if category is None:
                existing = conn.execute(
                    "SELECT id, retry_count FROM crawl_errors "
                    "WHERE source = ? AND url = ? AND category IS NULL AND status != 'dead'",
                    (source, url),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id, retry_count FROM crawl_errors "
                    "WHERE source = ? AND url = ? AND category = ? AND status != 'dead'",
                    (source, url, category),
                ).fetchone()
            if existing:
                new_count = (existing["retry_count"] or 0) + 1
                new_status = "dead" if new_count >= CrawlError.DEAD_THRESHOLD else "pending"
                # 指数退避：30s, 60s, 120s
                backoff = 30 * (2 ** (new_count - 1))
                next_retry = (now + timedelta(seconds=backoff)).isoformat()
                conn.execute(
                    """UPDATE crawl_errors SET error = ?, timestamp = ?, retry_count = ?,
                       status = ?, next_retry_at = ?, category = ? WHERE id = ?""",
                    (error[:500], now.isoformat(), new_count, new_status, next_retry, category, existing["id"]),
                )
            else:
                backoff = 30  # 首次失败退避
                next_retry = (now + timedelta(seconds=backoff)).isoformat()
                conn.execute(
                    """INSERT INTO crawl_errors (source, url, error, timestamp, retry_count, status, next_retry_at, category)
                       VALUES (?, ?, ?, ?, 1, 'pending', ?, ?)""",
                    (source, url, error[:500], now.isoformat(), next_retry, category),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    @staticmethod
    def list_pending(source: str, category: str | None = None, limit: int = 5) -> list[dict]:
        """获取待重试的错误URL。category=None 时用 IS NULL（兼容遗留全局桶）。"""
        conn = get_conn()
        now = datetime.now().isoformat()
        if category is None:
            rows = conn.execute(
                """SELECT url, retry_count, category FROM crawl_errors
                   WHERE source = ? AND status = 'pending' AND category IS NULL
                   AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   ORDER BY timestamp ASC LIMIT ?""",
                (source, now, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT url, retry_count, category FROM crawl_errors
                   WHERE source = ? AND status = 'pending' AND category = ?
                   AND (next_retry_at IS NULL OR next_retry_at <= ?)
                   ORDER BY timestamp ASC LIMIT ?""",
                (source, category, now, limit),
            ).fetchall()
        return [{"url": r["url"], "retry_count": r["retry_count"], "category": r["category"]} for r in rows]

    @staticmethod
    def mark_retried(source: str, url: str, category: str | None = None) -> None:
        conn = get_conn()
        if category is None:
            conn.execute(
                "UPDATE crawl_errors SET status = 'retried', retried = 1 "
                "WHERE source = ? AND url = ? AND category IS NULL",
                (source, url),
            )
        else:
            conn.execute(
                "UPDATE crawl_errors SET status = 'retried', retried = 1 "
                "WHERE source = ? AND url = ? AND category = ?",
                (source, url, category),
            )
        conn.commit()

    @staticmethod
    def is_dead(source: str, url: str, category: str | None = None) -> bool:
        """检查 (source, category, url) 是否已标记为死信。"""
        conn = get_conn()
        if category is None:
            row = conn.execute(
                "SELECT 1 FROM crawl_errors "
                "WHERE source = ? AND url = ? AND category IS NULL AND status = 'dead' LIMIT 1",
                (source, url),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM crawl_errors "
                "WHERE source = ? AND url = ? AND category = ? AND status = 'dead' LIMIT 1",
                (source, url, category),
            ).fetchone()
        return row is not None


class CrawlRun:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.source = row["source"]
        self.started_at = row["started_at"]
        self.finished_at = row["finished_at"]
        self.status = row["status"]
        self.new_count = row["new_count"]
        self.error_count = row["error_count"]
        self.last_crawled_date = row["last_crawled_date"] if "last_crawled_date" in row.keys() else None
        # category 列由迁移补充，旧库可能不存在该键
        self.category = row["category"] if "category" in row.keys() else None

    @classmethod
    def start(cls, source: str, category: str | None = None) -> "CrawlRun":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO crawl_runs (source, started_at, status, category)
               VALUES (?, ?, 'running', ?)""",
            (source, datetime.now().isoformat(), category),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    def finish(self, *, new_count: int, error_count: int, status: str = "success",
               last_crawled_date: str | None = None):
        # 按 run.id 更新（不接收 category：避免覆盖 start 已记录的栏目）
        conn = get_conn()
        conn.execute(
            """UPDATE crawl_runs SET finished_at = ?, status = ?,
               new_count = ?, error_count = ?, last_crawled_date = ? WHERE id = ?""",
            (datetime.now().isoformat(), status, new_count, error_count,
             last_crawled_date, self.id),
        )
        conn.commit()

    @classmethod
    def get_by_id(cls, run_id: int) -> "CrawlRun":
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM crawl_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def latest_by_source(cls, source: str, category: str | None = None) -> "CrawlRun | None":
        """获取某数据源（可选栏目）最近一次 run。

        category=None 时查 category IS NULL（精确匹配全局桶，用于游标）。
        如需"任意栏目最近一次 run"（用于状态展示），请用 latest_run_for_source。
        """
        conn = get_conn()
        if category is None:
            row = conn.execute(
                """SELECT * FROM crawl_runs WHERE source = ? AND category IS NULL
                   ORDER BY started_at DESC LIMIT 1""",
                (source,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT * FROM crawl_runs WHERE source = ? AND category = ?
                   ORDER BY started_at DESC LIMIT 1""",
                (source, category),
            ).fetchone()
        return cls(row) if row else None

    @classmethod
    def latest_run_for_source(cls, source: str) -> "CrawlRun | None":
        """获取某数据源最近一次 run（任意栏目）。用于状态展示，非游标计算。"""
        conn = get_conn()
        row = conn.execute(
            """SELECT * FROM crawl_runs WHERE source = ?
               ORDER BY started_at DESC LIMIT 1""",
            (source,),
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_last_crawled_date(cls, source: str, category: str | None = None) -> str | None:
        """获取某数据源（可选栏目）上次成功抓取的最新日期，用于增量爬取。

        category=None 时用 IS NULL（兼容旧的全库游标）。
        """
        conn = get_conn()
        if category is None:
            row = conn.execute(
                """SELECT last_crawled_date FROM crawl_runs
                   WHERE source = ? AND category IS NULL
                     AND status = 'success' AND last_crawled_date IS NOT NULL
                   ORDER BY started_at DESC LIMIT 1""",
                (source,),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT last_crawled_date FROM crawl_runs
                   WHERE source = ? AND category = ?
                     AND status = 'success' AND last_crawled_date IS NOT NULL
                   ORDER BY started_at DESC LIMIT 1""",
                (source, category),
            ).fetchone()
        return row["last_crawled_date"] if row else None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "status": self.status, "new_count": self.new_count,
            "error_count": self.error_count,
            "last_crawled_date": self.last_crawled_date,
            "category": self.category,
        }


class Entity:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.name = row["name"]
        self.entity_type = row["entity_type"]
        self.aliases = row["aliases"]
        self.source_doc_ids = row["source_doc_ids"]
        self.metadata = row["metadata"]
        self.created_at = row["created_at"]

    @classmethod
    def create(cls, *, name, entity_type, aliases="[]", source_doc_ids="[]",
               metadata="{}") -> "Entity":
        import json
        conn = get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO entities (name, entity_type, aliases, source_doc_ids, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, entity_type, aliases, source_doc_ids, metadata, datetime.now().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return cls.get_by_name(name)
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def find_or_create(cls, name: str, entity_type: str) -> "Entity":
        """查找或创建实体。

        匹配优先级：
        1. 精确名称匹配（name 字段）
        2. 别名匹配（aliases JSON 数组中包含该名称）
        3. 包含关系模糊匹配（name 包含或被包含，如"雄安集团"vs"中国雄安集团"）
        都不匹配则创建新实体。
        """
        existing = cls.get_by_name(name)
        if existing:
            return existing

        # 别名匹配
        alias_match = cls.get_by_alias(name)
        if alias_match:
            # 把当前名称加入该实体的别名列表
            cls._add_alias(alias_match, name)
            return alias_match

        # 模糊匹配（包含关系）
        fuzzy_match = cls.get_by_fuzzy(name, entity_type)
        if fuzzy_match:
            cls._add_alias(fuzzy_match, name)
            # 重新查询以获取更新后的 aliases
            return cls.get_by_id(fuzzy_match.id)

        return cls.create(name=name, entity_type=entity_type)

    @classmethod
    def get_by_id(cls, eid: int) -> "Entity | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (eid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_by_name(cls, name: str) -> "Entity | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_by_alias(cls, name: str) -> "Entity | None":
        """通过别名精确匹配。"""
        conn = get_conn()
        rows = conn.execute("SELECT * FROM entities WHERE aliases LIKE ?", (f'%"{name}"%',)).fetchall()
        return cls(rows[0]) if rows else None

    @classmethod
    def get_by_fuzzy(cls, name: str, entity_type: str) -> "Entity | None":
        """通过包含关系模糊匹配同一类型的实体。

        规则：
        - 去除常见后缀（集团/公司/委员会/管理局/新区/官网）后比较
        - 一个名称包含另一个（如"雄安集团"在"中国雄安集团"中）
        - 只匹配同类型实体（避免"雄安"人物和"雄安"机构合并）
        - 名称长度 >= 3 才做模糊匹配（避免"新区"等过短词误合并）
        """
        if len(name) < 3:
            return None
        conn = get_conn()
        # 查询同类型的所有实体
        rows = conn.execute(
            "SELECT * FROM entities WHERE entity_type = ? AND name != ?",
            (entity_type, name),
        ).fetchall()
        # 去除常见后缀后的标准化名称
        suffixes = ["集团", "公司", "股份有限公司", "委员会", "管理局", "管理委员",
                     "新区", "官网", "政府", "县人民政府", "县人民政府办公室"]
        def normalize(s):
            for suf in suffixes:
                if s.endswith(suf):
                    s = s[:-len(suf)]
            return s.strip()
        norm_name = normalize(name)
        if len(norm_name) < 2:
            return None
        for row in rows:
            existing_name = row["name"]
            norm_existing = normalize(existing_name)
            if len(norm_existing) < 2:
                continue
            # 包含关系（标准化后）
            if norm_name in norm_existing or norm_existing in norm_name:
                return cls(row)
        return None

    @classmethod
    def _add_alias(cls, entity: "Entity", alias: str) -> None:
        """向实体添加别名（如果尚不存在）。"""
        import json
        conn = get_conn()
        try:
            aliases = json.loads(entity.aliases) if entity.aliases else []
        except (json.JSONDecodeError, TypeError):
            aliases = []
        if alias not in aliases and alias != entity.name:
            aliases.append(alias)
            conn.execute(
                "UPDATE entities SET aliases = ? WHERE id = ?",
                (json.dumps(aliases, ensure_ascii=False), entity.id),
            )
            conn.commit()

    @classmethod
    def add_source_doc(cls, entity_id: int, doc_id: int) -> None:
        """原子追加来源文档ID到 source_doc_ids。"""
        import json
        conn = get_conn()
        row = conn.execute(
            "SELECT source_doc_ids FROM entities WHERE id = ?", (entity_id,)
        ).fetchone()
        if not row:
            return
        try:
            doc_ids = json.loads(row["source_doc_ids"]) if row["source_doc_ids"] else []
        except (json.JSONDecodeError, TypeError):
            doc_ids = []
        if doc_id not in doc_ids:
            doc_ids.append(doc_id)
            conn.execute(
                "UPDATE entities SET source_doc_ids = ? WHERE id = ?",
                (json.dumps(doc_ids, ensure_ascii=False), entity_id),
            )
            conn.commit()

    @classmethod
    def list(cls, entity_type: str | None = None, limit: int = 200) -> list["Entity"]:
        conn = get_conn()
        if entity_type:
            rows = conn.execute(
                "SELECT * FROM entities WHERE entity_type = ? LIMIT ?", (entity_type, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM entities LIMIT ?", (limit,)).fetchall()
        return [cls(r) for r in rows]

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id, "name": self.name, "entity_type": self.entity_type,
            "aliases": json.loads(self.aliases) if self.aliases else [],
        }


class Relation:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.from_entity_id = row["from_entity_id"]
        self.to_entity_id = row["to_entity_id"]
        self.relation_type = row["relation_type"]
        self.source_doc_id = row["source_doc_id"]
        self.confidence = row["confidence"]
        self.publish_date = row["publish_date"]

    @classmethod
    def create(cls, *, from_entity_id, to_entity_id, relation_type,
               source_doc_id=None, confidence=1.0, publish_date=None) -> "Relation":
        """创建关系（upsert：已存在则忽略，不报错）。"""
        conn = get_conn()
        # INSERT OR IGNORE 利用唯一索引 (from_entity_id, to_entity_id, relation_type, source_doc_id)
        conn.execute(
            """INSERT OR IGNORE INTO relations (from_entity_id, to_entity_id, relation_type,
               source_doc_id, confidence, publish_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (from_entity_id, to_entity_id, relation_type, source_doc_id, confidence, publish_date),
        )
        conn.commit()
        # 返回已存在或新创建的记录
        row = conn.execute(
            """SELECT * FROM relations WHERE from_entity_id = ? AND to_entity_id = ?
               AND relation_type = ? AND source_doc_id IS ?""",
            (from_entity_id, to_entity_id, relation_type, source_doc_id),
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_by_id(cls, rid: int) -> "Relation | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM relations WHERE id = ?", (rid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, limit: int = 200) -> list["Relation"]:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM relations LIMIT ?", (limit,)).fetchall()
        return [cls(r) for r in rows]


class Opportunity:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.title = row["title"]
        self.source_doc_id = row["source_doc_id"]
        self.business_line = row["business_line"]
        self.opp_type = row["opp_type"]
        self.fin_scale = row["fin_scale"] if "fin_scale" in row.keys() else None
        self.fin_products = row["fin_products"] if "fin_products" in row.keys() else "[]"
        self.target_client = row["target_client"] if "target_client" in row.keys() else None
        self.buyer_dept = row["buyer_dept"] if "buyer_dept" in row.keys() else None
        self.relocate_from = row["relocate_from"] if "relocate_from" in row.keys() else None
        self.relocate_scale = row["relocate_scale"] if "relocate_scale" in row.keys() else None
        self.relocate_phase = row["relocate_phase"] if "relocate_phase" in row.keys() else None
        self.trigger_event = row["trigger_event"] if "trigger_event" in row.keys() else None
        self.timing_window = row["timing_window"] if "timing_window" in row.keys() else None
        self.insight = row["insight"]
        self.action_suggest = row["action_suggest"]
        self.priority = row["priority"]
        self.status = row["status"]
        self.publish_date = row["publish_date"]
        self.deadline = row["deadline"] if "deadline" in row.keys() else None
        self.extracted_at = row["extracted_at"]

    @classmethod
    def create(cls, *, title, source_doc_id=None, business_line, opp_type,
               fin_scale=None, fin_products="[]", target_client=None, buyer_dept=None,
               relocate_from=None, relocate_scale=None, relocate_phase=None,
               trigger_event=None, timing_window=None, insight=None,
               action_suggest=None, priority="medium", status="signal",
               publish_date=None, deadline=None) -> "Opportunity":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO opportunities
               (title, source_doc_id, business_line, opp_type, fin_scale, fin_products,
                target_client, buyer_dept, relocate_from, relocate_scale, relocate_phase,
                trigger_event, timing_window, insight, action_suggest, priority, status,
                publish_date, deadline, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, source_doc_id, business_line, opp_type, fin_scale, fin_products,
             target_client, buyer_dept, relocate_from, relocate_scale, relocate_phase,
             trigger_event, timing_window, insight, action_suggest, priority, status,
             publish_date, deadline, datetime.now().isoformat()),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, oid: int) -> "Opportunity | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, *, business_line: str | None = None, priority: str | None = None,
             status: str | None = None, limit: int = 50, offset: int = 0) -> list["Opportunity"]:
        conn = get_conn()
        conditions = []
        params = []
        if business_line:
            conditions.append("business_line = ?")
            params.append(business_line)
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM opportunities {where} ORDER BY publish_date DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def count(cls, business_line: str | None = None, priority: str | None = None,
              status: str | None = None) -> int:
        conn = get_conn()
        conditions = []
        params = []
        if business_line:
            conditions.append("business_line = ?")
            params.append(business_line)
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        row = conn.execute(
            f"SELECT COUNT(*) as c FROM opportunities {where}", params
        ).fetchone()
        return row["c"]

    @classmethod
    def list_for_period(cls, *, date_from: str, date_to: str,
                        business_lines: list[str] | None = None) -> list["Opportunity"]:
        """按日期范围查询商机（SQL层过滤，无截断）。"""
        conn = get_conn()
        conditions = ["publish_date >= ?", "publish_date <= ?"]
        params = [date_from, date_to]
        if business_lines:
            placeholders = ",".join("?" * len(business_lines))
            conditions.append(f"business_line IN ({placeholders})")
            params.extend(business_lines)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT * FROM opportunities WHERE {where} ORDER BY publish_date DESC",
            params,
        ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def count_for_period(cls, *, date_from: str, date_to: str,
                         business_lines: list[str] | None = None) -> int:
        conn = get_conn()
        conditions = ["publish_date >= ?", "publish_date <= ?"]
        params = [date_from, date_to]
        if business_lines:
            placeholders = ",".join("?" * len(business_lines))
            conditions.append(f"business_line IN ({placeholders})")
            params.extend(business_lines)
        where = " AND ".join(conditions)
        row = conn.execute(
            f"SELECT COUNT(*) as c FROM opportunities WHERE {where}", params
        ).fetchone()
        return row["c"]

    def to_dict(self) -> dict:
        import json
        # fin_scale 只在有实际金额（含数字）时显示，否则隐藏
        scale = self.fin_scale
        if not scale or scale == "null":
            scale = ""
        elif not any(c.isdigit() for c in scale):
            scale = ""

        def _norm(v):
            """F-29：防御性规范化 "null"/""/空白 → None。"""
            if isinstance(v, str):
                s = v.strip()
                return None if (s == "" or s.lower() == "null") else s
            return v

        return {
            "id": self.id, "title": self.title, "source_doc_id": self.source_doc_id,
            "business_line": self.business_line, "opp_type": self.opp_type,
            "fin_scale": scale,
            "fin_products": json.loads(self.fin_products) if self.fin_products else [],
            "target_client": _norm(self.target_client),
            "buyer_dept": _norm(self.buyer_dept),
            "relocate_from": _norm(self.relocate_from),
            "relocate_scale": _norm(self.relocate_scale),  # F-29：补回遗漏字段
            "relocate_phase": _norm(self.relocate_phase),
            "trigger_event": _norm(self.trigger_event),
            "timing_window": _norm(self.timing_window),
            "insight": self.insight, "action_suggest": self.action_suggest,
            "priority": self.priority, "status": self.status,
            "publish_date": self.publish_date,
            "deadline": _norm(self.deadline),
        }

    def update_banking_fields(self, **fields) -> None:
        """F-29：直接更新商机字段（enrichment 回填专用，不走 create 去重）。

        仅更新传入的非 None 字段，避免覆盖已有值。
        """
        allowed = {
            "buyer_dept", "relocate_from", "relocate_scale", "relocate_phase",
            "timing_window", "deadline", "target_client",
        }
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [self.id]
        conn = get_conn()
        conn.execute(
            f"UPDATE opportunities SET {set_clause} WHERE id = ?", params
        )
        conn.commit()


class LeadershipVisit:
    """leadership_visits 表的数据访问对象（领导调研信息）。"""

    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.source_doc_id = row["source_doc_id"] if "source_doc_id" in row.keys() else None
        self.leader_name = row["leader_name"]
        self.leader_title = row["leader_title"] if "leader_title" in row.keys() else None
        self.visit_date = row["visit_date"] if "visit_date" in row.keys() else None
        self.visit_topic = row["visit_topic"] if "visit_topic" in row.keys() else None
        self.visited_entities = row["visited_entities"] if "visited_entities" in row.keys() else "[]"
        self.summary = row["summary"] if "summary" in row.keys() else None
        self.priority = row["priority"] if "priority" in row.keys() else "medium"
        self.publish_date = row["publish_date"] if "publish_date" in row.keys() else None
        self.images = row["images"] if "images" in row.keys() else "[]"
        self.extracted_at = row["extracted_at"]

    @classmethod
    def create(cls, *, source_doc_id=None, leader_name, leader_title=None,
               visit_date=None, visit_topic=None, visited_entities="[]",
               summary=None, priority="medium", publish_date=None,
               images="[]") -> "LeadershipVisit":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO leadership_visits
               (source_doc_id, leader_name, leader_title, visit_date, visit_topic,
                visited_entities, summary, priority, publish_date, images, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source_doc_id, leader_name, leader_title, visit_date, visit_topic,
             visited_entities, summary, priority, publish_date, images,
             datetime.now().isoformat()),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, vid: int) -> "LeadershipVisit | None":
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM leadership_visits WHERE id = ?", (vid,)
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, *, visit_date_from: str | None = None,
             visit_date_to: str | None = None,
             limit: int = 50, offset: int = 0) -> list["LeadershipVisit"]:
        conn = get_conn()
        conditions = []
        params = []
        if visit_date_from:
            conditions.append("visit_date >= ?")
            params.append(visit_date_from)
        if visit_date_to:
            conditions.append("visit_date <= ?")
            params.append(visit_date_to)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"""SELECT * FROM leadership_visits {where}
                ORDER BY COALESCE(visit_date, publish_date, extracted_at) DESC
                LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def list_for_period(cls, *, visit_date_from: str | None = None,
                        visit_date_to: str | None = None) -> list["LeadershipVisit"]:
        """按日期范围查询领导调研（SQL 层 WHERE，无 limit，不截断）。

        F-12：报告生成用此方法，避免 list(limit=200) 截断大量调研记录。
        """
        conn = get_conn()
        conditions = []
        params = []
        if visit_date_from:
            conditions.append("visit_date >= ?")
            params.append(visit_date_from)
        if visit_date_to:
            conditions.append("visit_date <= ?")
            params.append(visit_date_to)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"""SELECT * FROM leadership_visits {where}
                ORDER BY COALESCE(visit_date, publish_date, extracted_at) DESC""",
            params,
        ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def list_for_publish_period(cls, *, publish_date_from: str,
                                publish_date_to: str) -> list["LeadershipVisit"]:
        """按来源文章发布时间查询领导调研，用于报告的内容时间范围。"""
        conn = get_conn()
        rows = conn.execute(
            """SELECT * FROM leadership_visits
               WHERE publish_date >= ? AND publish_date <= ?
               ORDER BY publish_date DESC""",
            (publish_date_from, publish_date_to),
        ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def count(cls, *, visit_date_from: str | None = None,
              visit_date_to: str | None = None) -> int:
        conn = get_conn()
        conditions = []
        params = []
        if visit_date_from:
            conditions.append("visit_date >= ?")
            params.append(visit_date_from)
        if visit_date_to:
            conditions.append("visit_date <= ?")
            params.append(visit_date_to)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        row = conn.execute(
            f"SELECT COUNT(*) as c FROM leadership_visits {where}", params
        ).fetchone()
        return row["c"]

    def to_dict(self) -> dict:
        import json
        raw_images = json.loads(self.images) if self.images else []
        # F-14：images 转 /images/... API URL（不再泄露本地路径给前端）
        api_images = [image_url_for_api(p) for p in raw_images if p]
        return {
            "id": self.id, "source_doc_id": self.source_doc_id,
            "leader_name": self.leader_name, "leader_title": self.leader_title,
            "visit_date": self.visit_date, "visit_topic": self.visit_topic,
            "visited_entities": json.loads(self.visited_entities) if self.visited_entities else [],
            "summary": self.summary, "priority": self.priority,
            "publish_date": self.publish_date,
            "images": api_images,
            "extracted_at": self.extracted_at,
        }


class AnalysisTaskState:
    """分析子任务状态（实体/商机/领导调研各一条）。"""

    TASK_TYPES = ("entity", "opportunity", "leadership")
    # 必要任务：三个子任务都必须终结（succeeded 或 permanent_error）
    REQUIRED_TYPES = ("entity", "opportunity", "leadership")
    # 熔断阈值：尝试次数达上限后转为 permanent_error，不再自动重试
    MAX_ATTEMPTS = 5

    @staticmethod
    def get_or_create(doc_id: int, task_type: str) -> dict:
        """获取或创建任务状态。

        返回 dict {status, attempt_count, last_error, next_retry_at}。
        """
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM analysis_task_states WHERE doc_id = ? AND task_type = ?",
            (doc_id, task_type),
        ).fetchone()
        if row:
            return {"status": row["status"], "attempt_count": row["attempt_count"],
                    "last_error": row["last_error"], "next_retry_at": row["next_retry_at"]}
        conn.execute(
            "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, updated_at) "
            "VALUES (?, ?, 'pending', 0, ?)",
            (doc_id, task_type, datetime.now().isoformat()),
        )
        conn.commit()
        return {"status": "pending", "attempt_count": 0, "last_error": None,
                "next_retry_at": None}

    @staticmethod
    def mark_succeeded(doc_id: int, task_type: str) -> None:
        """标记成功，清空 last_error 与 next_retry_at。"""
        conn = get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, updated_at) "
            "VALUES (?, ?, 'succeeded', 1, ?) "
            "ON CONFLICT(doc_id, task_type) DO UPDATE SET "
            "status='succeeded', last_error=NULL, next_retry_at=NULL, updated_at=excluded.updated_at",
            (doc_id, task_type, now),
        )
        conn.commit()

    @staticmethod
    def mark_retryable(doc_id: int, task_type: str, error: str) -> None:
        """记录可重试错误。原子熔断：attempt_count 达 MAX_ATTEMPTS 后转 permanent_error。"""
        conn = get_conn()
        now = datetime.now()
        # 先读当前 attempt_count（不存在则视为 0）
        existing = conn.execute(
            "SELECT attempt_count FROM analysis_task_states WHERE doc_id = ? AND task_type = ?",
            (doc_id, task_type),
        ).fetchone()
        current = existing["attempt_count"] if existing else 0
        new_count = current + 1
        # 熔断：达上限转 permanent_error（终态，不再自动重试）
        if new_count >= AnalysisTaskState.MAX_ATTEMPTS:
            final_status = "permanent_error"
            next_retry = None
        else:
            final_status = "retryable_error"
            # 指数退避：30s, 60s, 120s, 240s
            backoff = 30 * (2 ** (new_count - 1))
            next_retry = (now + timedelta(seconds=backoff)).isoformat()
        conn.execute(
            "INSERT INTO analysis_task_states (doc_id, task_type, status, attempt_count, last_error, next_retry_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(doc_id, task_type) DO UPDATE SET "
            "status=excluded.status, attempt_count=excluded.attempt_count, "
            "last_error=excluded.last_error, next_retry_at=excluded.next_retry_at, "
            "updated_at=excluded.updated_at",
            (doc_id, task_type, final_status, new_count, error[:500], next_retry, now.isoformat()),
        )
        conn.commit()

    @staticmethod
    def all_succeeded(doc_id: int) -> bool:
        """检查必要任务（entity+opportunity+leadership）是否全部 succeeded。

        P0-04 修正：permanent_error 不再计入成功集合。permanent_error = 失败，
        文档应进 dead_letter 而非标 is_analyzed=1。若任一必要任务缺失或非 succeeded，
        返回 False。
        """
        conn = get_conn()
        rows = conn.execute(
            "SELECT task_type, status FROM analysis_task_states WHERE doc_id = ?",
            (doc_id,),
        ).fetchall()
        if not rows:
            return False
        succeeded_types = {
            r["task_type"] for r in rows if r["status"] == "succeeded"
        }
        return succeeded_types >= set(AnalysisTaskState.REQUIRED_TYPES)

    @staticmethod
    def has_permanent_failure(doc_id: int) -> bool:
        """检查任一必要任务是否达到 permanent_error（5 次失败熔断）。

        P0-04：permanent_error 视为失败，调用方应标记文档 dead_letter，
        不再自动重试，需人工介入或重置。
        A-08：只检查必要任务类型（entity/opportunity/leadership），非必要辅助任务
        的 permanent_error 不触发 dead_letter。
        """
        conn = get_conn()
        placeholders = ",".join("?" * len(AnalysisTaskState.REQUIRED_TYPES))
        row = conn.execute(
            f"SELECT 1 FROM analysis_task_states WHERE doc_id = ? "
            f"AND status = 'permanent_error' AND task_type IN ({placeholders}) LIMIT 1",
            (doc_id, *AnalysisTaskState.REQUIRED_TYPES),
        ).fetchone()
        return row is not None

    @staticmethod
    def list_retryable(limit: int = 50) -> list[dict]:
        """列出已到期、可重试的子任务（排除 permanent_error 和未到期）。

        返回 [{doc_id, task_type, attempt_count}]，按 next_retry_at 升序。
        """
        conn = get_conn()
        now = datetime.now().isoformat()
        rows = conn.execute(
            """SELECT doc_id, task_type, attempt_count FROM analysis_task_states
               WHERE status = 'retryable_error'
                 AND (next_retry_at IS NULL OR next_retry_at <= ?)
               ORDER BY COALESCE(next_retry_at, '9999') ASC LIMIT ?""",
            (now, limit),
        ).fetchall()
        return [{"doc_id": r["doc_id"], "task_type": r["task_type"],
                 "attempt_count": r["attempt_count"]} for r in rows]


class LLMLog:
    @staticmethod
    def log(*, doc_id=None, task_type, model, prompt, response,
            prompt_tokens=0, completion_tokens=0, duration_ms=0):
        conn = get_conn()
        conn.execute(
            """INSERT INTO raw_llm_logs
               (doc_id, task_type, model, prompt, response, prompt_tokens,
                completion_tokens, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, task_type, model, prompt, response, prompt_tokens,
             completion_tokens, duration_ms, datetime.now().isoformat()),
        )
        conn.commit()


class Report:
    """reports 表的数据访问对象。"""

    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.report_type = row["report_type"]
        self.period_start = row["period_start"]
        self.period_end = row["period_end"]
        self.content = row["content"]
        self.opportunity_ids = row["opportunity_ids"]
        self.docx_path = row["docx_path"] if "docx_path" in row.keys() else None
        self.pdf_path = row["pdf_path"] if "pdf_path" in row.keys() else None
        self.generated_at = row["generated_at"]

    @classmethod
    def create(cls, *, report_type, period_start, period_end,
               content="{}", opportunity_ids="[]") -> "Report":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO reports (report_type, period_start, period_end, content,
               opportunity_ids, generated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_type, period_start, period_end, content, opportunity_ids,
             datetime.now().isoformat()),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, rid: int) -> "Report | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, limit: int = 20) -> list["Report"]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY generated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [cls(r) for r in rows]

    @staticmethod
    def count() -> int:
        """F-21：报告总数（用于分页 total，非页长度）。"""
        conn = get_conn()
        return conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0]

    def update_files(self, *, docx_path: str | None = None, pdf_path: str | None = None):
        conn = get_conn()
        conn.execute(
            "UPDATE reports SET docx_path = ?, pdf_path = ? WHERE id = ?",
            (docx_path, pdf_path, self.id),
        )
        conn.commit()
        self.docx_path = docx_path
        self.pdf_path = pdf_path

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id, "report_type": self.report_type,
            "period_start": self.period_start, "period_end": self.period_end,
            "content": json.loads(self.content) if self.content else {},
            "opportunity_ids": json.loads(self.opportunity_ids) if self.opportunity_ids else [],
            "docx_path": self.docx_path, "pdf_path": self.pdf_path,
            "generated_at": self.generated_at,
        }


class PushSubscription:
    """push_subscriptions 表的数据访问对象（Web Push 订阅信息）。"""

    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.user_id = row["user_id"]
        self.channel = row["channel"]
        self.endpoint = row["endpoint"]
        self.keys = row["keys"]
        self.created_at = row["created_at"]

    @classmethod
    def create(cls, *, user_id="default", channel, endpoint, keys="{}") -> "PushSubscription":
        """F-20：upsert（按 user_id+endpoint 唯一），重复订阅不创建新行。"""
        import json
        conn = get_conn()
        if isinstance(keys, dict):
            keys = json.dumps(keys)
        conn.execute(
            """INSERT INTO push_subscriptions (user_id, channel, endpoint, keys, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, endpoint) DO UPDATE SET
                 channel = excluded.channel, keys = excluded.keys""",
            (user_id, channel, endpoint, keys, datetime.now().isoformat()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user_id, endpoint),
        ).fetchone()
        return cls(row)

    @classmethod
    def delete_by_endpoint(cls, endpoint: str, user_id="default") -> bool:
        """F-20：退订（按 endpoint 删除订阅）。返回是否删除了行。"""
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?",
            (user_id, endpoint),
        )
        conn.commit()
        return cur.rowcount > 0

    @classmethod
    def list_by_user(cls, user_id="default") -> list["PushSubscription"]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [cls(r) for r in rows]


class PushSettings:
    """push_settings 表的数据访问对象（用户推送偏好 + 防打扰判断逻辑）。"""

    PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, row: sqlite3.Row):
        self.user_id = row["user_id"]
        self.instant_enabled = bool(row["instant_enabled"])
        self.instant_threshold = row["instant_threshold"]
        self.daily_limit = row["daily_limit"]
        self.focus_lines = row["focus_lines"]
        self.daily_digest_enabled = bool(row["daily_digest_enabled"])
        self.daily_digest_time = row["daily_digest_time"]
        self.weekly_digest_enabled = bool(row["weekly_digest_enabled"])
        self.digest_threshold = row["digest_threshold"]
        self.dnd_enabled = bool(row["dnd_enabled"])
        self.dnd_start = row["dnd_start"]
        self.dnd_end = row["dnd_end"]

    @classmethod
    def get_or_create(cls, user_id="default") -> "PushSettings":
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM push_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO push_settings (user_id) VALUES (?)", (user_id,)
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM push_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
        return cls(row)

    def update(self, **kwargs):
        conn = get_conn()
        for key, value in kwargs.items():
            if isinstance(value, bool):
                value = 1 if value else 0
            conn.execute(
                f"UPDATE push_settings SET {key} = ? WHERE user_id = ?",
                (value, self.user_id),
            )
        conn.commit()

    def should_send_instant(self, priority: str) -> bool:
        """判断某优先级是否达到即时推送阈值。

        数值越小优先级越高；priority 的序号 <= threshold 的序号才推送。
        例如 threshold=high(1)，则 critical(0)/high(1) 推送，medium(2) 不推送。
        """
        if not self.instant_enabled:
            return False
        return (self.PRIORITY_ORDER.get(priority, 3)
                <= self.PRIORITY_ORDER.get(self.instant_threshold, 1))

    def is_dnd_now(self, now_time: str = None) -> bool:
        """判断当前是否在免打扰时段。支持跨午夜窗口（如 22:00-07:00）。"""
        if not self.dnd_enabled:
            return False
        t = now_time or datetime.now().strftime("%H:%M")
        start, end = self.dnd_start, self.dnd_end
        if start <= end:
            # 同一天窗口，如 09:00-12:00
            return start <= t < end
        else:
            # 跨午夜窗口，如 22:00-07:00
            return t >= start or t < end

    def to_dict(self) -> dict:
        import json
        return {
            "instant_enabled": self.instant_enabled,
            "instant_threshold": self.instant_threshold,
            "daily_limit": self.daily_limit,
            "focus_lines": json.loads(self.focus_lines) if self.focus_lines else [],
            "daily_digest_enabled": self.daily_digest_enabled,
            "daily_digest_time": self.daily_digest_time,
            "weekly_digest_enabled": self.weekly_digest_enabled,
            "digest_threshold": self.digest_threshold,
            "dnd_enabled": self.dnd_enabled,
            "dnd_start": self.dnd_start,
            "dnd_end": self.dnd_end,
        }


class PushLog:
    """push_logs 表的数据访问对象（推送记录 + 去重/计数）。"""

    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.user_id = row["user_id"]
        self.opportunity_id = row["opportunity_id"] if "opportunity_id" in row.keys() else None
        self.trigger_type = row["trigger_type"]
        self.channel = row["channel"]
        self.title = row["title"]
        self.body = row["body"]
        self.sent_at = row["sent_at"]
        self.delivered = bool(row["delivered"])
        self.clicked = bool(row["clicked"])

    @classmethod
    def create(cls, *, user_id="default", opportunity_id=None, trigger_type,
               channel, title, body, delivered=False) -> "PushLog":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO push_logs (user_id, opportunity_id, trigger_type, channel,
               title, body, sent_at, delivered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, opportunity_id, trigger_type, channel, title, body,
             datetime.now().isoformat(), 1 if delivered else 0),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, lid: int) -> "PushLog | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM push_logs WHERE id = ?", (lid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def count_today(cls, user_id="default", trigger_type=None) -> int:
        """统计今日推送数。

        M-05：只统计 delivered=1（成功送达），失败推送不计入每日上限。
        """
        conn = get_conn()
        today = datetime.now().strftime("%Y-%m-%d")
        if trigger_type:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM push_logs WHERE user_id = ? AND trigger_type = ? "
                "AND sent_at LIKE ? AND delivered = 1",
                (user_id, trigger_type, f"{today}%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM push_logs WHERE user_id = ? "
                "AND sent_at LIKE ? AND delivered = 1",
                (user_id, f"{today}%"),
            ).fetchone()
        return row["c"]

    @classmethod
    def already_sent(cls, user_id="default", opportunity_id=None) -> bool:
        """检查某商机是否已成功推送过（去重）。

        F-06：只认 delivered=1 的记录（失败推送不阻断补发）。
        """
        if not opportunity_id:
            return False
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM push_logs WHERE user_id = ? AND opportunity_id = ? "
            "AND delivered = 1 LIMIT 1",
            (user_id, opportunity_id),
        ).fetchone()
        return row is not None
