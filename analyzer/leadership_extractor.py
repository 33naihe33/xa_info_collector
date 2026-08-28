# analyzer/leadership_extractor.py
"""领导调研识别：调用 LLM 判断文档是否关于领导调研雄安，写入 leadership_visits 表。"""
import json
import logging

from analyzer.result import TaskResult, validate_llm_dict, LeadershipLLMResult, ok, retryable_error
from analyzer.rules_loader import load_prompt
from storage.models import LeadershipVisit, Document

logger = logging.getLogger(__name__)


def extract_leadership(*, doc_id: int, text: str, publish_date: str,
                       llm_client, doc_title: str = "") -> TaskResult:
    """判断文档是否关于重要领导调研雄安。

    返回 TaskResult：
    - retryable_error：LLM 返回 None / 非 dict（输出合约不合）
    - ok(None)：成功分类为"非领导调研"或重复/跳过（不入库）
    - ok(visit)：成功创建 LeadershipVisit
    """
    system_prompt = load_prompt("extract_leadership")
    # 发布日期必须随上下文传给模型：当正文只写“近日”或缺少年份时，
    # 模型才能按提示回填当期日期，而非臆造历史年份。
    context = f"标题：{doc_title}\n发布日期：{publish_date}\n\n正文：{text[:3000]}"
    user_prompt = f"分析以下雄安新区新闻是否关于领导调研：\n\n{context}"

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        doc_id=doc_id, task_type="extract_leadership",
    )
    # 形状校验：None / 非 dict / 缺 is_leadership_visit → retryable_error（P1-05）
    bad = validate_llm_dict(result, schema=LeadershipLLMResult)
    if bad is not None:
        logger.warning(f"Leadership extraction contract violation for doc {doc_id}: {bad.payload}")
        return bad

    if not result.get("is_leadership_visit", False):
        return ok(None)  # 成功判定：非领导调研

    leader_name = (result.get("leader_name") or "").strip()
    if not leader_name:
        logger.info(f"Leadership visit missing leader_name for doc {doc_id}, skipping")
        return ok(None)

    # 去重：同一文档同一领导已有调研记录则跳过
    from storage.database import get_conn
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM leadership_visits WHERE source_doc_id = ? AND leader_name = ? LIMIT 1",
        (doc_id, leader_name),
    ).fetchone()
    if existing:
        logger.info(f"Skipping duplicate leadership visit for doc {doc_id} leader {leader_name}")
        return ok(None)

    # 查找源文档的图片 URL 列表
    images_json = "[]"
    if doc_id:
        doc = Document.get_by_id(doc_id)
        if doc and doc.images:
            images_json = doc.images if isinstance(doc.images, str) else json.dumps(
                doc.images, ensure_ascii=False)

    visited_entities = result.get("visited_entities") or []
    if not isinstance(visited_entities, list):
        visited_entities = []
    visited_entities = [str(e).strip() for e in visited_entities if str(e).strip()]

    # 调研日期校验：严格解析日期，校验与发布日期的合理范围
    # 规则：
    # 1. 必须是有效的 YYYY-MM-DD 日期（拒绝 2026-02-30 等无效日期 → 不收录）
    # 2. 年份在发布日期前后1年内（允许跨年）
    # 3. 调研日期与发布日期相差超过7天 → 视为回顾性报道，不收录
    from datetime import datetime
    raw_visit_date = result.get("visit_date") or ""
    visit_date = publish_date  # 默认用发布日期
    skip = False

    if raw_visit_date and raw_visit_date.strip() not in ("", "null"):
        raw_visit_date = raw_visit_date.strip()
        # R-08：ValueError 只包住 visit_date 的 strptime（无效日期 → skip，不收录）
        try:
            v_dt = datetime.strptime(raw_visit_date, "%Y-%m-%d")
        except ValueError:
            # datetime.strptime 失败 = 无效日期（如 2026-02-30）→ 不收录
            logger.info(f"Invalid visit_date '{raw_visit_date}' for doc {doc_id}, skipping")
            skip = True
            v_dt = None
        if v_dt is not None and not skip:
            # 严格解析成功，校验年份范围（基于发布日期动态计算）
            if publish_date:
                try:
                    p_year = datetime.strptime(publish_date[:10], "%Y-%m-%d").year
                    if not (p_year - 1 <= v_dt.year <= p_year + 1):
                        logger.info(f"Leadership visit_date year {v_dt.year} too far from publish year {p_year}, skipping")
                        skip = True
                except (ValueError, TypeError):
                    pass  # 发布日期解析失败，跳过年份检查
            # 检查调研日期与发布日期的间隔（超过7天视为回顾性报道）
            if not skip and publish_date:
                try:
                    p_dt = datetime.strptime(publish_date[:10], "%Y-%m-%d")
                    diff = abs((v_dt - p_dt).days)
                    if diff > 7:
                        logger.info(
                            f"Leadership visit_date {raw_visit_date} is {diff} days from publish_date {publish_date}, "
                            f"likely retrospective article, skipping"
                        )
                        skip = True
                    else:
                        visit_date = raw_visit_date
                except (ValueError, TypeError):
                    visit_date = raw_visit_date
            elif not skip:
                visit_date = raw_visit_date

    if skip:
        logger.info(f"Skipping leadership visit for doc {doc_id}: retrospective or invalid date")
        return ok(None)

    visit = LeadershipVisit.create(
        source_doc_id=doc_id,
        leader_name=leader_name[:100],
        leader_title=result.get("leader_title"),
        visit_date=visit_date,
        visit_topic=result.get("visit_topic"),
        visited_entities=json.dumps(visited_entities, ensure_ascii=False),
        summary=result.get("summary"),
        priority=result.get("priority", "medium"),
        publish_date=publish_date,
        images=images_json,
    )
    logger.info(
        f"Created leadership_visit {visit.id}: {visit.leader_name} "
        f"({visit.priority}) - {visit.visit_topic}"
    )
    return ok(visit)
