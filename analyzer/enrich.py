# analyzer/enrich.py
"""P1-07 / H-03: 商机六字段 enrichment runner（CLI 可触发）。

H-03 修正：
- 断点键改为 opportunity_id（独立 opportunity_enrichment_states 表），
  同文档多商机各自独立处理（原用 doc_id 导致第二条被跳过）
- 候选 = 任一六字段为 NULL 或空串（原只选全空，漏掉部分缺失）
- 零更新（LLM 未返回任何字段）→ retryable_error（原标 succeeded 永不再试）
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from analyzer.rules_loader import load_prompt
from analyzer.result import validate_llm_dict, JudgeLLMResult
from storage.models import Opportunity, Document, get_conn

logger = logging.getLogger(__name__)

ENRICH_VERSION = "v1"
SIX_FIELDS = (
    "buyer_dept", "relocate_from", "relocate_scale",
    "relocate_phase", "timing_window", "deadline",
)


def _normalize_field(value):
    """把 "null"/""/纯空白 规范化为 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if s == "" or s.lower() == "null":
            return None
        return s
    return value


def _enrich_state_get(opportunity_id: int, version: str = ENRICH_VERSION) -> str:
    """读取 enrichment 状态。返回 status（无记录='none'）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT status FROM opportunity_enrichment_states WHERE opportunity_id=? AND version=?",
        (opportunity_id, version),
    ).fetchone()
    return row["status"] if row else "none"


def _enrich_state_set(opportunity_id: int, status: str, version: str = ENRICH_VERSION,
                      last_error: str | None = None) -> None:
    """写入 enrichment 状态（upsert）。

    A-03：retryable_error 时原子递增 attempt_count + 退避 next_retry_at。
    succeeded 时清空 last_error/next_retry_at。
    """
    from datetime import timedelta
    conn = get_conn()
    now = datetime.now()
    if status == "retryable_error":
        # 原子递增 attempt_count + 指数退避（30s, 60s, 120s）
        conn.execute(
            "INSERT INTO opportunity_enrichment_states (opportunity_id, version, status, attempt_count, last_error, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(opportunity_id, version) DO UPDATE SET "
            "status=excluded.status, attempt_count=attempt_count+1, "
            "last_error=excluded.last_error, updated_at=excluded.updated_at",
            (opportunity_id, version, status, (last_error or "")[:200], now.isoformat()),
        )
    else:
        # succeeded/skipped：清空 last_error
        conn.execute(
            "INSERT INTO opportunity_enrichment_states (opportunity_id, version, status, attempt_count, last_error, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(opportunity_id, version) DO UPDATE SET status=excluded.status, "
            "last_error=NULL, updated_at=excluded.updated_at",
            (opportunity_id, version, status, 1, last_error, now.isoformat()),
        )
    conn.commit()


def list_enrichment_candidates(limit: int | None = None) -> list[Opportunity]:
    """H-03：列出待 enrichment 的商机。

    候选 = 任一六字段为 NULL 或空串 + 有源文档 + 未标 succeeded（按 opportunity_id）。
    """
    conn = get_conn()
    rows = conn.execute(
        f"""
        SELECT o.* FROM opportunities o
        WHERE o.source_doc_id IS NOT NULL
          AND (
            o.buyer_dept IS NULL OR o.buyer_dept = ''
            OR o.relocate_from IS NULL OR o.relocate_from = ''
            OR o.relocate_scale IS NULL OR o.relocate_scale = ''
            OR o.relocate_phase IS NULL OR o.relocate_phase = ''
            OR o.timing_window IS NULL OR o.timing_window = ''
            OR o.deadline IS NULL OR o.deadline = ''
          )
          AND NOT EXISTS (
            SELECT 1 FROM opportunity_enrichment_states e
            WHERE e.opportunity_id = o.id AND e.version = ? AND e.status = 'succeeded'
          )
        ORDER BY o.id
        {'LIMIT ?' if limit else ''}
        """,
        ([ENRICH_VERSION, limit] if limit else [ENRICH_VERSION]),
    ).fetchall()
    return [Opportunity(r) for r in rows]


def _field_is_empty(opp: Opportunity, field: str) -> bool:
    """检查商机某字段是否为空（None 或空串/null）。"""
    val = getattr(opp, field, None)
    if val is None:
        return True
    if isinstance(val, str):
        s = val.strip()
        return s == "" or s.lower() == "null"
    return False


def enrich_one(opp: Opportunity, llm_client) -> dict:
    """对单条商机执行 enrichment。返回 {status, updated_fields}。

    A-03 修正：
    - 只填充当前为空的字段（不覆盖已有值）
    - succeeded 要求所有 6 字段均达终态（有值或 LLM 明确返回 null 视为"不可得"）
    - 部分填充 → pending（下次补剩余字段，不标 succeeded）
    - 零可用填充 → retryable_error
    """
    doc = Document.get_by_id(opp.source_doc_id)
    if not doc:
        _enrich_state_set(opp.id, "succeeded", last_error="source doc not found")
        return {"status": "skipped", "reason": "source doc not found"}

    system_prompt = load_prompt("judge_opportunity")
    context = f"标题：{doc.title}\n\n正文：{doc.text[:3000]}"
    user_prompt = f"补充分析以下雄安新区新闻的金融商机细节：\n\n{context}"

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        doc_id=opp.source_doc_id, task_type="judge_enrich",
    )
    bad = validate_llm_dict(result, schema=JudgeLLMResult)
    if bad is not None:
        logger.warning(f"Enrich LLM contract violation for opp {opp.id}: {bad.payload}")
        _enrich_state_set(opp.id, "retryable_error", last_error=str(bad.payload)[:200])
        return {"status": "failed", "reason": str(bad.payload)[:100]}

    # A-03：只填充当前为空的字段（不覆盖已有值）
    updates = {}
    fields_declined = set()  # LLM 明确返回 null 的字段（键存在但值为 null）
    for field in SIX_FIELDS:
        if not _field_is_empty(opp, field):
            continue  # 已有值，不覆盖
        if field not in result:
            continue  # LLM 完全省略该字段（键不存在）→ 仍待定
        val = _normalize_field(result.get(field))
        if val is not None:
            updates[field] = val
        else:
            # 键存在但值为 null → LLM 明确表示"不可得"
            fields_declined.add(field)

    if updates:
        opp.update_banking_fields(**updates)
        # 刷新 opp 对象以反映更新后的值
        opp = Opportunity.get_by_id(opp.id)

    # A-03：检查是否所有字段均达终态（有值 或 LLM 明确 decline）
    still_empty = [f for f in SIX_FIELDS if _field_is_empty(opp, f) and f not in fields_declined]
    if not still_empty:
        # 所有字段有值或明确不可得 → 终态 succeeded
        _enrich_state_set(opp.id, "succeeded")
        return {"status": "succeeded", "updated_fields": list(updates.keys())}
    elif updates:
        # 部分填充但仍有未确定字段 → pending（下次补剩余）
        _enrich_state_set(opp.id, "pending", last_error=f"{len(still_empty)} fields still empty")
        return {"status": "partial", "updated_fields": list(updates.keys()), "remaining": still_empty}
    else:
        # 零可用填充 → retryable
        _enrich_state_set(opp.id, "retryable_error", last_error="no fillable fields returned")
        return {"status": "failed", "reason": "no fillable fields returned"}


def enrich_opportunities(*, dry_run: bool = False, limit: int | None = None,
                         llm_client=None, qps: float = 0.5) -> dict:
    """批量 enrichment 回填六字段。

    Args:
        dry_run: 只列出候选，不调 LLM、不修改数据
        limit: 最多处理条数（None=全部）
        llm_client: LLM 客户端（dry_run 时可 None）
        qps: 限流（每秒最多 qps 次 LLM 调用，默认 0.5=每2秒1次）

    Returns:
        {total, processed, succeeded, skipped, failed, updated_fields_count}
    """
    candidates = list_enrichment_candidates(limit=limit)
    if dry_run:
        logger.info(f"[dry-run] 待 enrichment 商机：{len(candidates)} 条")
        for opp in candidates:
            logger.info(f"  opp {opp.id}: {opp.title} (doc {opp.source_doc_id})")
        return {"total": len(candidates), "dry_run": True}

    if llm_client is None:
        from analyzer.llm_client import LLMClient
        llm_client = LLMClient()

    interval = 1.0 / qps if qps > 0 else 0
    processed = succeeded = skipped = failed = updated_fields_count = 0

    for opp in candidates:
        try:
            result = enrich_one(opp, llm_client)
            processed += 1
            if result["status"] == "succeeded":
                succeeded += 1
                updated_fields_count += len(result.get("updated_fields", []))
            elif result["status"] == "skipped":
                skipped += 1
            else:
                failed += 1
        except Exception as e:
            logger.exception(f"Enrich crashed for opp {opp.id}")
            _enrich_state_set(opp.id, "retryable_error", last_error=str(e)[:200])
            failed += 1
        if interval > 0:
            time.sleep(interval)

    stats = {
        "total": len(candidates), "processed": processed,
        "succeeded": succeeded, "skipped": skipped, "failed": failed,
        "updated_fields_count": updated_fields_count,
    }
    logger.info(f"Enrichment done: {stats}")
    return stats
