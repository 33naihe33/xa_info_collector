"""雄安官网爬虫 adapter。

注意：本 adapter 使用 httpx.Client（同步）发起 HTTP 请求。
原因：测试使用 respx 做 HTTP mock，而 respx 只拦截 httpx，不拦截 requests。
行为上与 requests.Session 等价：同步、单线程、连接复用。
"""
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc, _normalize_publish_date, _validate_date_range


class XionganPortalAdapter(BaseAdapter):
    source_name = "xiongan_portal"
    BASE = "https://www.xiongan.gov.cn"

    def __init__(self):
        super().__init__()
        self.session = httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
            },
        )

    def _get(self, url: str) -> httpx.Response:
        self._throttle()
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp

    def run(self, since: str | None = None, until: str | None = None) -> dict:
        """遍历所有配置的栏目进行抓取。每个栏目独立错误隔离。

        F-04：栏目循环前先排空 category=None 全局桶（遗留未分类错误），
        循环内每栏目调用 _retry_pending(category=cat) 重试该栏目 pending。
        """
        from storage.models import CrawlError

        _validate_date_range(since, until)
        total_new = 0
        total_errors = 0
        categories = self.config.get("categories", {})

        # F-04：先排空全局桶（category IS NULL 的遗留错误）
        if until is None:
            self._retry_pending(category=None)

        for cat_name, cat_cfg in categories.items():
            if not cat_cfg.get("datasource_path"):
                continue  # 跳过无 datasource 的栏目（如 tzgg）
            try:
                # 栏目级 pending 重试
                if until is None:
                    self._retry_pending(category=cat_name)
                result = self._run_category(cat_name, cat_cfg, since, until)
                total_new += result.get("new", 0)
                total_errors += result.get("errors", 0)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Category {cat_name} failed: {e}")
                total_errors += 1

        return {"new": total_new, "errors": total_errors}

    def _run_category(self, category: str, cat_cfg: dict, since: str | None, until: str | None = None) -> dict:
        """抓取单个栏目（栏目级游标隔离）。"""
        from storage.models import CrawlError, CrawlRun

        # R-03：栏目级增量游标（按 source + category）
        cat_since = since
        if cat_since is None:
            cat_since = CrawlRun.get_last_crawled_date(self.source_name, category=category)

        run = CrawlRun.start(self.source_name, category=category)
        new_count = 0
        error_count = 0
        latest_date = cat_since or ""

        try:
            items = self.fetch_list(since=cat_since, category=category)
            for item in items:
                publish_date = _normalize_publish_date(item.publish_date)
                if until is not None and (not publish_date or publish_date < cat_since or publish_date > until):
                    continue
                if publish_date:
                    item.publish_date = publish_date
                if item.url and CrawlError.is_dead(self.source_name, item.url, category=category):
                    continue
                try:
                    result = (self._ingest_detail(item, category=category, since=cat_since, until=until)
                              if until is not None else self._ingest_detail(item, category=category))
                    if result.is_new:
                        new_count += 1
                        if result.publish_date and result.publish_date > latest_date:
                            latest_date = result.publish_date
                except Exception as e:
                    CrawlError.log(self.source_name, item.url, str(e), category=category)
                    error_count += 1
            if error_count > 0:
                run.finish(new_count=new_count, error_count=error_count,
                           status="success_with_errors", last_crawled_date=None if until is not None else cat_since)
            else:
                run.finish(new_count=new_count, error_count=error_count,
                           status="success", last_crawled_date=None if until is not None else latest_date or None)
        except Exception as e:
            run.finish(new_count=new_count, error_count=error_count, status="failed", last_crawled_date=None)
            CrawlError.log(self.source_name, None, f"fetch_list failed for {category}: {e}", category=category)
            raise

        return {"new": new_count, "errors": error_count, "run_id": run.id}

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

        # 提取文章图片URL
        import json
        images = []
        if content_el:
            for img in content_el.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    # 图片 src 是相对文章目录的文件名，用文章 URL 解析（不是 BASE）
                    img_url = urljoin(url, src)
                    images.append(img_url)
        images_json = json.dumps(images[:5], ensure_ascii=False)  # 最多5张

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
            source_text=source_text,
            summary="",
            images=images_json,
        )
