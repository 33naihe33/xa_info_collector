"""报告生成器：汇总指定时段商机，调 LLM 生成结构化报告内容。"""
import json
import logging

from analyzer.rules_loader import load_prompt
from storage.models import Document, Opportunity, LeadershipVisit, image_url_for_api

logger = logging.getLogger(__name__)

LINE_LABELS = {
    "corporate": "对公+跨境+普惠（企业端）",
    "retail": "对私（个人金融）",
    "operations": "营运+数币（运营服务）",
    "fintech": "金融科技",
    "synergy": "综合条线",
    "risk_control": "风控条线",
}


def generate_report(*, report_type: str, period_start: str, period_end: str,
                    llm_client, business_lines: list[str] | None = None) -> dict:
    """生成报告内容。返回结构化 dict。

    - report_type: daily / weekly / monthly
    - period_start, period_end: YYYY-MM-DD
    - llm_client: 拥有 chat_json(system, user, task_type) 方法的客户端
    - business_lines: 可选，按业务条线过滤
    """
    # 查询时段内商机（SQL层日期+条线过滤，无截断）
    opps = Opportunity.list_for_period(
        date_from=period_start, date_to=period_end,
        business_lines=business_lines,
    )

    # 查询领导调研（在判定空报告之前查询）
    # F-12：用 list_for_period 避免 limit=200 截断大量调研记录
    lv_visits = LeadershipVisit.list_for_publish_period(
        publish_date_from=period_start, publish_date_to=period_end
    )

    # 只有商机和领导调研都为空时才返回空报告
    if not opps and not lv_visits:
        return {
            "title": f"雄安新区金融业务机会{report_type}（{period_start} ~ {period_end}）",
            "summary": "本期无新增商机线索。",
            "sections": [],
            "recommendations": "",
            "stats": {"total": 0},
            "opportunity_count": 0,
        }

    # 直接用商机数据构建报告结构（不调 LLM，避免超时）
    # 商机研判阶段已产出 action，这里直接组装
    from collections import OrderedDict
    sections_map = OrderedDict()
    priority_count = {}
    for o in opps:
        line_label = LINE_LABELS.get(o.business_line, o.business_line)
        if line_label not in sections_map:
            sections_map[line_label] = []
        # 查找信息来源文档的 URL 和来源名
        source_url = ""
        source_name = ""
        images = []
        if o.source_doc_id:
            doc = Document.get_by_id(o.source_doc_id)
            if doc:
                source_url = doc.url or ""
                source_name = doc.source or ""
                try:
                    raw_images = json.loads(doc.images) if doc.images else []
                except (json.JSONDecodeError, TypeError):
                    raw_images = []
                # F-14：本地路径转 /images/... API URL（exporter 反向解析回本地）
                images = [image_url_for_api(p) for p in raw_images if p]
        sections_map[line_label].append({
            "title": o.title,
            "priority": o.priority,
            "source_url": source_url,
            "source_name": source_name,
            "publish_date": o.publish_date,
            "images": images,
        })
        priority_count[o.priority] = priority_count.get(o.priority, 0) + 1

    sections = [
        {"line": label, "opportunities": opps_list}
        for label, opps_list in sections_map.items()
    ]

    # 领导调研信息作为第一个章节（新闻线索重点）
    # lv_visits 已在上方查询，移除了 limit=20 截断
    if lv_visits:
        leadership_opps = []
        for lv in lv_visits:
            source_url, source_name, images = "", "", []
            if lv.source_doc_id:
                doc = Document.get_by_id(lv.source_doc_id)
                if doc:
                    source_url = doc.url or ""
                    source_name = doc.source or ""
                    try:
                        raw_images = json.loads(doc.images) if doc.images else []
                    except (json.JSONDecodeError, TypeError):
                        raw_images = []
                    # P1-08：与商机章节对齐，本地路径转 /images/... API URL
                    images = [image_url_for_api(p) for p in raw_images if p]
            leadership_opps.append({
                "title": f"{lv.leader_name}（{lv.leader_title or ''}）调研：{lv.visit_topic or ''}",
                "summary": lv.summary or "",
                "priority": lv.priority,
                "publish_date": lv.publish_date or lv.visit_date or "",
                "visit_date": lv.visit_date or "",
                "source_url": source_url,
                "source_name": source_name,
                "images": images,
            })
        sections.insert(0, {"line": "领导调研", "opportunities": leadership_opps})

    # 只对 high/critical 商机调 LLM 生成重点关注建议
    recommendations = ""
    top_opps = [o for o in opps if o.priority in ("high", "critical")][:8]
    if top_opps and llm_client:
        top_text = "\n".join(f"- {o.title}" for o in top_opps)
        rec_result = llm_client.chat_json(
            system="你是银行分行行长的情报分析助手。根据高优先级商机列表，给出3-5条重点关注建议。"
                   "每条建议要具体、可操作。以JSON返回：{\"recommendations\": \"建议文本（用换行分隔每条）\"}",
            user=f"以下是本期高优先级商机，请给出重点关注建议：\n{top_text}",
            task_type="generate_recommendations",
        )
        if rec_result and isinstance(rec_result, dict):
            rec = rec_result.get("recommendations", "")
            if isinstance(rec, list):
                recommendations = "\n".join(f"{i+1}. {r}" for i, r in enumerate(rec))
            elif isinstance(rec, str):
                recommendations = rec

    if not recommendations:
        # fallback：列出全部高优先级商机标题
        lines = [f"{i+1}. {o.title}" for i, o in enumerate(top_opps)]
        recommendations = "建议重点关注以下商机：\n" + "\n".join(lines) if top_opps else "本期无高优先级商机。"

    lv_count = len(lv_visits)
    summary = f"本期共监测到 {len(opps)} 条商机线索"
    if lv_count:
        summary += f"，{lv_count} 条领导调研信息"
    summary += (f"，覆盖 {len(sections)} 个板块。"
                + (f"其中高优先级 {priority_count.get('high', 0) + priority_count.get('critical', 0)} 条。" if priority_count else ""))

    result = {
        "title": f"雄安新区金融业务机会{report_type}（{period_start} ~ {period_end}）",
        "summary": summary,
        "sections": sections,
        "recommendations": recommendations,
        "stats": {"total": len(opps), "by_priority": priority_count},
    }

    result["opportunity_count"] = len(opps)
    return result


def generate_line_briefs(*, period_start: str, period_end: str,
                         llm_client=None) -> list[dict]:
    """生成各条线的新闻线索列表预览。

    返回 [{"line": "corporate", "label": "对公业务", "count": 3,
           "items": [{"title": "京雄快线...", "clue": "【新闻线索】京雄快线开通..."},
                     {"title": "...", "clue": "【新闻线索】..."}]}, ...]

    每条线逐条列出商机作为新闻线索（不调 LLM，直接用商机标题+摘要生成）。
    """
    # 查询时段内商机（SQL层日期过滤，无截断）
    opps = Opportunity.list_for_period(
        date_from=period_start, date_to=period_end,
    )

    # 按条线分组
    line_opps: dict[str, list] = {}
    for o in opps:
        line_opps.setdefault(o.business_line, []).append(o)

    # 为每个有条线商机的条线生成新闻线索列表
    briefs = []
    for line_key, line_opps_list in line_opps.items():
        label = LINE_LABELS.get(line_key, line_key)

        # 逐条生成新闻线索（全部列出）
        items = []
        for o in line_opps_list:
            # 用商机标题作为新闻线索（不再附带 insight）
            clue_text = o.title
            # 查找信息来源文档的 URL 和来源名
            source_url = ""
            source_name = ""
            if o.source_doc_id:
                doc = Document.get_by_id(o.source_doc_id)
                if doc:
                    source_url = doc.url or ""
                    source_name = doc.source or ""
            items.append({
                "title": o.title,
                "clue": f"【新闻线索】{clue_text}",
                "priority": o.priority,
                "publish_date": o.publish_date,
                "source_url": source_url,
                "source_name": source_name,
            })

        briefs.append({
            "line": line_key,
            "label": label,
            "count": len(line_opps_list),
            "items": items,
        })

    # 领导调研作为第一个 brief（新闻线索重点）
    # F-12：用 list_for_period 避免 limit=200 截断大量调研记录
    lv_visits = LeadershipVisit.list_for_publish_period(
        publish_date_from=period_start, publish_date_to=period_end
    )
    if lv_visits:
        leadership_items = []
        for lv in lv_visits:
            entities = json.loads(lv.visited_entities) if lv.visited_entities else []
            entities_str = "、".join(entities[:5]) if entities else ""
            clue = f"【新闻线索】{lv.leader_name}（{lv.leader_title or ''}）调研：{lv.visit_topic or ''}"
            if entities_str:
                clue += f"，走访：{entities_str}"
            source_url, source_name = "", ""
            if lv.source_doc_id:
                doc = Document.get_by_id(lv.source_doc_id)
                if doc:
                    source_url = doc.url or ""
                    source_name = doc.source or ""
            leadership_items.append({
                "title": f"{lv.leader_name}调研{(lv.visit_topic or '')[:20]}",
                "clue": clue,
                "priority": lv.priority,
                "publish_date": lv.publish_date or lv.visit_date or "",
                "visit_date": lv.visit_date or "",
                "source_url": source_url,
                "source_name": source_name,
            })
        briefs.insert(0, {
            "line": "leadership",
            "label": "领导调研",
            "count": len(lv_visits),
            "items": leadership_items,
        })

    # 按商机数降序（领导调研已固定为第一条）
    if briefs and briefs[0].get("line") == "leadership":
        rest = briefs[1:]
        rest.sort(key=lambda x: x["count"], reverse=True)
        briefs = [briefs[0]] + rest
    else:
        briefs.sort(key=lambda x: x["count"], reverse=True)
    return briefs
