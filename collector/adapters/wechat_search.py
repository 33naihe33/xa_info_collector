# collector/adapters/wechat_search.py
"""微信公众号搜索 adapter（通过搜狗微信搜索间接获取）。

搜狗微信搜索（weixin.sogou.com）可以搜索公众号文章，
获取标题和摘要。由于反爬限制，无法获取完整正文，
但标题+摘要足够 LLM 分析商机。

每个公众号配置为一个 source，搜索 query 为公众号名。
"""
import re
from urllib.parse import urljoin, quote

import httpx
from bs4 import BeautifulSoup

from collector.base import BaseAdapter, ListItem, RawDoc


class WechatSearchAdapter(BaseAdapter):
    """通用微信搜索 adapter，搜索关键词在搜狗微信搜索中的文章。"""

    # 子类需要覆盖
    source_name = "wechat_search"
    SEARCH_URL = "https://weixin.sogou.com/weixin"

    def __init__(self):
        super().__init__()
        self.session = httpx.Client(
            timeout=20.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0.0.0 Safari/537.36",
            },
            follow_redirects=True,
        )

    def _get_search_query(self) -> str:
        """从配置获取搜索关键词（公众号名）。"""
        return self.config.get("search_query", self.config.get("name", "雄安"))

    def fetch_list(self, since: str | None = None) -> list[ListItem]:
        """通过搜狗微信搜索获取文章列表（标题+摘要）。"""
        query = self._get_search_query()
        params = {"type": "2", "query": query, "ie": "utf8"}
        self._throttle()
        resp = self.session.get(self.SEARCH_URL, params=params)
        resp.raise_for_status()
        resp.encoding = resp.charset_encoding or "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        seen = set()

        for box in soup.select("div.txt-box"):
            a = box.select_one("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            # 搜狗链接（无法直接获取正文，用标题做 URL 标识）
            href = a.get("href", "")
            url = urljoin("https://weixin.sogou.com", href)
            if url in seen:
                continue
            seen.add(url)

            # 摘要
            summary = ""
            p = box.select_one("p.txt-info")
            if p:
                summary = p.get_text(strip=True)[:200]

            # 日期（搜狗格式：YYYY-MM-DD 或 N天前）
            publish_date = ""
            date_el = box.select_one("span.s2")
            if date_el:
                date_text = date_el.get_text(strip=True)
                m = re.search(r"(\d{4}-\d{2}-\d{2})", date_text)
                if m:
                    publish_date = m.group(1)

            if since and publish_date and publish_date < since:
                continue

            items.append(ListItem(
                title=title,
                url=url,
                publish_date=publish_date,
                summary=summary,
            ))

        # 限制数量
        limit = self.config.get("max_results", 20)
        return items[:limit]

    def fetch_detail(self, url: str) -> RawDoc:
        """微信文章正文无法直接获取（反爬），用标题+摘要作为正文。"""
        # 搜狗链接无法直接获取微信正文，返回空正文
        # 商机研判会基于空文本，但 fetch_list 中的 summary 已有信息
        # 这里尝试跟随链接，失败则返回空
        self._throttle()
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            resp.encoding = resp.charset_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            content = soup.select_one("#js_content") or soup.select_one(".rich_media_content")
            if content:
                text = content.get_text("\n", strip=True)
            else:
                text = ""
            title = soup.title.get_text(strip=True) if soup.title else ""
        except Exception:
            text = ""
            title = ""

        return RawDoc(
            title=title,
            url=url,
            publish_date="",
            raw_html="",
            text=text,
        )


class XionganFabuAdapter(WechatSearchAdapter):
    """雄安发布公众号。"""
    source_name = "wechat_xiongan_fabu"


class RongchengFabuAdapter(WechatSearchAdapter):
    """容城发布公众号。"""
    source_name = "wechat_rongcheng_fabu"


class XiongzhouVoiceAdapter(WechatSearchAdapter):
    """雄州之声公众号（雄县）。"""
    source_name = "wechat_xiongzhou_voice"


class YanlingVoiceAdapter(WechatSearchAdapter):
    """雁翎之声公众号（安新）。"""
    source_name = "wechat_yanling_voice"


class XionganEduAdapter(WechatSearchAdapter):
    """雄安教育发布公众号。"""
    source_name = "wechat_xiongan_edu"
