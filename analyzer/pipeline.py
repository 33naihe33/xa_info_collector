# analyzer/pipeline.py
"""分析 pipeline 编排：预筛 → 实体抽取 → 商机研判 → 标记已分析。"""
import logging
from datetime import datetime

from analyzer.rule_filter import should_analyze
from analyzer.entity_extractor import extract_entities
from analyzer.opportunity_judge import judge_opportunity, JudgeResult
from analyzer.leadership_extractor import extract_leadership
from storage.models import Document, AnalysisTaskState, get_conn

logger = logging.getLogger(__name__)


def _should_run_task(state: dict) -> bool:
    """R-04：判断子任务是否应执行。

    - succeeded / permanent_error：终态，不执行（幂等 + 熔断后不再自动重试）
    - pending：执行
    - retryable_error：仅当 next_retry_at 已到期（或为空）时执行
    """
    status = state["status"]
    if status in ("succeeded", "permanent_error"):
        return False
    if status == "retryable_error":
        next_retry = state.get("next_retry_at")
        if next_retry and next_retry > datetime.now().isoformat():
            return False  # 未到期，暂不重试
    return True


def analyze_document(doc: "Document", llm_client) -> dict:
    """分析单篇文档。返回 {"analyzed": bool, "has_opportunity": bool}。

    无信号文档直接标记为已分析并跳过 LLM 调用（控制成本）；
    有信号文档依次执行实体抽取与商机研判。

    每个子任务（entity/opportunity/leadership）独立记录状态到
    analysis_task_states。仅当必要子任务（entity + opportunity）全部成功时
    才把文档标记为 is_analyzed=1；存在 retryable_error 的文档不标记，以便重试。

    子任务返回 TaskResult：succeeded（含"无实体/无商机/非领导调研"的成功分类）
    或 retryable_error（LLM None/合约不合）。本函数据此记录任务状态。
    业务逻辑的编程错误向上抛出，不被标为 retryable。
    """
    # 规则预筛
    if not should_analyze(doc.text):
        _mark_analyzed(doc.id)
        doc.is_analyzed = True
        return {"analyzed": False, "has_opportunity": False, "reason": "no_signal"}

    # H-02: 崩溃恢复 reconcile——任务状态与文档标记不一致时补标
    if AnalysisTaskState.has_permanent_failure(doc.id):
        # permanent_error 未落 dead_letter（崩溃在 _mark_dead_letter 前）
        _mark_dead_letter(doc.id)
        doc.dead_letter = True
        return {"analyzed": False, "has_opportunity": False, "dead_letter": True}
    if AnalysisTaskState.all_succeeded(doc.id):
        # 三任务全 succeeded 但 is_analyzed 未落（崩溃在 _mark_analyzed 前）
        _mark_analyzed(doc.id)
        doc.is_analyzed = True
        return {"analyzed": True, "has_opportunity": False, "reason": "reconciled"}

    # 实体抽取（F-26：不再按长度跳过，统一执行；失败不阻塞后续商机研判）
    # R-04：子任务幂等 + next_retry_at 节流——_should_run_task 决定是否执行
    # P1-05：extractor 已把 LLM/合约错误转为 TaskResult（不抛异常），
    # 故 try 内的异常是真正的编程/DB 错误——记完整 traceback 后 re-raise，
    # 不再静默标 retryable（避免掩盖 bug）。
    ent_state = AnalysisTaskState.get_or_create(doc.id, "entity")
    if _should_run_task(ent_state):
        try:
            result = extract_entities(doc_id=doc.id, text=doc.text, llm_client=llm_client,
                                      publish_date=doc.publish_date or "")
            if result.succeeded:
                AnalysisTaskState.mark_succeeded(doc.id, "entity")
            else:
                AnalysisTaskState.mark_retryable(doc.id, "entity", result.payload or "entity retryable")
        except Exception:
            logger.exception(f"Entity extraction crashed for doc {doc.id} (programming error, not retryable)")
            raise

    # 商机研判
    opp = None
    opp_state = AnalysisTaskState.get_or_create(doc.id, "opportunity")
    if _should_run_task(opp_state):
        try:
            result = judge_opportunity(
                doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
                doc_title=doc.title, llm_client=llm_client,
            )
            if result.status == "succeeded":
                AnalysisTaskState.mark_succeeded(doc.id, "opportunity")
            else:
                AnalysisTaskState.mark_retryable(doc.id, "opportunity", "LLM retryable error")
            opp = result.opportunity
        except Exception:
            logger.exception(f"Opportunity judging crashed for doc {doc.id} (programming error, not retryable)")
            raise

    # 领导调研识别（独立于商机研判）
    ld_state = AnalysisTaskState.get_or_create(doc.id, "leadership")
    if _should_run_task(ld_state):
        try:
            result = extract_leadership(
                doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
                llm_client=llm_client, doc_title=doc.title,
            )
            if result.succeeded:
                AnalysisTaskState.mark_succeeded(doc.id, "leadership")
            else:
                AnalysisTaskState.mark_retryable(doc.id, "leadership", result.payload or "leadership retryable")
        except Exception:
            logger.exception(f"Leadership extraction crashed for doc {doc.id} (programming error, not retryable)")
            raise

    # 即时预警推送（推送失败不得影响分析主流程）
    if opp:
        try:
            from notifier.push_manager import send_instant_alert
            send_instant_alert(opp)
        except Exception as e:
            logger.warning(f"Push notification failed for opp {opp.id}: {e}")

    # P0-04：permanent_error = 失败。任一必要任务 permanent_error → dead_letter，不标 is_analyzed=1。
    if AnalysisTaskState.has_permanent_failure(doc.id):
        _mark_dead_letter(doc.id)
        doc.dead_letter = True
        return {"analyzed": False, "has_opportunity": opp is not None, "dead_letter": True}
    # 仅当必要子任务（entity+opportunity+leadership）全部 succeeded 时才标记已分析；
    # 存在未到期 retryable/pending 则不标记，等待下次重试。
    completed = AnalysisTaskState.all_succeeded(doc.id)
    if completed:
        _mark_analyzed(doc.id)
        doc.is_analyzed = True
    return {"analyzed": completed, "has_opportunity": opp is not None}


def analyze_pending(*, llm_client, limit: int = 50) -> dict:
    """批量分析未完成的文档。返回统计。

    P0-03 修正候选饥饿：SQL 层合并候选并按可执行性排序，避免未到期任务占名额。
    候选 = is_analyzed=0 且非 dead_letter，且满足下列之一：
    - 新文档（无任务状态行）
    - 有 pending 任务
    - 有已到期 retryable_error 任务（next_retry_at <= now 或为空）
    排除：未到期 retryable、permanent_error 文档、dead_letter 文档。
    排序：到期重试优先 > pending > 新文档；组内按发布日期降序。
    重试时 analyze_document 的 _should_run_task 跳过已 succeeded 子任务（幂等）。
    """
    conn = get_conn()
    now = datetime.now().isoformat()
    # P0-03：SQL 层构造候选集，到期判断在 WHERE 中（不在 LIMIT 后）
    # 用 MAX（任一行匹配即为 1），非 MIN（MIN 会被 succeeded 行的 0 拉低）
    rows = conn.execute(
        """
        SELECT d.* FROM documents d
        LEFT JOIN (
          SELECT doc_id,
            MAX(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS has_pending,
            MAX(CASE WHEN status='retryable_error'
                     AND (next_retry_at IS NULL OR next_retry_at <= ?) THEN 1 ELSE 0 END
            ) AS has_due_retryable,
            MAX(CASE WHEN status='permanent_error' THEN 1 ELSE 0 END) AS has_permanent,
            -- H-02: 必要任务行是否齐全（entity+opportunity+leadership 各一条）
            CASE WHEN SUM(CASE WHEN task_type IN ('entity','opportunity','leadership') THEN 1 ELSE 0 END) = 3
                 THEN 0 ELSE 1 END AS required_missing
          FROM analysis_task_states GROUP BY doc_id
        ) t ON t.doc_id = d.id
        WHERE d.is_analyzed = 0
          AND COALESCE(d.dead_letter, 0) = 0
          AND (
            t.doc_id IS NULL                                              -- 新文档
            OR COALESCE(t.has_pending, 0) = 1                            -- 有 pending
            OR COALESCE(t.has_due_retryable, 0) = 1                      -- 到期 retryable
            OR COALESCE(t.required_missing, 0) = 1                       -- H-02: 缺必要任务行
            OR COALESCE(t.has_permanent, 0) = 1                          -- H-02: permanent 未落 dead_letter
          )
        ORDER BY
          COALESCE(t.has_permanent, 0) DESC,       -- H-02: 先 reconcile permanent→dead_letter
          COALESCE(t.has_due_retryable, 0) DESC,
          COALESCE(t.has_pending, 0) DESC,
          COALESCE(t.required_missing, 0) DESC,
          d.publish_date DESC
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()

    docs = [Document(r) for r in rows]
    analyzed = 0
    skipped = 0
    opportunities = 0
    dead_lettered = 0

    for doc in docs:
        result = analyze_document(doc, llm_client=llm_client)
        if result.get("dead_letter"):
            dead_lettered += 1
        elif result["analyzed"]:
            analyzed += 1
            if result["has_opportunity"]:
                opportunities += 1
        else:
            skipped += 1

    return {
        "total": len(docs),
        "analyzed": analyzed,
        "skipped": skipped,
        "opportunities": opportunities,
        "dead_lettered": dead_lettered,
    }


def _mark_analyzed(doc_id: int):
    conn = get_conn()
    conn.execute("UPDATE documents SET is_analyzed = 1 WHERE id = ?", (doc_id,))
    conn.commit()


def _mark_dead_letter(doc_id: int):
    """P0-04：标记文档为 dead_letter（必要任务 permanent_error，需人工介入）。"""
    conn = get_conn()
    conn.execute("UPDATE documents SET dead_letter = 1 WHERE id = ?", (doc_id,))
    conn.commit()
