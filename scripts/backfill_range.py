"""一次性脚本：按日期范围回填爬取全部启用的数据源。

用法：python scripts/backfill_range.py 2026-08-15
抓取自该日期至今（含）的所有内容，重新跑是幂等安全的（有去重）。
"""
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

from analyzer.env import load_env
load_env()

from storage.models import init_db, close_db
from collector.config import load_sources_config
from web.api.collect import _build_adapter


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else "2026-08-15"
    init_db()  # None → 从 storage.paths.db_path() 派生
    sources = load_sources_config()
    total_new = 0
    total_errors = 0
    for source_name, cfg in sources.items():
        if not cfg.get("enabled"):
            continue
        try:
            adapter = _build_adapter(source_name)
            result = adapter.run(since=since)
            new = result.get("new", 0)
            errors = result.get("errors", 0)
            total_new += new
            total_errors += errors
            print(f"[{source_name}] new={new} errors={errors} run_id={result.get('run_id')}")
        except Exception as e:
            total_errors += 1
            print(f"[{source_name}] FAILED: {e}")

    print(f"\nDONE since={since} total_new={total_new} errors={total_errors}")


if __name__ == "__main__":
    main()