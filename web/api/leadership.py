# web/api/leadership.py
from fastapi import APIRouter, HTTPException, Query

from storage.models import LeadershipVisit, Document

router = APIRouter()


@router.get("/leadership")
def list_leadership(
    visit_date_from: str | None = Query(None),
    visit_date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = LeadershipVisit.count(
        visit_date_from=visit_date_from, visit_date_to=visit_date_to,
    )
    visits = LeadershipVisit.list(
        visit_date_from=visit_date_from, visit_date_to=visit_date_to,
        limit=limit, offset=offset,
    )
    items = []
    for v in visits:
        d = v.to_dict()
        d["source_url"], d["source_name"] = _lookup_source(v.source_doc_id)
        items.append(d)
    return {"total": total, "items": items}


@router.get("/leadership/stats")
def leadership_stats():
    """领导调研统计：总数 + 按优先级。"""
    from storage.models import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT priority, COUNT(*) as c FROM leadership_visits GROUP BY priority"
    ).fetchall()
    by_priority = {row["priority"]: row["c"] for row in rows}
    total = sum(by_priority.values())
    return {"total": total, "by_priority": by_priority}


@router.get("/leadership/{visit_id}")
def get_leadership(visit_id: int):
    visit = LeadershipVisit.get_by_id(visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Leadership visit not found")
    data = visit.to_dict()
    data["source_url"], data["source_name"] = _lookup_source(visit.source_doc_id)
    return data


def _lookup_source(source_doc_id: int | None) -> tuple[str, str]:
    """查找源文档的 URL 和来源名（用于「查看原文」链接）。"""
    if not source_doc_id:
        return "", ""
    doc = Document.get_by_id(source_doc_id)
    if not doc:
        return "", ""
    return doc.url or "", doc.source or ""
