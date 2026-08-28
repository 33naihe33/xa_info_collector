# web/api/graph.py
"""关系图谱 API：返回 ECharts 力导向图所需的 nodes + edges 数据。"""
from fastapi import APIRouter, Query
from storage.models import get_conn

router = APIRouter()

# 节点大小按类型（机构最大，人物中等，项目较小）
NODE_SIZE = {"机构": 40, "人物": 30, "项目": 25}
# ECharts 类别（顺序用于颜色映射与图例）
CATEGORY_ORDER = ["机构", "人物", "项目", "其他"]


@router.get("/graph")
def get_graph(
    entity_types: str | None = Query(None, description="逗号分隔的实体类型，如 机构,人物"),
    relation_types: str | None = Query(None, description="逗号分隔的关系类型"),
    limit: int = Query(200, ge=1, le=500, description="最大节点数"),
):
    """返回图谱 nodes + edges + categories（ECharts 力导向图格式）。"""
    conn = get_conn()

    # 筛选实体类型
    type_filter = None
    if entity_types:
        type_filter = [t.strip() for t in entity_types.split(",") if t.strip()]

    # 查询实体
    if type_filter:
        placeholders = ",".join("?" * len(type_filter))
        entity_rows = conn.execute(
            f"SELECT * FROM entities WHERE entity_type IN ({placeholders}) LIMIT ?",
            (*type_filter, limit),
        ).fetchall()
    else:
        entity_rows = conn.execute(
            "SELECT * FROM entities LIMIT ?", (limit,),
        ).fetchall()

    entity_ids = {row["id"] for row in entity_rows}

    # 构建节点
    nodes = []
    for row in entity_rows:
        etype = row["entity_type"]
        cat = etype if etype in CATEGORY_ORDER else "其他"
        nodes.append({
            "id": row["id"],
            "name": row["name"],
            "category": cat,
            "symbolSize": NODE_SIZE.get(etype, 20),
            "entity_type": etype,
        })

    # 查询关系（只包含图谱中存在的实体间的关系）
    rel_filter = None
    if relation_types:
        rel_filter = [r.strip() for r in relation_types.split(",") if r.strip()]

    if entity_ids:
        id_list = list(entity_ids)
        placeholders = ",".join("?" * len(id_list))
        if rel_filter:
            rel_placeholders = ",".join("?" * len(rel_filter))
            rel_rows = conn.execute(
                f"""SELECT * FROM relations
                    WHERE from_entity_id IN ({placeholders})
                      AND to_entity_id IN ({placeholders})
                      AND relation_type IN ({rel_placeholders})""",
                (*id_list, *id_list, *rel_filter),
            ).fetchall()
        else:
            rel_rows = conn.execute(
                f"""SELECT * FROM relations
                    WHERE from_entity_id IN ({placeholders})
                      AND to_entity_id IN ({placeholders})""",
                (*id_list, *id_list),
            ).fetchall()
    else:
        rel_rows = []

    # 构建边
    edges = []
    for row in rel_rows:
        edges.append({
            "source": row["from_entity_id"],
            "target": row["to_entity_id"],
            "relation_type": row["relation_type"],
        })

    # 构建类别（ECharts 图例），按预定义顺序排列以保证颜色稳定
    used_cats = sorted(
        set(n["category"] for n in nodes),
        key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else len(CATEGORY_ORDER),
    )
    categories = [{"name": c} for c in used_cats]

    return {
        "nodes": nodes,
        "edges": edges,
        "categories": categories,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }
