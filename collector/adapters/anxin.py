"""安新县政府 (anxin_gov) 爬虫 adapter。

列表页：/news/3/10/1.html（安新要闻）
列表项：li.xxgk-comm-line，标题在 li > a，日期在 li span.fr（格式 2026-07-09）
详情正文：div#conN，标题：input[name="ArticleTitle"] 的 value
详情日期：正则 发布时间：(YYYY-MM-DD)
"""
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_PUBLISH_TIME_RE = re.compile(r"发布时间[：:]\s*(\d{4}-\d{2}-\d{2})")


class AnxinAdapter(BaseAdapter):
    source_name = "anxin_gov"
    BASE = "https://www.anxin.gov.cn"
    INITIAL_BATCH = 20

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
        resp.encoding = resp.charset_encoding or "utf-8"
        return resp

    def fetch_list(self, since: str | None = None) -> list[ListItem]:
        """安新县列表页是JS渲染的，从首页抓取新闻链接。

        首页的新闻链接 URL 模式：/news/00-80-67-1-10/{id}.html
        """
        url = urljoin(self.BASE + "/", "/")
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        items = []
        seen_urls = set()
        # 首页所有指向文章详情的链接
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/news/00-" not in href:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 4:
                continue
            item_url = urljoin(self.BASE + "/", href)
            if item_url in seen_urls:
                continue
            seen_urls.add(item_url)

            # 首页列表项没有日期，留空，详情页会补充
            publish_date = ""

            items.append(ListItem(
                title=title,
                url=item_url,
                publish_date=publish_date,
            ))

        # since 过滤（首页无日期，跳过 since 过滤，靠去重保障）
        if since is None:
            items = items[: self.INITIAL_BATCH]

        return items

    def fetch_detail(self, url: str) -> RawDoc:
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # 标题：input[name="ArticleTitle"] 的 value
        title = ""
        title_input = soup.select_one('input[name="ArticleTitle"]')
        if title_input:
            title = title_input.get("value", "").strip()
        elif soup.title:
            title = soup.title.get_text(strip=True)

        # 正文：div#conN
        content_el = soup.select_one("div#conN") or soup.select_one("#conN")
        if content_el:
            paragraphs = content_el.find_all("p")
            if not paragraphs:
                text = content_el.get_text("\n", strip=True)
            else:
                text = "\n".join(
                    p.get_text(strip=True).replace("\u3003", "").replace("\u3000", "")
                    for p in paragraphs
                )
        else:
            text = ""

        # 日期：发布时间：YYYY-MM-DD
        publish_date = ""
        m = _PUBLISH_TIME_RE.search(html)
        if m:
            publish_date = m.group(1)
        else:
            m2 = _DATE_RE.search(html)
            if m2:
                publish_date = m2.group(1)

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
        )
