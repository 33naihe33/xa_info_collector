"""容城县政府 (rongcheng_gov) 爬虫 adapter。

列表页：/news/2/10/1.html（容城动态）
列表项：li.xxgk-comm-line，标题在 li > a，日期在 li span（格式 2026-07-10）
详情正文：div.con#content，标题：div.cont_title，日期：div.rq
"""
import re
import subprocess
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class RongchengAdapter(BaseAdapter):
    source_name = "rongcheng_gov"
    BASE = "https://www.hbrc.gov.cn"
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
        self._assert_official_host(url)
        self._throttle()
        try:
            resp = self.session.get(url)
        except httpx.ConnectError as exc:
            if "SSLV3_ALERT_HANDSHAKE_FAILURE" not in str(exc):
                raise
            result = subprocess.run(
                ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "30", url],
                check=True,
                capture_output=True,
            )
            resp = httpx.Response(
                200,
                content=result.stdout,
                request=httpx.Request("GET", url),
            )
        resp.raise_for_status()
        resp.encoding = resp.charset_encoding or "utf-8"
        return resp

    def _assert_official_host(self, url: str) -> None:
        if urlparse(url).hostname != urlparse(self.BASE).hostname:
            raise ValueError("URL is not on the official host")

    def fetch_list(self, since: str | None = None) -> list[ListItem]:
        list_url = self.config.get("list_url") or "/news/2/10/1.html"
        url = urljoin(self.BASE + "/", list_url)
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        items = []
        for li in soup.select("li.xxgk-comm-line"):
            a = li.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or not href:
                continue
            item_url = urljoin(self.BASE + "/", href)

            publish_date = ""
            span = li.select_one("span")
            if span:
                m = _DATE_RE.search(span.get_text())
                if m:
                    publish_date = m.group(1)

            if since and publish_date and publish_date < since:
                continue

            items.append(ListItem(
                title=title,
                url=item_url,
                publish_date=publish_date,
            ))

        if since is None:
            items = items[: self.INITIAL_BATCH]

        return items

    def fetch_detail(self, url: str) -> RawDoc:
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # 标题
        title = ""
        title_el = soup.select_one("div.cont_title")
        if title_el:
            title = title_el.get_text(strip=True)
        elif soup.title:
            title = soup.title.get_text(strip=True)

        # 正文：div.con#content
        content_el = soup.select_one("div.con#content") or soup.select_one("#content")
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

        # 日期
        publish_date = ""
        date_el = soup.select_one("div.rq")
        if date_el:
            m = _DATE_RE.search(date_el.get_text())
            if m:
                publish_date = m.group(1)

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
        )
