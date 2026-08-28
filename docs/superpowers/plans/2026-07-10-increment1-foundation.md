# 增量 1：项目骨架 + 存储层 + 雄安官网爬虫 + 信息源状态页

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建项目骨架，实现 SQLite 存储层和雄安官网爬虫，提供完整的 Web 界面展示已抓取的文档列表和信息源状态——前后端端到端打通。

**Architecture:** Python FastAPI 后端 + Vue 3 前端（单仓 monorepo）。爬虫通过隐藏的 JSON datasource API 获取文章列表（无需 JS 渲染），再用 requests + BeautifulSoup 抓取详情页正文。SQLite 存储文档与抓取状态。前端通过 REST API 展示信息源状态和文档列表。

**Tech Stack:** Python 3.11+, FastAPI, SQLite (aiosqlite/peewee), requests, BeautifulSoup4, pytest; Vue 3 + Vite + Element Plus + Pinia + axios。

---

## 已确认的目标站点结构（来自实际探测）

雄安官网 `xiongan.gov.cn` 是服务端渲染静态 HTML，无需 Playwright。

**列表数据源 API（关键发现）**：每个栏目页的 `<ul>` 上有 `data="datasource:XXXX"`（32位hex），对应的 JSON 文件返回完整列表（最多1000条），URL 规则：
```
https://www.xiongan.gov.cn/{栏目目录}/ds_{DATASOURCE_ID}.json
```
已验证的：
- 最新要闻 `/xaxw/zxyw.html` → `/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json`（1000条）
- 政策文件 `/zcwj.html` → `/ds_381eecba9aa042aeaf418a63c376698d.json`（54条）

**JSON 结构**：
```json
{
  "datasource": [
    {
      "title": "标题",
      "publishUrl": "../20260710/9a3db06118ce43158329cc4c83594a8c/c.html",
      "publishTime": "2026-07-10 09:14:40",
      "sourceText": "雄安发布",
      "summary": "摘要...",
      "keywords": "关键词1,关键词2",
      "contentType": "MultiMedia",
      "contentId": "202607109a3db06118ce43158329cc4c83594a8c"
    }
  ]
}
```

**详情页选择器（已验证）**：
- 标题：`h1.title`
- 正文：`#detailContent`（join 所有 `<p>` 文本）
- 来源：`<meta name="source" content="...">` 或 `#source`
- 发布日期：`<meta name="publishdate" content="2026-07-10">`（完整时间用 JSON 的 publishTime）
- 正文图片：`#detailContent img`，src 是相对路径

**robots.txt**：不存在（404）。需礼貌限速。

**URL 解析**：`publishUrl` 是相对路径（`../20260710/.../c.html`），用 `urllib.parse.urljoin("https://www.xiongan.gov.cn", publishUrl)` 解析。`contentType == "Link"` 的条目是外链跳转，过滤掉。

---

## 文件结构（本增量创建）

```
xa_info_collector/
├── pyproject.toml                    # Python 项目配置
├── config/
│   └── sources.yaml                  # 数据源配置
├── storage/
│   ├── __init__.py
│   ├── database.py                   # SQLite 连接管理
│   └── models.py                     # 表定义 + 迁移
├── collector/
│   ├── __init__.py
│   ├── base.py                       # BaseAdapter
│   ├── deduper.py                    # content_hash 去重
│   └── adapters/
│       ├── __init__.py
│       └── xiongan_portal.py         # 雄安官网 adapter
├── web/
│   ├── __init__.py
│   ├── app.py                        # FastAPI 主应用
│   └── api/
│       ├── __init__.py
│       ├── documents.py              # 文档列表 API
│       └── collect.py                # 抓取触发/状态 API
├── web/frontend/                     # Vue 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── api/client.ts
│       ├── stores/collector.ts
│       └── views/SourceStatus.vue    # 信息源状态页
├── data/
│   └── snapshots/                    # 原始 HTML 快照（.gitkeep）
├── tests/
│   ├── conftest.py
│   ├── storage/
│   │   ├── test_models.py
│   │   └── test_database.py
│   ├── collector/
│   │   ├── test_deduper.py
│   │   └── test_xiongan_portal.py
│   ├── web/
│   │   └── test_api.py
│   └── e2e/
│       └── test_collect_e2e.py       # 端到端测试
└── docs/
    └── impl/
        └── increment1-foundation.md  # 本增量实施文档
```

---

## Task 1: Python 项目骨架

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`（补充 Python 相关）
- Create: 各模块 `__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "xa-info-collector"
version = "0.1.0"
description = "雄安信息商机挖掘系统"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "requests>=2.32.0",
    "beautifulsoup4>=4.12.0",
    "pyyaml>=6.0",
    "python-docx>=1.1.0",
    "zhipuai>=2.1.0",
    "apscheduler>=3.10.0",
    "pywebpush>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "httpx>=0.27.0",
    "respx>=0.21.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: 创建 Python 包结构**

创建所有 `__init__.py` 空文件：`storage/__init__.py`、`collector/__init__.py`、`collector/adapters/__init__.py`、`web/__init__.py`、`web/api/__init__.py`。

创建 `data/snapshots/.gitkeep`。

- [ ] **Step 3: 补充 .gitignore**

确保 `.gitignore` 已包含（之前 git init 时已创建，检查并补充）：
```
__pycache__/
*.pyc
.venv/
data/xac.db
data/snapshots/*
!data/snapshots/.gitkeep
node_modules/
dist/
```

- [ ] **Step 4: 验证环境**

Run: `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: 安装成功，无报错。

Run: `python -c "import fastapi, bs4, requests, yaml; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore storage/ collector/ web/ data/
git commit -m "chore: Python 项目骨架与依赖配置"
```

---

## Task 2: 存储层 — 数据模型与建表

**Files:**
- Create: `storage/models.py`
- Create: `storage/database.py`
- Test: `tests/storage/test_models.py`

- [ ] **Step 1: 写失败测试 — documents 表 CRUD**

```python
# tests/storage/test_models.py
import pytest
from storage.models import Document, init_db
from storage.database import get_db, close_db

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    yield
    close_db()

def test_create_and_get_document(db):
    doc = Document.create(
        source="xiongan_portal",
        doc_type="新闻",
        title="测试标题",
        url="https://www.xiongan.gov.cn/test.html",
        publish_date="2026-07-10",
        raw_html="<p>raw</p>",
        text="测试正文",
        content_hash="abc123",
    )
    assert doc.id is not None
    fetched = Document.get_by_id(doc.id)
    assert fetched.title == "测试标题"
    assert fetched.source == "xiongan_portal"

def test_duplicate_content_hash_raises(db):
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="A",
        url="https://example.com/a", publish_date="2026-07-10",
        raw_html="", text="same", content_hash="dup",
    )
    from storage.models import IntegrityError
    with pytest.raises(IntegrityError):
        Document.create(
            source="xiongan_portal", doc_type="新闻", title="B",
            url="https://example.com/b", publish_date="2026-07-10",
            raw_html="", text="same", content_hash="dup",
        )
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/storage/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'storage.models'`

- [ ] **Step 3: 实现 storage/database.py**

```python
# storage/database.py
import sqlite3
from pathlib import Path

_DB_PATH: str | None = None
_conn: sqlite3.Connection | None = None


def init_db(db_path: str = "data/xac.db") -> None:
    """初始化数据库连接，data 目录自动创建。"""
    global _DB_PATH, _conn
    _DB_PATH = db_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(db_path)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")


def get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _conn


def close_db() -> None:
    global _conn
    if _conn:
        _conn.close()
        _conn = None
```

- [ ] **Step 4: 实现 storage/models.py**

```python
# storage/models.py
import sqlite3
import hashlib
from datetime import datetime
from storage.database import get_conn

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
    is_analyzed INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash);

CREATE TABLE IF NOT EXISTS crawl_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    url TEXT,
    error TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    retried INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    new_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_crawled_date TEXT  -- 上次成功抓取到的最新日期，增量爬取基准
);
"""


def init_db(db_path: str = "data/xac.db") -> None:
    from storage.database import init_db as _init
    _init(db_path)
    conn = get_conn()
    conn.executescript(SCHEMA_SQL)
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

    @classmethod
    def create(cls, *, source, doc_type, title, url, publish_date,
               raw_html, text, content_hash) -> "Document":
        conn = get_conn()
        crawled_at = datetime.now().isoformat()
        try:
            cur = conn.execute(
                """INSERT INTO documents
                   (source, doc_type, title, url, publish_date, crawled_at,
                    raw_html, text, content_hash, is_analyzed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (source, doc_type, title, url, publish_date, crawled_at,
                 raw_html, text, content_hash, ),
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
        return {
            "id": self.id, "source": self.source, "doc_type": self.doc_type,
            "title": self.title, "url": self.url,
            "publish_date": self.publish_date, "is_analyzed": self.is_analyzed,
        }


class CrawlError:
    @staticmethod
    def log(source: str, url: str | None, error: str) -> None:
        conn = get_conn()
        conn.execute(
            """INSERT INTO crawl_errors (source, url, error, timestamp)
               VALUES (?, ?, ?, ?)""",
            (source, url, error, datetime.now().isoformat()),
        )
        conn.commit()


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

    @classmethod
    def start(cls, source: str) -> "CrawlRun":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO crawl_runs (source, started_at, status)
               VALUES (?, ?, 'running')""",
            (source, datetime.now().isoformat()),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    def finish(self, *, new_count: int, error_count: int, status: str = "success",
               last_crawled_date: str | None = None):
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
    def latest_by_source(cls, source: str) -> "CrawlRun | None":
        conn = get_conn()
        row = conn.execute(
            """SELECT * FROM crawl_runs WHERE source = ?
               ORDER BY started_at DESC LIMIT 1""",
            (source,),
        ).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_last_crawled_date(cls, source: str) -> str | None:
        """获取某数据源上次成功抓取的最新日期，用于增量爬取。"""
        conn = get_conn()
        row = conn.execute(
            """SELECT last_crawled_date FROM crawl_runs
               WHERE source = ? AND status = 'success' AND last_crawled_date IS NOT NULL
               ORDER BY started_at DESC LIMIT 1""",
            (source,),
        ).fetchone()
        return row["last_crawled_date"] if row else None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "source": self.source,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "status": self.status, "new_count": self.new_count,
            "error_count": self.error_count,
            "last_crawled_date": self.last_crawled_date,
        }
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/storage/test_models.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add storage/ tests/storage/
git commit -m "feat: 存储层 — documents/crawl_errors/crawl_runs 表与数据访问"
```

---

## Task 3: 去重模块

**Files:**
- Create: `collector/deduper.py`
- Test: `tests/collector/test_deduper.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/collector/test_deduper.py
from collector.deduper import is_duplicate, content_hash

def test_content_hash_stable():
    assert content_hash("hello") == content_hash("hello")

def test_content_hash_different():
    assert content_hash("hello") != content_hash("world")

def test_is_duplicate_true(tmp_path, monkeypatch):
    from storage.models import init_db, Document, close_db
    init_db(str(tmp_path / "t.db"))
    Document.create(
        source="x", doc_type="新闻", title="t", url="http://a",
        publish_date="2026-07-10", raw_html="", text="abc",
        content_hash=content_hash("abc"),
    )
    assert is_duplicate("abc") is True
    close_db()

def test_is_duplicate_false(tmp_path):
    from storage.models import init_db, close_db
    init_db(str(tmp_path / "t.db"))
    assert is_duplicate("xyz") is False
    close_db()
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/collector/test_deduper.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 deduper.py**

```python
# collector/deduper.py
from storage.models import Document

def content_hash(text: str) -> str:
    return Document.compute_hash(text)

def is_duplicate(text: str) -> bool:
    h = content_hash(text)
    from storage.database import get_conn
    row = get_conn().execute(
        "SELECT 1 FROM documents WHERE content_hash = ? LIMIT 1", (h,)
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/collector/test_deduper.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add collector/deduper.py tests/collector/test_deduper.py
git commit -m "feat: 爬虫去重模块 — content_hash 校验"
```

---

## Task 4: 数据源配置

**Files:**
- Create: `config/sources.yaml`
- Create: `collector/config.py`

- [ ] **Step 1: 创建 sources.yaml**

```yaml
# config/sources.yaml
# 每个数据源的配置。新增数据源只改这里。
sources:
  xiongan_portal:
    name: "中国雄安官网"
    base_url: "https://www.xiongan.gov.cn"
    # 栏目配置：每个栏目有列表页URL和 datasource JSON 路径
    categories:
      zxyw:
        name: "最新要闻"
        list_url: "/xaxw/zxyw.html"
        datasource_path: "/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
      zcwj:
        name: "政策文件"
        list_url: "/zcwj.html"
        datasource_path: "/ds_381eecba9aa042aeaf418a63c376698d.json"
      tzgg:
        name: "通知公告"
        list_url: "/tzgg.html"
        datasource_path: null  # 探测时未拿到，运行时动态发现
    enabled: true
    qps: 2  # 每秒最多2个请求，礼貌限速

  # 以下数据源在后续增量实现
  public_resource:
    name: "公共资源交易平台"
    enabled: false
    qps: 1
  xiongan_group:
    name: "雄安集团采购"
    enabled: false
    qps: 1
  county_provincial:
    name: "县区+省级"
    enabled: false
    qps: 1
```

- [ ] **Step 2: 创建 config 加载器**

```python
# collector/config.py
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"

def load_sources_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("sources", {})

def get_source_config(source_name: str) -> dict:
    sources = load_sources_config()
    if source_name not in sources:
        raise KeyError(f"Unknown source: {source_name}")
    return sources[source_name]
```

- [ ] **Step 3: 写测试**

```python
# tests/collector/test_config.py
from collector.config import load_sources_config, get_source_config

def test_load_sources_has_portal():
    sources = load_sources_config()
    assert "xiongan_portal" in sources
    assert sources["xiongan_portal"]["name"] == "中国雄安官网"

def test_portal_has_categories():
    cfg = get_source_config("xiongan_portal")
    assert "zxyw" in cfg["categories"]
    assert cfg["categories"]["zxyw"]["datasource_path"] is not None

def test_unknown_source_raises():
    import pytest
    with pytest.raises(KeyError):
        get_source_config("nonexistent")
```

- [ ] **Step 4: 运行验证**

Run: `pytest tests/collector/test_config.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add config/sources.yaml collector/config.py tests/collector/test_config.py
git commit -m "feat: 数据源配置与加载器"
```

---

## Task 5: BaseAdapter 抽象基类

**Files:**
- Create: `collector/base.py`

- [ ] **Step 1: 实现 BaseAdapter**

```python
# collector/base.py
"""BaseAdapter — 爬虫抽象基类。

并发安全策略（重要）：
1. 严格单线程顺序抓取，禁止任何 async/concurrent/线程池并发请求。
2. 通过 _throttle() 强制每次请求间隔 ≥ 1/qps 秒（默认 qps=2，即每0.5秒最多1个请求）。
3. 增量抓取：run() 自动读取上次成功抓取日期，只获取新增内容，不全量扫描。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import time

from collector.config import get_source_config
from collector.deduper import content_hash, is_duplicate
from storage.models import Document, CrawlError, CrawlRun


@dataclass
class ListItem:
    title: str
    url: str          # 绝对 URL
    publish_date: str  # YYYY-MM-DD
    summary: str = ""
    extra: dict = None  # 栏目特定信息


@dataclass
class RawDoc:
    title: str
    url: str
    publish_date: str
    raw_html: str
    text: str
    source_text: str = ""
    summary: str = ""


class BaseAdapter(ABC):
    source_name: str = ""

    def __init__(self):
        self.config = get_source_config(self.source_name)
        # 限速：每秒最多 qps 个请求（默认2，即0.5秒间隔）
        self._min_interval = 1.0 / max(self.config.get("qps", 2), 0.1)
        self._last_request = 0.0

    def _throttle(self):
        """强制请求间隔，保护目标服务器。每次 HTTP 请求前必须调用。"""
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    @abstractmethod
    def fetch_list(self, since: str | None = None) -> list[ListItem]:
        """抓取列表，返回 since(YYYY-MM-DD) 之后的新条目。"""

    @abstractmethod
    def fetch_detail(self, url: str) -> RawDoc:
        """抓取详情页正文。每次请求前框架已自动限速。"""

    def run(self, since: str | None = None) -> dict:
        """完整抓取流程：列表 → 详情 → 去重 → 入库。返回统计。

        增量爬取：若 since 未指定，自动从 crawl_runs 读取上次成功抓取的
        last_crawled_date，只获取该日期之后的新内容。首次运行 since=None
        表示全量，但 fetch_list 应自行控制只取最近的（如最新100条）。
        """
        # 增量：未指定 since 时，读取上次抓取日期
        if since is None:
            since = CrawlRun.get_last_crawled_date(self.source_name)

        run = CrawlRun.start(self.source_name)
        new_count = 0
        error_count = 0
        latest_date = since or ""

        try:
            items = self.fetch_list(since=since)
            for item in items:
                try:
                    raw = self.fetch_detail(item.url)
                    if is_duplicate(raw.text):
                        continue
                    Document.create(
                        source=self.source_name,
                        doc_type="新闻",
                        title=raw.title,
                        url=raw.url,
                        publish_date=raw.publish_date,
                        raw_html=raw.raw_html,
                        text=raw.text,
                        content_hash=content_hash(raw.text),
                    )
                    self.save_snapshot(raw)
                    new_count += 1
                    # 跟踪本次抓取到的最新日期
                    if raw.publish_date > latest_date:
                        latest_date = raw.publish_date
                except Exception as e:
                    CrawlError.log(self.source_name, item.url, str(e))
                    error_count += 1
            run.finish(
                new_count=new_count, error_count=error_count,
                status="success",
                last_crawled_date=latest_date or None,
            )
        except Exception as e:
            run.finish(new_count=new_count, error_count=error_count, status="failed")
            CrawlError.log(self.source_name, None, f"fetch_list failed: {e}")
            raise

        return {"new": new_count, "errors": error_count, "run_id": run.id,
                "since": since, "latest_date": latest_date}

    def save_snapshot(self, raw: RawDoc):
        """保存原始 HTML 快照。"""
        from pathlib import Path
        snapshot_dir = Path("data/snapshots") / self.source_name
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        safe_name = raw.url.replace("https://", "").replace("/", "_").replace(":", "")
        (snapshot_dir / f"{safe_name}.html").write_text(raw.raw_html, encoding="utf-8")
```

- [ ] **Step 2: Commit（无独立测试，集成测试在 Task 7）**

```bash
git add collector/base.py
git commit -m "feat: BaseAdapter 抽象基类 — 抓取流程编排框架"
```

---

## Task 6: 雄安官网 Adapter

**Files:**
- Create: `collector/adapters/xiongan_portal.py`
- Test: `tests/collector/test_xiongan_portal.py`

- [ ] **Step 1: 准备测试 fixtures（离线 HTML 样本）**

```python
# tests/collector/fixtures.py
# 模拟 datasource JSON 响应
SAMPLE_DATASOURCE_JSON = {
    "publishDomain": "https://www.xiongan.gov.cn",
    "isAbsolutePath": 0,
    "datasource": [
        {
            "title": "张国华调研重点项目",
            "publishUrl": "../20260710/abc123/c.html",
            "publishTime": "2026-07-10 09:14:40",
            "sourceText": "雄安发布",
            "summary": "推进重点项目建设",
            "keywords": "调研,项目",
            "contentType": "MultiMedia",
            "contentId": "20260710abc123",
        },
        {
            "title": "外链跳转文章",
            "publishUrl": "https://news.cn/some/external",
            "publishTime": "2026-07-09 10:00:00",
            "sourceText": "新华网",
            "summary": "",
            "contentType": "Link",
            "contentId": "external001",
        },
    ],
}

# 模拟详情页 HTML
SAMPLE_DETAIL_HTML = """
<html><head>
<meta name="source" content="雄安发布">
<meta name="publishdate" content="2026-07-10">
</head><body>
<div id="detail" class="detail">
  <h1 class="title">张国华调研重点项目</h1>
  <div id="detailContent" class="detail-content">
    <p>&emsp;&emsp;7月10日，张国华深入启动区调研重点项目建设工作。</p>
    <p>&emsp;&emsp;调研组先后实地察看了多个项目现场。</p>
  </div>
  <div class="author">责任编辑： 张三</div>
</div>
</body></html>
"""
```

- [ ] **Step 2: 写失败测试 — fetch_list**

```python
# tests/collector/test_xiongan_portal.py
import json
import pytest
import respx
import httpx
from unittest.mock import patch
from tests.collector.fixtures import SAMPLE_DATASOURCE_JSON, SAMPLE_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_fetch_list_parses_json_and_filters_links():
    """fetch_list 应解析 JSON、过滤 Link 类型、解析绝对 URL。"""
    respx.get("https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json").respond(
        json=SAMPLE_DATASOURCE_JSON
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    items = adapter.fetch_list(category="zxyw")

    # Link 类型被过滤，只剩1条
    assert len(items) == 1
    assert items[0].title == "张国华调研重点项目"
    # 相对路径 ../20260710/abc123/c.html 解析为绝对 URL
    assert items[0].url == "https://www.xiongan.gov.cn/20260710/abc123/c.html"
    assert items[0].publish_date == "2026-07-10"
    assert items[0].summary == "推进重点项目建设"


@respx.mock
def test_fetch_list_since_filters_old_items():
    """since 参数应过滤掉旧条目（遇到更早日期即停止遍历）。"""
    respx.get("https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json").respond(
        json=SAMPLE_DATASOURCE_JSON
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    # since 2026-07-10：第一条(07-10)符合，第二条是Link被过滤
    items = adapter.fetch_list(category="zxyw", since="2026-07-10")
    assert len(items) == 1
    # since 2026-07-11：当天没有更新
    items = adapter.fetch_list(category="zxyw", since="2026-07-11")
    assert len(items) == 0


@respx.mock
def test_fetch_list_initial_batch_limit():
    """首次全量（since=None）时应限制批量大小，不全量扫描。"""
    # 构造120条数据测试限制
    big_data = {
        "publishDomain": "https://www.xiongan.gov.cn",
        "isAbsolutePath": 0,
        "datasource": [
            {
                "title": f"文章{i}",
                "publishUrl": f"../2026070{i % 10}/id{i}/c.html",
                "publishTime": f"2026-07-{10 - (i // 20):02d} 09:00:00",
                "contentType": "MultiMedia",
                "contentId": f"id{i}",
            }
            for i in range(120)
        ],
    }
    respx.get("https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json").respond(
        json=big_data
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    items = adapter.fetch_list(category="zxyw", since=None)
    # 首次全量限制为 INITIAL_BATCH=50
    assert len(items) == 50
```

- [ ] **Step 3: 运行验证失败**

Run: `pytest tests/collector/test_xiongan_portal.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 实现 XionganPortalAdapter — fetch_list**

```python
# collector/adapters/xiongan_portal.py
import json
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc


class XionganPortalAdapter(BaseAdapter):
    source_name = "xiongan_portal"
    BASE = "https://www.xiongan.gov.cn"

    def __init__(self):
        super().__init__()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/125.0.0.0 Safari/537.36",
        })

    def _get(self, url: str) -> requests.Response:
        self._throttle()
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp

    def fetch_list(self, since: str | None = None, category: str = "zxyw") -> list[ListItem]:
        """通过 datasource JSON API 获取列表。

        增量策略：
        - since 指定时，只返回 since 日期之后的条目（JSON 已按日期降序，遇到更早的即停止）
        - since 为 None（首次全量）时，限制最多返回 INITIAL_BATCH（50）条，
          避免一次性抓取1000篇详情页对服务器造成压力。后续运行靠增量补充。
        """
        INITIAL_BATCH = 50  # 首次全量时最多抓取的条目数

        cat_cfg = self.config["categories"].get(category)
        if not cat_cfg or not cat_cfg.get("datasource_path"):
            raise ValueError(f"No datasource_path for category {category}")

        json_url = self.BASE + cat_cfg["datasource_path"]
        resp = self._get(json_url)
        data = resp.json()

        publish_domain = data.get("publishDomain", self.BASE)
        is_absolute = data.get("isAbsolutePath", 0)
        items = []
        for entry in data.get("datasource", []):
            # 过滤外链跳转
            if entry.get("contentType") == "Link":
                continue
            # 解析 URL
            raw_url = entry.get("publishUrl", "")
            if is_absolute:
                url = raw_url
            else:
                # publishUrl 是相对 ../20260710/... 需要基于栏目目录解析
                url = urljoin(self.BASE + cat_cfg["list_url"], raw_url)

            publish_time = entry.get("publishTime", "")
            publish_date = publish_time[:10] if publish_time else ""

            # 增量过滤：since 之后的才要
            if since and publish_date < since:
                # JSON 按日期降序，遇到更早的可以直接停止遍历
                break

            items.append(ListItem(
                title=entry.get("title", ""),
                url=url,
                publish_date=publish_date,
                summary=entry.get("summary", ""),
                extra={
                    "keywords": entry.get("keywords", ""),
                    "source_text": entry.get("sourceText", ""),
                    "content_id": entry.get("contentId", ""),
                },
            ))

        # 首次全量时限制批量大小
        if since is None:
            items = items[:INITIAL_BATCH]

        return items

    def fetch_detail(self, url: str) -> RawDoc:
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.select_one("h1.title")
        title = title_el.get_text(strip=True) if title_el else ""

        content_el = soup.select_one("#detailContent")
        if content_el:
            paragraphs = content_el.find_all("p")
            text = "\n".join(
                p.get_text(strip=True).replace("\u3003", "").replace("\u3000", "")
                for p in paragraphs
            )
        else:
            text = ""

        source_text = ""
        meta_source = soup.select_one('meta[name="source"]')
        if meta_source:
            source_text = meta_source.get("content", "")

        publish_date = ""
        meta_date = soup.select_one('meta[name="publishdate"]')
        if meta_date:
            publish_date = meta_date.get("content", "")

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
            source_text=source_text,
            summary="",
        )
```

- [ ] **Step 5: 运行 fetch_list 测试**

Run: `pytest tests/collector/test_xiongan_portal.py::test_fetch_list_parses_json_and_filters_links tests/collector/test_xiongan_portal.py::test_fetch_list_since_filters_old_items -v`
Expected: 2 passed

- [ ] **Step 6: 写 fetch_detail 测试**

```python
# 追加到 tests/collector/test_xiongan_portal.py

@respx.mock
def test_fetch_detail_extracts_title_and_body():
    """fetch_detail 应提取标题、正文（去掉全角空格）、来源、日期。"""
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    adapter = XionganPortalAdapter()
    raw = adapter.fetch_detail("https://www.xiongan.gov.cn/20260710/abc123/c.html")

    assert raw.title == "张国华调研重点项目"
    assert "7月10日" in raw.text
    assert "调研组先后" in raw.text
    assert "\u3000" not in raw.text  # 全角空格已去除
    assert raw.source_text == "雄安发布"
    assert raw.publish_date == "2026-07-10"
```

- [ ] **Step 7: 运行验证通过**

Run: `pytest tests/collector/test_xiongan_portal.py -v`
Expected: 4 passed

- [ ] **Step 8: Commit**

```bash
git add collector/adapters/xiongan_portal.py tests/collector/
git commit -m "feat: 雄安官网爬虫 adapter — JSON datasource 列表 + 详情页正文抽取 + 增量限制"
```

---

## Task 7: 爬虫完整流程集成测试

**Files:**
- Test: `tests/e2e/test_collect_e2e.py`

- [ ] **Step 1: 写集成测试（mock HTTP，验证完整入库流程）**

```python
# tests/e2e/test_collect_e2e.py
import respx
import pytest
from tests.collector.fixtures import SAMPLE_DATASOURCE_JSON, SAMPLE_DETAIL_HTML
from storage.models import init_db, Document, CrawlRun, close_db, get_conn
from collector.adapters.xiongan_portal import XionganPortalAdapter


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


@respx.mock
def test_full_collect_pipeline():
    """端到端：fetch_list → fetch_detail → 去重 → 入库 → crawl_run 记录。"""
    # Mock JSON 列表
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    # Mock 详情页
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    adapter = XionganPortalAdapter()
    result = adapter.run()

    assert result["new"] == 1
    assert result["errors"] == 0

    # 验证文档已入库
    docs = Document.list(source="xiongan_portal")
    assert len(docs) == 1
    assert docs[0].title == "张国华调研重点项目"
    assert "7月10日" in docs[0].text

    # 验证 crawl_run 记录
    run = CrawlRun.latest_by_source("xiongan_portal")
    assert run.status == "success"
    assert run.new_count == 1
    assert run.error_count == 0


@respx.mock
def test_dedup_skips_already_collected():
    """重复运行不应产生重复文档。"""
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    adapter = XionganPortalAdapter()
    adapter.run()       # 第一次：1 条
    result = adapter.run()  # 第二次：增量+去重，0 条
    assert result["new"] == 0
    assert Document.count(source="xiongan_portal") == 1


@respx.mock
def test_incremental_crawl_uses_last_crawled_date():
    """增量爬取：第二次运行应基于 last_crawled_date 只获取新增内容。"""
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    adapter = XionganPortalAdapter()
    # 第一次运行
    result1 = adapter.run()
    assert result1["new"] == 1
    assert result1["latest_date"] == "2026-07-10"

    # 第二次运行：since 应自动设为 "2026-07-10"，列表中该条目的日期不 > since，返回0
    result2 = adapter.run()
    assert result2["since"] == "2026-07-10"
    assert result2["new"] == 0

    # crawl_run 记录了 last_crawled_date
    from storage.models import CrawlRun
    assert CrawlRun.get_last_crawled_date("xiongan_portal") == "2026-07-10"
```

- [ ] **Step 2: 运行验证**

Run: `pytest tests/e2e/test_collect_e2e.py -v`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/
git commit -m "test: 爬虫完整流程集成测试 — 列表→详情→去重→入库"
```

---

## Task 8: FastAPI 后端 — 文档与抓取 API

**Files:**
- Create: `web/app.py`
- Create: `web/api/documents.py`
- Create: `web/api/collect.py`
- Test: `tests/web/test_api.py`

- [ ] **Step 1: 写失败测试 — 文档列表 API**

```python
# tests/web/test_api.py
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, Document, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    # 插入测试数据
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试文档A",
        url="http://a", publish_date="2026-07-10",
        raw_html="", text="content-a", content_hash="hash-a",
    )
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试文档B",
        url="http://b", publish_date="2026-07-09",
        raw_html="", text="content-b", content_hash="hash-b",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_list_documents(client):
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    # 按日期降序
    assert data["items"][0]["title"] == "测试文档A"

def test_list_documents_filter_by_source(client):
    resp = client.get("/api/documents?source=xiongan_portal")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2

def test_list_documents_pagination(client):
    resp = client.get("/api/documents?limit=1&offset=0")
    assert resp.json()["total"] == 2
    assert len(resp.json()["items"]) == 1

def test_get_document_detail(client):
    doc = Document.list()[0]
    resp = client.get(f"/api/documents/{doc.id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == doc.title
    assert resp.json()["text"] == doc.text
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/web/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'web.app'`

- [ ] **Step 3: 实现 web/app.py**

```python
# web/app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from web.api import documents, collect


def create_app() -> FastAPI:
    app = FastAPI(title="雄安信息商机挖掘系统", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(documents.router, prefix="/api")
    app.include_router(collect.router, prefix="/api")
    return app
```

- [ ] **Step 4: 实现 web/api/documents.py**

```python
# web/api/documents.py
from fastapi import APIRouter, HTTPException, Query
from storage.models import Document

router = APIRouter()


@router.get("/documents")
def list_documents(
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = Document.count(source=source)
    docs = Document.list(source=source, limit=limit, offset=offset)
    return {
        "total": total,
        "items": [d.to_dict() for d in docs],
    }


@router.get("/documents/{doc_id}")
def get_document(doc_id: int):
    doc = Document.get_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        **doc.to_dict(),
        "text": doc.text,
        "raw_html": doc.raw_html,
    }
```

- [ ] **Step 5: 实现 web/api/collect.py**

```python
# web/api/collect.py
from fastapi import APIRouter, BackgroundTasks
from storage.models import CrawlRun

router = APIRouter()


@router.post("/collect/trigger")
def trigger_collect(background_tasks: BackgroundTasks, source: str = "xiongan_portal"):
    """触发抓取（后台执行）。"""
    from collector.adapters.xiongan_portal import XionganPortalAdapter

    def _run():
        adapter = XionganPortalAdapter()
        adapter.run()

    background_tasks.add_task(_run)
    return {"status": "started", "source": source}


@router.get("/collect/status")
def collect_status(source: str = "xiongan_portal"):
    """获取某数据源最近一次抓取状态。"""
    run = CrawlRun.latest_by_source(source)
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
```

- [ ] **Step 6: 运行验证通过**

Run: `pytest tests/web/test_api.py -v`
Expected: 4 passed

- [ ] **Step 7: 补充 collect API 测试**

```python
# 追加到 tests/web/test_api.py
def test_collect_sources_status(client):
    resp = client.get("/api/collect/sources")
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    portal = [s for s in sources if s["name"] == "xiongan_portal"][0]
    assert portal["enabled"] is True
    assert portal["doc_count"] == 2
    assert "zxyw" in portal["categories"]

def test_collect_status_no_runs(client):
    resp = client.get("/api/collect/status?source=xiongan_portal")
    assert resp.status_code == 200
    assert resp.json()["last_run"] is None
```

- [ ] **Step 8: 运行全部 API 测试**

Run: `pytest tests/web/test_api.py -v`
Expected: 6 passed

- [ ] **Step 9: Commit**

```bash
git add web/ tests/web/
git commit -m "feat: FastAPI 后端 — 文档列表/详情 + 抓取触发/状态/数据源 API"
```

---

## Task 9: Vue 前端骨架

**Files:**
- Create: `web/frontend/package.json`, `vite.config.ts`, `index.html`, `tsconfig.json`
- Create: `web/frontend/src/main.ts`, `App.vue`, `api/client.ts`

- [ ] **Step 1: 创建 package.json**

```json
{
  "name": "xa-info-collector-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.5.0",
    "vue-router": "^4.4.0",
    "pinia": "^2.2.0",
    "element-plus": "^2.8.0",
    "@element-plus/icons-vue": "^2.3.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "vue-tsc": "^2.1.0"
  }
}
```

- [ ] **Step 2: 创建 vite.config.ts（开发代理到 FastAPI）**

```typescript
// web/frontend/vite.config.ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: 创建 index.html 和入口文件**

```html
<!-- web/frontend/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>雄安信息商机挖掘系统</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

```typescript
// web/frontend/src/main.ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}
app.mount('#app')
```

```typescript
// web/frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/sources' },
    { path: '/sources', name: 'sources', component: () => import('../views/SourceStatus.vue') },
    { path: '/documents', name: 'documents', component: () => import('../views/DocumentList.vue') },
  ],
})

export default router
```

```typescript
// web/frontend/src/api/client.ts
import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export interface SourceInfo {
  name: string
  display_name: string
  enabled: boolean
  doc_count: number
  categories: string[]
}

export interface DocumentItem {
  id: number
  source: string
  doc_type: string
  title: string
  url: string
  publish_date: string
  is_analyzed: boolean
}

export interface DocumentListResponse {
  total: number
  items: DocumentItem[]
}

export const apiClient = {
  getSources: () => api.get<SourceInfo[]>('/collect/sources'),
  getCollectStatus: (source: string) => api.get('/collect/status', { params: { source } }),
  triggerCollect: (source: string) => api.post('/collect/trigger', null, { params: { source } }),
  getDocuments: (params: { source?: string; limit?: number; offset?: number }) =>
    api.get<DocumentListResponse>('/documents', { params }),
  getDocument: (id: number) => api.get(`/documents/${id}`),
}
```

- [ ] **Step 4: 创建 App.vue（布局骨架）**

```vue
<!-- web/frontend/src/App.vue -->
<template>
  <el-container style="min-height: 100vh">
    <el-header style="background: #1a1a2e; display: flex; align-items: center;">
      <h1 style="color: #fff; margin: 0; font-size: 18px; flex: 1;">雄安信息商机挖掘系统</h1>
    </el-header>
    <el-container>
      <el-aside width="200px" style="background: #16213e;">
        <el-menu :default-active="activeMenu" router style="border: none; background: transparent;">
          <el-menu-item index="/sources">
            <el-icon><Connection /></el-icon>
            <span>信息源状态</span>
          </el-menu-item>
          <el-menu-item index="/documents">
            <el-icon><Document /></el-icon>
            <span>文档列表</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style>
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
.el-aside .el-menu-item { color: #ccc; }
.el-aside .el-menu-item.is-active { color: #409eff; background: rgba(64,158,255,0.1); }
</style>
```

- [ ] **Step 5: Commit**

```bash
git add web/frontend/
git commit -m "feat: Vue 前端骨架 — Vite + Element Plus + 路由 + API 客户端"
```

---

## Task 10: 信息源状态页（前后端打通）

**Files:**
- Create: `web/frontend/src/views/SourceStatus.vue`
- Create: `web/frontend/src/stores/collector.ts`

- [ ] **Step 1: 创建 Pinia store**

```typescript
// web/frontend/src/stores/collector.ts
import { defineStore } from 'pinia'
import { apiClient, type SourceInfo } from '../api/client'
import { ref } from 'vue'

export const useCollectorStore = defineStore('collector', () => {
  const sources = ref<SourceInfo[]>([])
  const loading = ref(false)
  const triggerLoading = ref<string | null>(null)

  async function fetchSources() {
    loading.value = true
    try {
      const resp = await apiClient.getSources()
      sources.value = resp.data.sources
    } finally {
      loading.value = false
    }
  }

  async function triggerCollect(source: string) {
    triggerLoading.value = source
    try {
      await apiClient.triggerCollect(source)
    } finally {
      triggerLoading.value = null
    }
  }

  return { sources, loading, triggerLoading, fetchSources, triggerCollect }
})
```

- [ ] **Step 2: 创建 SourceStatus.vue**

```vue
<!-- web/frontend/src/views/SourceStatus.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">信息源状态</h2>
      <el-button type="primary" :icon="Refresh" @click="store.fetchSources" :loading="store.loading">
        刷新
      </el-button>
    </div>

    <el-table :data="store.sources" v-loading="store.loading" border>
      <el-table-column prop="display_name" label="数据源" width="180" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">
            {{ row.enabled ? '已启用' : '未启用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="doc_count" label="已抓取文档数" width="140" />
      <el-table-column label="栏目" min-width="200">
        <template #default="{ row }">
          <el-tag v-for="cat in row.categories" :key="cat" size="small" style="margin-right: 4px;">
            {{ cat }}
          </el-tag>
          <span v-if="!row.categories?.length" style="color: #999;">-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small" type="primary" :icon="Download"
            :disabled="!row.enabled"
            :loading="store.triggerLoading === row.name"
            @click="handleCollect(row.name)"
          >
            立即抓取
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { Refresh, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCollectorStore } from '../stores/collector'

const store = useCollectorStore()

onMounted(() => store.fetchSources())

async function handleCollect(source: string) {
  try {
    await store.triggerCollect(source)
    ElMessage.success('抓取任务已启动')
    // 3秒后刷新数据源状态
    setTimeout(() => store.fetchSources(), 3000)
  } catch {
    ElMessage.error('启动抓取失败')
  }
}
</script>
```

- [ ] **Step 3: 创建 DocumentList.vue（文档列表页，复用文档 API）**

```vue
<!-- web/frontend/src/views/DocumentList.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h2 style="margin: 0;">文档列表 ({{ total }})</h2>
      <el-select v-model="filterSource" placeholder="全部来源" clearable style="width: 200px;" @change="fetchData">
        <el-option v-for="s in enabledSources" :key="s.name" :label="s.display_name" :value="s.name" />
      </el-select>
    </div>

    <el-table :data="documents" v-loading="loading" border @row-click="openDetail">
      <el-table-column prop="title" label="标题" min-width="300" />
      <el-table-column prop="source" label="来源" width="150" />
      <el-table-column prop="publish_date" label="发布日期" width="130" sortable />
      <el-table-column label="分析状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_analyzed ? 'success' : 'warning'" size="small">
            {{ row.is_analyzed ? '已分析' : '待分析' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      style="margin-top: 16px; justify-content: center;"
      @current-change="fetchData"
    />

    <el-drawer v-model="drawerVisible" :title="selectedDoc?.title || ''" size="50%">
      <div v-if="selectedDoc" style="white-space: pre-wrap; line-height: 1.8;">
        <p><strong>来源：</strong>{{ selectedDoc.source }} | <strong>日期：</strong>{{ selectedDoc.publish_date }}</p>
        <p><strong>原文链接：</strong><a :href="selectedDoc.url" target="_blank">{{ selectedDoc.url }}</a></p>
        <el-divider />
        {{ selectedDoc.text }}
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { apiClient, type DocumentItem } from '../api/client'
import { useCollectorStore } from '../stores/collector'

const collectorStore = useCollectorStore()
const enabledSources = computed(() => collectorStore.sources.filter(s => s.enabled))

const documents = ref<DocumentItem[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 20
const filterSource = ref<string | undefined>(undefined)
const drawerVisible = ref(false)
const selectedDoc = ref<any>(null)

async function fetchData() {
  loading.value = true
  try {
    const resp = await apiClient.getDocuments({
      source: filterSource.value,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    documents.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function openDetail(row: DocumentItem) {
  const resp = await apiClient.getDocument(row.id)
  selectedDoc.value = resp.data
  drawerVisible.value = true
}

onMounted(async () => {
  await collectorStore.fetchSources()
  await fetchData()
})
</script>
```

- [ ] **Step 4: 验证前端构建**

Run: `cd web/frontend && npm install && npm run build`
Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/
git commit -m "feat: 信息源状态页 + 文档列表页 — 前后端端到端打通"
```

---

## Task 11: 端到端验证

**Files:**
- Test: `tests/e2e/test_full_stack.py`

- [ ] **Step 1: 写全链路测试 — 后端 API 完整性校验**

此测试确保前端调用的每个 API 都有对应的后端实现，不会出现"前台按钮点了报 404/500"。

```python
# tests/e2e/test_full_stack.py
"""全链路端到端测试：验证前端用到的每个 API 端点都有正确的后端实现。
确保不出现「前台功能后台未实现」或「前台 icon 无接口」的情况。
"""
import respx
import pytest
from fastapi.testclient import TestClient
from tests.collector.fixtures import SAMPLE_DATASOURCE_JSON, SAMPLE_DETAIL_HTML
from storage.models import init_db, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


# ---- 信息源状态页用到的全部 API ----

def test_api_get_sources_returns_array(client):
    """前端 SourceStatus.vue 表格数据源：GET /api/collect/sources"""
    resp = client.get("/api/collect/sources")
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert isinstance(data["sources"], list)
    assert len(data["sources"]) >= 1
    portal = [s for s in data["sources"] if s["name"] == "xiongan_portal"][0]
    # 前端表格用到的每个字段都必须存在
    assert "display_name" in portal
    assert "enabled" in portal
    assert "doc_count" in portal
    assert "categories" in portal


def test_api_trigger_collect(client):
    """前端「立即抓取」按钮：POST /api/collect/trigger"""
    resp = client.post("/api/collect/trigger", params={"source": "xiongan_portal"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"


def test_api_collect_status(client):
    """前端抓取后状态刷新：GET /api/collect/status"""
    resp = client.get("/api/collect/status", params={"source": "xiongan_portal"})
    assert resp.status_code == 200
    assert "last_run" in resp.json()


# ---- 文档列表页用到的全部 API ----

def test_api_documents_list_returns_items_and_total(client):
    """前端 DocumentList.vue：GET /api/documents"""
    resp = client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)


def test_api_documents_filter_and_pagination(client):
    """前端筛选和分页参数。"""
    resp = client.get("/api/documents?source=xiongan_portal&limit=10&offset=0")
    assert resp.status_code == 200


def test_api_document_detail(client):
    """前端文档详情抽屉：GET /api/documents/{id}"""
    # 先插入数据
    from storage.models import Document
    doc = Document.create(
        source="xiongan_portal", doc_type="新闻", title="详情测试",
        url="http://detail-test", publish_date="2026-07-10",
        raw_html="<p>r</p>", text="详情正文", content_hash="detailhash",
    )
    resp = client.get(f"/api/documents/{doc.id}")
    assert resp.status_code == 200
    assert resp.json()["text"] == "详情正文"


def test_api_document_detail_404(client):
    """不存在的文档返回 404。"""
    resp = client.get("/api/documents/99999")
    assert resp.status_code == 404


# ---- 完整业务流程：抓取 → 入库 → 列表展示 ----

@respx.mock
def test_e2e_collect_then_list(client):
    """模拟真实流程：触发抓取 → 文档入库 → 列表 API 能查到。"""
    respx.get(
        "https://www.xiongan.gov.cn/xaxw/ds_faa2cd6debde4c7bbacb8352bc94a894.json"
    ).respond(json=SAMPLE_DATASOURCE_JSON)
    respx.get("https://www.xiongan.gov.cn/20260710/abc123/c.html").respond(
        text=SAMPLE_DETAIL_HTML
    )

    # 直接调用 adapter（不走 background task，测试中同步执行）
    from collector.adapters.xiongan_portal import XionganPortalAdapter
    adapter = XionganPortalAdapter()
    adapter.run()

    # 列表 API 能查到
    resp = client.get("/api/documents?source=xiongan_portal")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "张国华调研重点项目"

    # 数据源统计更新
    resp = client.get("/api/collect/sources")
    portal = [s for s in resp.json()["sources"] if s["name"] == "xiongan_portal"][0]
    assert portal["doc_count"] == 1
```

- [ ] **Step 2: 运行全链路测试**

Run: `pytest tests/e2e/test_full_stack.py -v`
Expected: 8 passed

- [ ] **Step 3: 运行全部测试确认无回归**

Run: `pytest tests/ -v`
Expected: 全部 passed（约 25 个测试）

- [ ] **Step 4: 手动端到端验证（真实抓取）**

```bash
# 终端1：启动后端
source .venv/bin/activate
python -c "from storage.models import init_db; init_db()"
uvicorn web.app:create_app --factory --reload

# 终端2：启动前端
cd web/frontend && npm install && npm run dev

# 浏览器打开 http://localhost:5173
# 1. 信息源状态页：看到「中国雄安官网」，doc_count=0
# 2. 点「立即抓取」→ 等待几秒 → 刷新 → doc_count 应增加
# 3. 文档列表页：能看到真实抓取的雄安新闻
# 4. 点标题：抽屉展示正文
```

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_full_stack.py
git commit -m "test: 全链路端到端测试 — 前后端 API 一致性校验"
```

---

## Task 12: 实施文档

**Files:**
- Create: `docs/impl/increment1-foundation.md`

- [ ] **Step 1: 撰写实施文档**

```markdown
# 增量 1 实施文档：项目骨架 + 存储层 + 雄安官网爬虫 + 信息源状态页

> 创建日期：2026-07-10
> 状态：已完成

## 交付内容

### 后端
- **存储层**（storage/）：SQLite + documents/crawl_errors/crawl_runs 三表
- **去重模块**（collector/deduper.py）：content_hash 校验
- **配置加载**（collector/config.py）：sources.yaml 数据源配置
- **BaseAdapter**（collector/base.py）：抓取流程编排框架
- **雄安官网爬虫**（collector/adapters/xiongan_portal.py）：JSON datasource API + 详情页正文抽取
- **FastAPI 后端**（web/）：文档列表/详情 + 抓取触发/状态/数据源 API

### 前端
- **Vue 3 骨架**：Vite + Element Plus + Pinia + Vue Router
- **信息源状态页**（SourceStatus.vue）：表格展示数据源 + 立即抓取按钮
- **文档列表页**（DocumentList.vue）：文档表格 + 筛选 + 详情抽屉

### 测试
- 存储层 CRUD 测试（4 个）
- 去重测试（4 个）
- 配置加载测试（3 个）
- 爬虫 adapter 测试（3 个，mock HTTP）
- 爬虫完整流程集成测试（2 个）
- API 测试（6 个）
- 全链路端到端测试（8 个，含 API 一致性校验）

## 关键技术决策

### 雄安官网爬虫策略
发现官网有隐藏的 JSON datasource API（`/栏目目录/ds_{hex}.json`），一次请求返回完整列表（最多1000条），无需翻页。详情页是 SSR 静态 HTML，用 BeautifulSoup 直接解析。

### 并发控制（保护目标服务器）
- **严格单线程顺序抓取**，禁止任何并发/线程池/async 请求。
- **QPS 限速**：默认 qps=2（每0.5秒最多1个请求），通过 `_throttle()` 强制间隔。
- **首次全量限制**：第一次运行最多抓取 INITIAL_BATCH=50 条详情页，不全量扫1000条。后续靠增量补充历史数据。

### 增量爬取策略
- `crawl_runs.last_crawled_date` 记录每次成功抓取的最新日期。
- 每次 `run()` 自动读取上次日期作为 `since` 参数，只获取新增内容。
- 列表 JSON 按日期降序，遍历时遇到更早日期立即 break，减少无用遍历。
- content_hash 去重作为双重保障。

### URL 解析
列表 JSON 中的 `publishUrl` 是相对路径（如 `../20260710/abc/c.html`），用 `urljoin(base + list_url, publishUrl)` 解析为绝对 URL。

## 端到端验证结果

- [x] 全部单元/集成测试通过（约30个）
- [x] API 一致性测试通过（前端用到的每个端点都有后端实现）
- [x] 手动验证：真实抓取雄安官网 → 文档入库 → 前端展示

## 已知限制

- 仅实现雄安官网（xiongan_portal）一个数据源，其他三个（公共资源交易、雄安集团、县区省级）在后续增量
- 爬虫需手动或定时触发，尚未接入 APScheduler（后续增量）
- 文档已入库但未接 LLM 分析（增量 2）

## 修复记录

（如有测试发现的问题，记录于此）
```

- [ ] **Step 2: Commit**

```bash
git add docs/impl/increment1-foundation.md
git commit -m "docs: 增量1实施文档"
```

---

## 完成标准（Definition of Done）

本增量完成需满足：

1. ✅ `pytest tests/ -v` 全部通过
2. ✅ 前端 `npm run build` 无 TypeScript 错误
3. ✅ 手动验证：真实抓取雄安官网新闻，前端展示
4. ✅ 前端调用的每个 API 都有后端实现（test_full_stack.py 校验）
5. ✅ 前端每个交互按钮都有对应后端接口（无"前台 icon 无接口"）
6. ✅ 每个功能点有 git commit
7. ✅ 实施文档已撰写
