"""一次性脚本：补齐雄安官网指定标题在日期范围内缺失的文档。

用法：python scripts/fix_missing_portal.py
"""
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
from analyzer.env import load_env
load_env()
from storage.models import init_db
from collector.adapters.xiongan_portal import XionganPortalAdapter
from collector.base import ListItem

TARGETS = [
    "从塞罕坝到千年秀林：一场跨越时空的绿色接力",
    "张国华与紫荆文化集团有限公司党委书记、董事长许正中一行举行工作座谈",
    "第二届健康传播生态共创大会暨“生命微光”中国医师节特别致敬活动在雄安新区举行",
    "纵览视评｜“雄安一号”飞向太空，一座新城向上生长",
    "雄安新区开展志愿服务进工地慰问活动",
    "雄安电网“哨兵”智慧守护汛期供电安全",
]


def main():
    init_db()
    adapter = XionganPortalAdapter()
    cat_cfg = adapter.config["categories"]["zxyw"]
    json_url = adapter.BASE + cat_cfg["datasource_path"]
    data = adapter._get(json_url).json()
    publish_domain = data.get("publishDomain", adapter.BASE)
    found = 0
    for entry in data.get("datasource", []):
        if entry.get("title") not in TARGETS:
            continue
        from urllib.parse import urljoin
        raw_url = entry.get("publishUrl", "")
        url = urljoin(adapter.BASE + cat_cfg["list_url"], raw_url)
        pub = (entry.get("publishTime") or "")[:10]
        item = ListItem(title=entry.get("title", ""), url=url,
                        publish_date=pub, summary=entry.get("summary", ""))
        try:
            result = adapter._ingest_detail(item, category="zxyw")
            print(f"[{result.kind}] {pub} {entry.get('title')} id={result.doc_id}")
            found += 1
        except Exception as e:
            print(f"[ERROR] {entry.get('title')}: {e}")
    print(f"处理完成: {found}/6")


if __name__ == "__main__":
    main()