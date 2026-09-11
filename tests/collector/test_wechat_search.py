from datetime import date

import respx

from collector.adapters.wechat_search import XionganFabuAdapter, _parse_publish_date
from storage.models import close_db, init_db


def setup_function():
    init_db(":memory:")


def teardown_function():
    close_db()


def test_parse_publish_date_supports_absolute_and_relative_dates():
    today = date(2026, 9, 11)

    assert _parse_publish_date("2026-09-09", today) == "2026-09-09"
    assert _parse_publish_date("昨天", today) == "2026-09-10"
    assert _parse_publish_date("3天前", today) == "2026-09-08"


@respx.mock
def test_fetch_list_since_skips_undated_and_old_items():
    respx.get("https://weixin.sogou.com/weixin").respond(
        text="""
        <div class="txt-box"><a href="/new">范围内文章</a><span class="s2">2026-09-09</span></div>
        <div class="txt-box"><a href="/old">过期文章</a><span class="s2">2026-09-04</span></div>
        <div class="txt-box"><a href="/undated">无日期文章</a><span class="s2">来源未知</span></div>
        """
    )

    items = XionganFabuAdapter().fetch_list(since="2026-09-05")

    assert [item.publish_date for item in items] == ["2026-09-09"]
