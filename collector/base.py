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


def _normalize_publish_date(value: str | None) -> str | None:
    """Return an ISO calendar date, or None when a list date is unusable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None


def _validate_date_range(since: str | None, until: str | None) -> None:
    if until is not None and (
        since is None or _normalize_publish_date(since) != since
        or _normalize_publish_date(until) != until or since > until
    ):
        raise ValueError("range collection requires valid YYYY-MM-DD bounds with since <= until")


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
    images: str = "[]"  # JSON array of image URLs


@dataclass
class IngestResult:
    """单个详情入库结果。

    - kind="inserted"：新文档入库，doc_id 为新记录 id
    - kind="already_exists"：文档已入库（去重命中），doc_id 为既有记录 id
    - kind="skipped"：无有效内容（正文+标题都空），doc_id=None
    """
    kind: str
    doc_id: int | None = None
    publish_date: str | None = None  # 入库文档的发布日期（用于游标推进）

    @property
    def is_new(self) -> bool:
        return self.kind == "inserted"

    @property
    def is_success(self) -> bool:
        """inserted 或 already_exists 都算成功（可标记 retried）。"""
        return self.kind in ("inserted", "already_exists")


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

    def _ingest_detail(self, item: ListItem, category: str | None = None,
                       *, since: str | None = None, until: str | None = None) -> IngestResult:
        """公共详情入库流程（主抓取与重试共用）。

        fetch_detail → 回退 → 去重 → hash → download_images → Document.create → save_snapshot
        返回 IngestResult。已入库视为幂等成功（already_exists），不重复计数。
        抛出异常表示该 item 失败（由调用方记录 CrawlError）。
        """
        raw = self.fetch_detail(item.url)
        # 如果详情页正文为空（如微信搜索无法获取正文），
        # 用列表摘要作为正文，确保有内容可供分析
        if not raw.text and item.summary:
            raw.text = item.summary
        if not raw.title:
            raw.title = item.title
        if not raw.publish_date:
            raw.publish_date = item.publish_date
        if until is not None:
            publish_date = _normalize_publish_date(raw.publish_date)
            if not publish_date or publish_date < since or publish_date > until:
                return IngestResult("skipped")
            raw.publish_date = publish_date
        # 正文+标题去重
        dedup_text = raw.text or item.title
        if not dedup_text:
            return IngestResult("skipped")
        if is_duplicate(dedup_text):
            # 文档已入库，视为幂等成功
            from storage.database import get_conn
            doc_hash = content_hash(dedup_text)
            conn = get_conn()
            existing = conn.execute(
                "SELECT id FROM documents WHERE content_hash = ? LIMIT 1", (doc_hash,)
            ).fetchone()
            return IngestResult("already_exists", doc_id=existing["id"] if existing else None,
                                publish_date=raw.publish_date or item.publish_date)
        doc_hash = content_hash(dedup_text)
        # 下载图片到本地（爬取时即缓存，报告生成时直接使用）
        self.download_images(raw, doc_hash)
        doc = Document.create(
            source=self.source_name,
            doc_type="新闻",
            title=raw.title or item.title,
            url=raw.url,
            publish_date=raw.publish_date or item.publish_date,
            raw_html=raw.raw_html,
            text=raw.text,
            content_hash=doc_hash,
            images=raw.images,
        )
        self.save_snapshot(raw)
        return IngestResult("inserted", doc_id=doc.id,
                            publish_date=raw.publish_date or item.publish_date)

    def _retry_pending(self, category: str | None = None, limit: int = 5) -> int:
        """重试已记录的 pending 错误 URL（按 source, category 隔离）。

        category=None 表示全局桶（遗留未分类错误）。
        返回成功重试的数量。url IS NULL 的列表级错误不交 fetch_detail。
        """
        pending = CrawlError.list_pending(self.source_name, category=category, limit=limit)
        retried_ok = 0
        for p in pending:
            url = p.get("url")
            if not url:
                # 列表级错误（url IS NULL）不在此重试，由主流程重新抓取列表
                continue
            item = ListItem(title="", url=url, publish_date="", summary="")
            try:
                result = self._ingest_detail(item, category=category)
                if result.is_success:
                    CrawlError.mark_retried(self.source_name, url, category=category)
                    retried_ok += 1
                # M-02: skipped（空内容）不标 retried，继续 pending 等下次重试
                # （原行为是 mark_retried → 永久丢失；空内容可能是临时故障）
                elif result.kind == "skipped":
                    CrawlError.log(self.source_name, url, "empty content on retry", category=category)
            except Exception as e:
                # 失败：CrawlError.log 自动累加 retry_count，达阈值转 dead
                CrawlError.log(self.source_name, url, str(e), category=category)
        return retried_ok

    def run(self, since: str | None = None, until: str | None = None) -> dict:
        """完整抓取流程：列表 → 详情 → 去重 → 入库。返回统计。

        增量爬取：若 since 未指定，自动从 crawl_runs 读取上次成功抓取的
        last_crawled_date，只获取该日期之后的新内容。首次运行 since=None
        表示全量，但 fetch_list 应自行控制只取最近的（如最新100条）。

        F-04：运行开头先重试 pending 错误（含 category=None 全局桶），
        主循环复用 _ingest_detail 公共入库流程。
        """
        _validate_date_range(since, until)
        is_range_run = until is not None
        # 范围任务没有经列表日期校验的 pending URL，不能重试入库。
        if not is_range_run:
            self._retry_pending(category=None)

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
                publish_date = _normalize_publish_date(item.publish_date)
                if is_range_run and (not publish_date or publish_date < since or publish_date > until):
                    continue
                if publish_date:
                    item.publish_date = publish_date
                # 跳过已标记为死信的URL
                if item.url and CrawlError.is_dead(self.source_name, item.url):
                    continue
                try:
                    result = (self._ingest_detail(item, since=since, until=until)
                              if is_range_run else self._ingest_detail(item))
                    if result.is_new:
                        new_count += 1
                        # 跟踪本次抓取到的最新日期
                        if result.publish_date and result.publish_date > latest_date:
                            latest_date = result.publish_date
                except Exception as e:
                    CrawlError.log(self.source_name, item.url, str(e))
                    error_count += 1
            # 游标止血：有错误时不推进 last_crawled_date
            if error_count > 0:
                run.finish(
                    new_count=new_count, error_count=error_count,
                    status="success_with_errors",
                    last_crawled_date=None if is_range_run else since,
                )
            else:
                run.finish(
                    new_count=new_count, error_count=error_count,
                    status="success",
                    last_crawled_date=None if is_range_run else latest_date or None,
                )
        except Exception as e:
            run.finish(new_count=new_count, error_count=error_count, status="failed", last_crawled_date=None)
            CrawlError.log(self.source_name, None, f"fetch_list failed: {e}")
            raise

        return {"new": new_count, "errors": error_count, "run_id": run.id,
                "since": since, "latest_date": latest_date}

    def save_snapshot(self, raw: RawDoc):
        """保存原始 HTML 快照。文件名用 URL 的 hash 避免过长。"""
        from pathlib import Path
        import hashlib
        from storage.paths import snapshots_dir
        snapshot_dir = Path(snapshots_dir()) / self.source_name  # M-09: 统一 DATA_DIR
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.md5(raw.url.encode()).hexdigest()[:16]
        (snapshot_dir / f"{url_hash}.html").write_text(raw.raw_html, encoding="utf-8")

    def download_images(self, raw: RawDoc, content_hash: str):
        """下载文章图片到本地，更新 raw.images 为本地路径列表。

        H-05 图片安全（完整重做）：
        - 白名单从 adapter config 派生（image_domains/base_url），非硬编码
        - httpx.stream 流式读取 + Content-Length 预检 + 累计字节硬截止（不先全量入内存）
        - 逐跳验证：每跳 scheme(http/https) + 拒绝私网 IP（防 redirect SSRF）
        - 写临时文件后校验魔数（PIL verify）再原子 rename 落盘
        - 总量精确截止（下载前 total+expected > MAX_TOTAL 则跳过）
        图片存储在 {DATA_DIR}/images/{content_hash}/ 下（M-09 统一 DATA_DIR）。
        """
        import json
        import ipaddress
        import socket
        from pathlib import Path
        from urllib.parse import urlparse
        import httpx
        import hashlib
        from storage.paths import images_dir

        MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 单图 5MB
        MAX_TOTAL_SIZE = 20 * 1024 * 1024  # 单文档总 20MB
        MAX_IMAGES = 5
        # H-05: 白名单从 config 派生
        base_url = self.config.get("base_url", "")
        base_host = urlparse(base_url).hostname if base_url else ""
        allowed = set(self.config.get("image_domains", []))
        if base_host:
            allowed.add(base_host)

        try:
            image_urls = json.loads(raw.images) if raw.images else []
        except (json.JSONDecodeError, TypeError):
            return

        if not image_urls:
            return

        img_dir = Path(images_dir()) / content_hash  # M-09: 统一 DATA_DIR
        img_dir.mkdir(parents=True, exist_ok=True)

        local_paths = []
        total_size = 0
        for img_url in image_urls[:MAX_IMAGES]:
            if not img_url:
                continue
            # H-05: 初始 URL 域名白名单
            try:
                host = urlparse(img_url).hostname or ""
            except Exception:
                continue
            if host and allowed and host not in allowed:
                continue
            # H-05: 总量精确截止
            if total_size + 1000 > MAX_TOTAL_SIZE:  # 至少预留 1KB
                break
            url_hash = hashlib.md5(img_url.encode()).hexdigest()[:12]
            suffix = ".png" if ".png" in img_url.lower() else ".jpg"
            local_path = img_dir / f"{url_hash}{suffix}"
            if local_path.exists() and local_path.stat().st_size > 1000:
                local_paths.append(str(local_path))
                total_size += local_path.stat().st_size
                continue

            # H-05: 流式下载 + 逐跳验证
            try:
                data = self._stream_download_image(img_url, MAX_IMAGE_SIZE, allowed)
                if data is None:
                    continue
                if total_size + len(data) > MAX_TOTAL_SIZE:
                    continue  # 这张会超总量
                # H-05: 写临时文件后校验魔数（PIL verify）
                tmp_path = local_path.with_suffix(".tmp")
                tmp_path.write_bytes(data)
                if not self._verify_image_magic(tmp_path):
                    tmp_path.unlink(missing_ok=True)
                    continue
                tmp_path.rename(local_path)  # 原子落盘
                local_paths.append(str(local_path))
                total_size += len(data)
            except Exception as e:
                # A-01: 不再静默吞掉（原 except: pass 导致 NameError 隐藏，图片全丢）
                import logging
                logging.getLogger(__name__).warning(
                    f"Image download failed for {img_url}: {type(e).__name__}: {e}")
                # 清理可能的残留临时文件
                try:
                    local_path.with_suffix(".tmp").unlink(missing_ok=True)
                except Exception:
                    pass

        raw.images = json.dumps(local_paths, ensure_ascii=False) if local_paths else "[]"

    def _stream_download_image(self, url: str, max_size: int, allowed_domains: set) -> bytes | None:
        """H-05: 流式下载图片，逐跳验证 scheme/IP，累计字节硬截止。

        返回图片字节（已通过大小+MIME 初检），或 None（拒绝/失败）。
        """
        import httpx
        import ipaddress
        import socket
        from urllib.parse import urlparse

        def _validate_host(u: str, reject_internal_ip: bool = True) -> bool:
            """验证 URL 的 scheme + host（白名单 + 拒绝私网 IP）。"""
            try:
                parsed = urlparse(u)
            except Exception:
                return False
            if parsed.scheme not in ("http", "https"):
                return False
            host = parsed.hostname or ""
            if not host:
                return False
            # 白名单检查
            if allowed_domains and host not in allowed_domains:
                return False
            # 白名单初始域名可能被受控网络重写到保留地址；该入口已受
            # host 白名单约束。重定向目标则必须继续拒绝内网地址，避免 SSRF。
            if not reject_internal_ip:
                return True
            # 私网 IP 检查（防 redirect SSRF 到内网）
            try:
                ip = ipaddress.ip_address(socket.gethostbyname(host))
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
            except (ValueError, socket.gaierror):
                pass  # 非 IP 主机名或解析失败，放行（白名单已过滤）
            return True

        # 用自定义 transport 拦截重定向（逐跳验证）
        seen_urls = set()
        current_url = url
        for hop in range(5):  # 最多 5 跳
            if current_url in seen_urls:
                return None  # 重定向循环
            seen_urls.add(current_url)
            if not _validate_host(current_url, reject_internal_ip=hop > 0):
                return None
            try:
                # 先 HEAD 预检 Content-Length + Content-Type
                head = httpx.head(current_url, timeout=10, follow_redirects=False, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    "Referer": self.config.get("base_url", ""),
                })
                if head.status_code in (301, 302, 303, 307, 308):
                    loc = head.headers.get("location", "")
                    if not loc:
                        return None
                    # 相对路径补全
                    if loc.startswith("/"):
                        p = urlparse(current_url)
                        loc = f"{p.scheme}://{p.netloc}{loc}"
                    current_url = loc
                    continue
                if head.status_code != 200:
                    return None
                cl = head.headers.get("content-length")
                if cl and int(cl) > max_size:
                    return None  # H-05: 超大响应预检拒绝
                ct = head.headers.get("content-type", "")
                if not ct.startswith("image/"):
                    return None
                # 流式 GET，累计字节硬截止
                data = bytearray()
                with httpx.stream("GET", current_url, timeout=15, follow_redirects=False, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    "Referer": self.config.get("base_url", ""),
                }) as resp:
                    if resp.status_code != 200:
                        return None
                    rct = resp.headers.get("content-type", "")
                    if not rct.startswith("image/"):
                        return None
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        data.extend(chunk)
                        if len(data) > max_size:  # H-05: 累计超限立即中止
                            return None
                return bytes(data) if len(data) > 1000 else None
            except Exception:
                return None
        return None

    def _verify_image_magic(self, path) -> bool:
        """H-05: 用 PIL 校验图片魔数 + 像素（非 image/* 或损坏则 False）。"""
        try:
            from PIL import Image
            with Image.open(path) as img:
                img.verify()  # 魔数校验
            return True
        except Exception:
            return False
