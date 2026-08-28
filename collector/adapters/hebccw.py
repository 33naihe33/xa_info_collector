"""长城新媒体雄安频道 (hebccw) 爬虫 adapter。

列表页为静态 HTML：div.centerLeft > a 或 div.centerLeftLi，
标题在 .centerTitle，日期在 .centerTime span（格式 2026-07-13 13:07:49）。
详情正文：div.detailMessage，标题：div.detailTitle span。
"""
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc

# 匹配 YYYY-MM-DD 前缀
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class HebccwAdapter(BaseAdapter):
    source_name = "hebccw"
    BASE = "https://xiongan.hebccw.cn"
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
        list_url = self.config.get("list_url") or "/xaxw/index.shtml"
        url = urljoin(self.BASE + "/", list_url)
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        items = []
        seen = set()
        # 列表项：div.centerLeft 内的 a 或 div.centerLeftLi
        for node in soup.select("div.centerLeft a, div.centerLeftLi, div.centerLeft li"):
            # 取该节点内的标题与日期
            title_el = node.select_one(".centerTitle")
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                title = node.get_text(strip=True)
            if not title:
                # 可能是纯链接节点，跳过没有有效文本的
                continue

            href = node.get("href", "") if node.name == "a" else ""
            if not href:
                a = node.select_one("a")
                if a:
                    href = a.get("href", "")
            if not href:
                continue

            item_url = urljoin(self.BASE + "/", href)
            if item_url in seen:
                continue
            seen.add(item_url)

            publish_date = ""
            time_el = node.select_one(".centerTime span") or node.select_one(".centerTime")
            if time_el:
                m = _DATE_RE.search(time_el.get_text())
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
        title_el = soup.select_one("div.detailTitle span") or soup.select_one("div.detailTitle")
        if title_el:
            title = title_el.get_text(strip=True)
        elif soup.title:
            title = soup.title.get_text(strip=True)

        # 正文
        content_el = soup.select_one("div.detailMessage")
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

        # 发布时间：在详情页 .detailTime 或类似位置
        publish_date = ""
        time_el = soup.select_one(".detailTime span") or soup.select_one(".detailTime")
        if not time_el:
            # 回退：从正文区域搜索日期
            for cand in soup.select("div.detailMessage *, .centerTime"):
                m = _DATE_RE.search(cand.get_text())
                if m:
                    publish_date = m.group(1)
                    break
        else:
            m = _DATE_RE.search(time_el.get_text())
            if m:
                publish_date = m.group(1)

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
        )
