"""雄县政府 (xiongxian_gov) 爬虫 adapter。

注意：
- 站点使用 HTTP 而非 HTTPS（http://www.xiongxian.gov.cn）。
- 部分页面编码为 GBK/GB2312，需做编码检测。
- 详情 URL 形如 content-173-{id}.html（无前导斜杠），需补 '/' 后拼接。

列表页：/index.do?view=ejxwzx&ccid=173（雄县要闻）
列表项：table.list tr，标题在 tr td:first-child a，日期在 tr td:last-child
详情正文：table.sj_nr td（含 <p>）
"""
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


class XiongxianAdapter(BaseAdapter):
    source_name = "xiongxian_gov"
    BASE = "http://www.xiongxian.gov.cn"
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
        # 雄县政府站可能为 GBK/GB2312；httpx 已声明 charset 时优先用，
        # 否则探测：若 utf-8 解码出现乱码标记，则回退到 gbk。
        enc = resp.charset_encoding
        if enc and enc.lower() not in ("iso-8859-1",):
            resp.encoding = enc
        else:
            # 通过 meta charset 探测
            head = resp.content[:512].lower()
            if b"charset=gb" in head:
                resp.encoding = "gb18030"
            else:
                resp.encoding = "utf-8"
        return resp

    def fetch_list(self, since: str | None = None) -> list[ListItem]:
        list_url = self.config.get("list_url") or "/index.do?view=ejxwzx&ccid=173"
        url = urljoin(self.BASE + "/", list_url)
        resp = self._get(url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        items = []
        for tr in soup.select("table.list tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            a = tds[0].select_one("a") or tr.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or not href:
                continue

            # 详情 URL 形如 content-173-{id}.html（无前导斜杠）→ 需补 '/'
            if href.startswith("http"):
                item_url = href
            else:
                if not href.startswith("/"):
                    href = "/" + href
                item_url = urljoin(self.BASE + "/", href)

            # 日期：最后一个 td
            publish_date = ""
            if tds:
                m = _DATE_RE.search(tds[-1].get_text())
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

        # 标题：优先 table.sj_bt 区域，回退 <title>
        title = ""
        bt = soup.select_one("table.sj_bt")
        if bt:
            # sj_bt 内可能有 <td>、<span> 等，取文本
            title = bt.get_text(" ", strip=True)
        if not title and soup.title:
            title = soup.title.get_text(strip=True)

        # 正文：table.sj_nr td
        content_el = soup.select_one("table.sj_nr td")
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

        # 日期：尝试从页面文本中正则匹配
        publish_date = ""
        m = _DATE_RE.search(html)
        if m:
            publish_date = m.group(1)

        return RawDoc(
            title=title,
            url=url,
            publish_date=publish_date,
            raw_html=html,
            text=text,
        )
