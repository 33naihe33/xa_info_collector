"""人民雄安网 (rmxiongan) 爬虫 adapter。

列表页为静态 HTML（无 JSON API），通过 BeautifulSoup 解析。
列表选择器：div.pageContent dl.clearfix，标题在 dl > h3 > a，
详情正文：div#rm_txt_zw，发布时间：b#newstime（格式 2026年07月13日10:34）。
"""
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc

# 匹配 "2026年07月13日10:34" 形式的中文日期
_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


class RmxionganAdapter(BaseAdapter):
    source_name = "rmxiongan"
    BASE = "http://www.rmxiongan.com"
    INITIAL_BATCH = 20  # 首次全量最多抓取条目数

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
        # rmxiongan 使用 UTF-8
        resp.encoding = resp.charset_encoding or "utf-8"
        return resp

    def fetch_list(self, since: str | None = None) -> list[ListItem]:
        """解析列表页静态 HTML，返回 (title, url, date) 三元组。

        增量策略：
        - since 指定时只返回 since 之后（>=）的条目
        - since 为 None（首次全量）时限制最多 INITIAL_BATCH 条
        """
        list_url = self.config.get("list_url") or "/GB/383581/index.html"
        url = urljoin(self.BASE + "/", list_url)
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        items = []
        for dl in soup.select("div.pageContent dl.clearfix"):
            a = dl.select_one("h3 a") or dl.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not href:
                continue
            item_url = urljoin(self.BASE + "/", href)

            # 解析发布日期（部分条目没有时间，置空）
            publish_date = ""
            time_el = dl.select_one("b#newstime") or dl.select_one("b")
            if time_el:
                m = _DATE_RE.search(time_el.get_text())
                if m:
                    publish_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

            if since and publish_date and publish_date < since:
                continue

            items.append(ListItem(
                title=title,
                url=item_url,
                publish_date=publish_date,
            ))

        # 首次全量时限制批量大小
        if since is None:
            items = items[: self.INITIAL_BATCH]

        return items

    def fetch_detail(self, url: str) -> RawDoc:
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        # 标题：优先 <title>，剥掉站点后缀
        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)
            # 去掉形如 "标题--人民雄安网" 的站点后缀
            for sep in ["--", "—", "-", "_人民雄安网"]:
                if sep in title:
                    title = title.split(sep)[0].strip()
                    break

        # 正文：div#rm_txt_zw 内 <p>
        content_el = soup.select_one("#rm_txt_zw") or soup.select_one("div#rm_txt_zw")
        if content_el:
            paragraphs = content_el.find_all("p")
            if not paragraphs:
                # 没有段落标签时取整体文本
                text = content_el.get_text("\n", strip=True)
            else:
                text = "\n".join(
                    p.get_text(strip=True).replace("\u3003", "").replace("\u3000", "")
                    for p in paragraphs
                )
        else:
            text = ""

        # 发布时间：b#newstime → 2026年07月13日10:34
        publish_date = ""
        time_el = soup.select_one("b#newstime")
        if time_el:
            m = _DATE_RE.search(time_el.get_text())
            if m:
                publish_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # meta description 作为 summary
        summary = ""
        meta_desc = soup.select_one('meta[name="description"]')
        if meta_desc:
            summary = meta_desc.get("content", "")

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
            summary=summary,
        )
