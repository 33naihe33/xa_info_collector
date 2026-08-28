# analyzer/__main__.py
"""P1-07: enrichment runner CLI 入口。

用法：
    python -m analyzer --dry-run          # 列出待 enrichment 商机
    python -m analyzer --limit 10         # 回填前 10 条
    python -m analyzer                    # 回填全部
"""
import argparse
import logging
import sys

from storage.models import init_db, close_db


def main():
    parser = argparse.ArgumentParser(description="商机六字段 enrichment 回填")
    parser.add_argument("--dry-run", action="store_true", help="只列出候选，不调 LLM")
    parser.add_argument("--limit", type=int, default=None, help="最多处理条数")
    parser.add_argument("--qps", type=float, default=0.5, help="LLM 限流（每秒调用数）")
    parser.add_argument("--db", default=None, help="数据库路径（默认从 XA_DATA_DIR 派生）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # H-01/A-02: 显式加载 .env（XA_DATA_DIR + API key）早于 init_db
    from analyzer.env import load_env, require_api_key
    load_env()
    if not args.dry_run:
        require_api_key()

    init_db(args.db)  # None → 从 storage.paths.db_path() 派生
    try:
        from analyzer.enrich import enrich_opportunities
        stats = enrich_opportunities(
            dry_run=args.dry_run, limit=args.limit, qps=args.qps,
        )
        print(stats)
    finally:
        close_db()


if __name__ == "__main__":
    sys.exit(main())
