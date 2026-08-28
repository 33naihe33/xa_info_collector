# web/api/opportunities.py
from fastapi import APIRouter, HTTPException, Query
from storage.models import Opportunity

router = APIRouter()


@router.get("/opportunities")
def list_opportunities(
    business_line: str | None = Query(None),
    priority: str | None = Query(None),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    # 有日期过滤时用 list_for_period（SQL层过滤，保证 count 和 list 一致）
    if date_from or date_to:
        all_opps = Opportunity.list_for_period(
            date_from=date_from or "2000-01-01",
            date_to=date_to or "2999-12-31",
        )
        # 再叠加 business_line/priority/status 过滤
        if business_line:
            all_opps = [o for o in all_opps if o.business_line == business_line]
        if priority:
            all_opps = [o for o in all_opps if o.priority == priority]
        if status:
            all_opps = [o for o in all_opps if o.status == status]
        total = len(all_opps)
        page = all_opps[offset:offset + limit]
        return {"total": total, "items": [o.to_dict() for o in page]}

    total = Opportunity.count(business_line=business_line, priority=priority, status=status)
    opps = Opportunity.list(
        business_line=business_line, priority=priority, status=status,
        limit=limit, offset=offset,
    )
    return {"total": total, "items": [o.to_dict() for o in opps]}


@router.get("/opportunities/stats")
def opportunity_stats():
    """商机统计：按条线汇总。"""
    from storage.models import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT business_line, COUNT(*) as c FROM opportunities GROUP BY business_line"
    ).fetchall()
    by_line = {row["business_line"]: row["c"] for row in rows}
    total = sum(by_line.values())
    return {"total": total, "by_line": by_line}


@router.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: int):
    opp = Opportunity.get_by_id(opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp.to_dict()
