# analyzer/opportunity_judge.py
"""商机研判：调用 LLM 判断文档是否含金融商机，写入 opportunities 表。"""
import json
import logging
from dataclasses import dataclass

from analyzer.rules_loader import load_prompt
from analyzer.result import validate_llm_dict, JudgeLLMResult
from storage.models import Opportunity

logger = logging.getLogger(__name__)

# F-29：六字段规范化——LLM 可能返回 "null"/空串/纯空白，统一为 None
_BANKING_FIELDS = (
    "buyer_dept", "relocate_from", "relocate_scale",
    "relocate_phase", "timing_window", "deadline",
)


def _normalize_field(value):
    """把 "null"/""/纯空白 规范化为 None，其他原样返回。"""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if s == "" or s.lower() == "null":
            return None
        return s
    return value


@dataclass
class JudgeResult:
    status: str  # "succeeded" | "retryable_error"
    opportunity: "Opportunity | None"  # None = no opportunity or error


def judge_opportunity(*, doc_id: int, text: str, publish_date: str,
                      llm_client, doc_title: str = "") -> JudgeResult:
    """判断文档是否含商机。

    返回 JudgeResult：
    - status="retryable_error" 当 LLM 调用失败（返回 None）
    - status="succeeded" 当 LLM 正常返回；opportunity 字段为 Opportunity 或 None
      （无商机或与已有商机重复时 opportunity=None）
    """
    system_prompt = load_prompt("judge_opportunity")
    context = f"标题：{doc_title}\n\n正文：{text[:3000]}"
    user_prompt = f"分析以下雄安新区新闻的金融商机：\n\n{context}"

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        doc_id=doc_id, task_type="judge_opportunity",
    )
    # P1-05：字段级 schema 校验（None / 非 dict / 缺 is_opportunity → retryable）
    bad = validate_llm_dict(result, schema=JudgeLLMResult)
    if bad is not None:
        logger.warning(f"Opportunity judge contract violation for doc {doc_id}: {bad.payload}")
        return JudgeResult("retryable_error", None)

    if not result.get("is_opportunity", False):
        return JudgeResult("succeeded", None)

    # 构建 Opportunity
    fin_products = result.get("fin_products", [])
    title = result.get("trigger_event") or doc_title or "未命名商机"

    # 规范化 business_line：LLM 可能返回 "corporate|inclusive" 多值组合，
    # 取第一个有效值作为主条线（设计要求每条商机归属单一业务条线）
    raw_line = result.get("business_line") or "corporate"
    business_line = raw_line.split("|")[0].strip()
    valid_lines = {
        "corporate", "retail", "operations", "fintech", "synergy", "risk_control",
    }
    if business_line not in valid_lines:
        business_line = "corporate"

    # 去重：检查同一文档是否已产出相同条线商机，或标题高度相似
    from storage.database import get_conn
    conn = get_conn()
    # 同文档同条线已有商机 → 跳过（避免一篇文章在同条线产生重复商机）
    existing = conn.execute(
        "SELECT id FROM opportunities WHERE source_doc_id = ? AND business_line = ? LIMIT 1",
        (doc_id, business_line),
    ).fetchone()
    if existing:
        logger.info(f"Skipping duplicate opportunity for doc {doc_id} line {business_line}")
        return JudgeResult("succeeded", None)

    # 跨文档标题相似度去重：同一条线下标题前20字相同 → 跳过
    title_prefix = title[:20]
    similar = conn.execute(
        "SELECT id FROM opportunities WHERE business_line = ? AND substr(title, 1, 20) = ? LIMIT 1",
        (business_line, title_prefix),
    ).fetchone()
    if similar:
        logger.info(f"Skipping similar opportunity: '{title[:30]}' matches existing")
        return JudgeResult("succeeded", None)

    opp = Opportunity.create(
        title=title[:200],
        source_doc_id=doc_id,
        business_line=business_line,
        opp_type=result.get("opp_type", ""),
        fin_scale=result.get("fin_scale"),
        fin_products=json.dumps(fin_products, ensure_ascii=False) if fin_products else "[]",
        target_client=_normalize_field(result.get("target_client")),
        # F-29：六大银行业字段（写库前规范化 "null"/""/空白 → None）
        buyer_dept=_normalize_field(result.get("buyer_dept")),
        relocate_from=_normalize_field(result.get("relocate_from")),
        relocate_scale=_normalize_field(result.get("relocate_scale")),
        relocate_phase=_normalize_field(result.get("relocate_phase")),
        timing_window=_normalize_field(result.get("timing_window")),
        deadline=_normalize_field(result.get("deadline")),
        insight=result.get("insight"),
        action_suggest=result.get("action_suggest"),
        priority=result.get("priority", "medium"),
        status="signal",
        publish_date=publish_date,
        trigger_event=result.get("trigger_event"),
    )
    logger.info(f"Created opportunity {opp.id}: {opp.title} ({opp.business_line}/{opp.priority})")
    return JudgeResult("succeeded", opp)
