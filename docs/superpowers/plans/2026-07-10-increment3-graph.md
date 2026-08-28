# 增量 3：关系图谱模式 — ECharts 力导向图可视化

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 新增"关系图谱"模式，将 entities + relations 数据以 ECharts 力导向图可视化，支持节点类型筛选、关系类型筛选、点击节点查看关联商机。

**Architecture:** 后端新增 GET /api/graph 端点返回 nodes[] + edges[]，前端新增 GraphView.vue 使用 ECharts 力导向图渲染，支持筛选和交互。

**Tech Stack:** ECharts 5（力导向图 graph 系列），Vue 3，FastAPI。

---

## 文件结构（本增量创建/修改）

```
web/api/graph.py              # 图谱数据 API
web/app.py                    # 注册路由
web/frontend/src/views/GraphView.vue  # 图谱可视化页面
web/frontend/src/api/client.ts        # 新增 getGraph 方法
web/frontend/src/router/index.ts      # 新增路由
web/frontend/src/App.vue              # 侧边栏新增菜单
```

---

## Task 1: 图谱数据 API

**Files:**
- Create: `web/api/graph.py`
- Modify: `web/app.py`（注册路由）
- Test: `tests/web/test_graph_api.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/web/test_graph_api.py
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Document, Entity, Relation


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    # 创建测试数据：机构-人物-项目关系网
    org = Entity.create(name="雄安集团", entity_type="机构")
    person = Entity.create(name="张国华", entity_type="人物")
    proj = Entity.create(name="启动区建设", entity_type="项目")
    Relation.create(from_entity_id=person.id, to_entity_id=org.id,
                    relation_type="调研", source_doc_id=None, publish_date="2026-07-10")
    Relation.create(from_entity_id=org.id, to_entity_id=proj.id,
                    relation_type="投资", source_doc_id=None, publish_date="2026-07-10")

    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_graph_returns_nodes_and_edges(client):
    resp = client.get("/api/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 2

def test_node_has_required_fields(client):
    resp = client.get("/api/graph")
    node = resp.json()["nodes"][0]
    assert "id" in node
    assert "name" in node
    assert "category" in node  # entity_type
    assert "symbolSize" in node  # 节点大小

def test_edge_has_required_fields(client):
    resp = client.get("/api/graph")
    edge = resp.json()["edges"][0]
    assert "source" in edge
    assert "target" in edge
    assert "relation_type" in edge

def test_graph_filter_by_entity_type(client):
    """只看机构节点。"""
    resp = client.get("/api/graph?entity_types=机构")
    data = resp.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["name"] == "雄安集团"

def test_graph_limit(client):
    """限制节点数（大数据量时只展示核心节点）。"""
    resp = client.get("/api/graph?limit=2")
    data = resp.json()
    assert len(data["nodes"]) <= 2

def test_graph_categories(client):
    """返回节点类别列表（前端图例用）。"""
    resp = client.get("/api/graph")
    data = resp.json()
    assert "categories" in data
    cat_names = [c["name"] for c in data["categories"]]
    assert "机构" in cat_names
    assert "人物" in cat_names
    assert "项目" in cat_names
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/web/test_graph_api.py -v`
Expected: FAIL — 404/ModuleNotFoundError

- [ ] **Step 3: 实现 web/api/graph.py**

```python
# web/api/graph.py
"""关系图谱 API：返回 ECharts 力导向图所需的 nodes + edges 数据。"""
from fastapi import APIRouter, Query
from storage.models import Entity, Relation, get_conn

router = APIRouter()

# 节点大小按类型（机构最大，人物中等，项目较小）
NODE_SIZE = {"机构": 40, "人物": 30, "项目": 25}
# ECharts 类别颜色（索引对应 categories 顺序）
CATEGORY_ORDER = ["机构", "人物", "项目", "其他"]


@router.get("/graph")
def get_graph(
    entity_types: str | None = Query(None, description="逗号分隔的实体类型，如 机构,人物"),
    relation_types: str | None = Query(None, description="逗号分隔的关系类型"),
    limit: int = Query(200, ge=1, le=500, description="最大节点数"),
):
    """返回图谱 nodes + edges + categories。"""
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
    entity_type_map = {row["id"]: row["entity_type"] for row in entity_rows}

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

    # 构建类别（ECharts 图例）
    used_cats = sorted(set(n["category"] for n in nodes))
    categories = [{"name": c} for c in used_cats]

    return {
        "nodes": nodes,
        "edges": edges,
        "categories": categories,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }
```

- [ ] **Step 4: 注册路由到 app.py**

在 `web/app.py` 中添加：
```python
from web.api import documents, collect, opportunities, graph
# ...
app.include_router(graph.router, prefix="/api")
```

- [ ] **Step 5: 运行验证通过**

Run: `pytest tests/web/test_graph_api.py -v`
Expected: 6 passed

- [ ] **Step 6: 全量测试 + Commit**

Run: `pytest tests/ -v` → 70 passed (64 + 6)

```bash
git add web/api/graph.py web/app.py tests/web/test_graph_api.py
git commit -m "feat: 关系图谱 API — nodes/edges/categories 数据端点"
```

---

## Task 2: 前端 ECharts 力导向图页面

**Files:**
- Modify: `web/frontend/src/api/client.ts`
- Create: `web/frontend/src/views/GraphView.vue`
- Modify: `web/frontend/src/router/index.ts`
- Modify: `web/frontend/src/App.vue`

- [ ] **Step 1: 在 client.ts 新增图谱 API**

```typescript
export interface GraphNode {
  id: number
  name: string
  category: string
  symbolSize: number
  entity_type: string
}

export interface GraphEdge {
  source: number
  target: number
  relation_type: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  categories: { name: string }[]
  total_nodes: number
  total_edges: number
}
```

在 apiClient 中追加：
```typescript
  getGraph: (params: { entity_types?: string; relation_types?: string; limit?: number }) =>
    api.get<GraphData>('/graph', { params }),
```

- [ ] **Step 2: 安装 ECharts 依赖**

Run: `cd web/frontend && npm install echarts`

- [ ] **Step 3: 创建 GraphView.vue**

```vue
<!-- web/frontend/src/views/GraphView.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div>
        <h2 style="margin: 0; display: inline-block;">关系图谱</h2>
        <span v-if="graphData" style="margin-left: 12px; color: #909399; font-size: 13px;">
          {{ graphData.total_nodes }} 个节点 · {{ graphData.total_edges }} 条关系
        </span>
      </div>
      <el-button type="primary" :icon="Refresh" @click="fetchGraph" :loading="loading">刷新</el-button>
    </div>

    <!-- 筛选栏 -->
    <div style="display: flex; gap: 16px; margin-bottom: 16px; align-items: center;">
      <span style="font-size: 13px; color: #606266;">节点类型：</span>
      <el-checkbox-group v-model="selectedTypes" @change="fetchGraph">
        <el-checkbox label="机构">机构</el-checkbox>
        <el-checkbox label="人物">人物</el-checkbox>
        <el-checkbox label="项目">项目</el-checkbox>
      </el-checkbox-group>
      <span style="font-size: 13px; color: #606266; margin-left: 16px;">节点上限：</span>
      <el-select v-model="nodeLimit" style="width: 100px;" @change="fetchGraph">
        <el-option :value="50" label="50" />
        <el-option :value="100" label="100" />
        <el-option :value="200" label="200" />
        <el-option :value="500" label="500" />
      </el-select>
    </div>

    <!-- 图谱容器 -->
    <div ref="chartRef" style="width: 100%; height: 600px; border: 1px solid #ebeef5; border-radius: 4px;" v-loading="loading"></div>

    <!-- 节点详情面板 -->
    <el-drawer v-model="detailVisible" :title="selectedNode?.name || ''" size="40%">
      <div v-if="selectedNode">
        <p><strong>类型：</strong>
          <el-tag :color="nodeColor(selectedNode.category)" style="color: #fff;" size="small">
            {{ selectedNode.category }}
          </el-tag>
        </p>
        <el-divider />
        <h4>关联实体（通过关系连接）</h4>
        <el-tag v-for="r in relatedEntities" :key="r.name" style="margin: 4px;" size="small">
          {{ r.type }} → {{ r.name }}
        </el-tag>
        <el-empty v-if="relatedEntities.length === 0" description="无关联实体" :image-size="60" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { apiClient, type GraphData, type GraphNode } from '../api/client'

const CATEGORY_COLORS: Record<string, string> = {
  '机构': '#409eff',
  '人物': '#67c23a',
  '项目': '#e6a23c',
  '其他': '#909399',
}

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
const graphData = ref<GraphData | null>(null)
const loading = ref(false)
const selectedTypes = ref<string[]>(['机构', '人物', '项目'])
const nodeLimit = ref(200)
const detailVisible = ref(false)
const selectedNode = ref<GraphNode | null>(null)
const relatedEntities = ref<{ name: string; type: string }[]>([])

function nodeColor(category: string) {
  return CATEGORY_COLORS[category] || '#909399'
}

async function fetchGraph() {
  loading.value = true
  try {
    const resp = await apiClient.getGraph({
      entity_types: selectedTypes.value.join(','),
      limit: nodeLimit.value,
    })
    graphData.value = resp.data
    await nextTick()
    renderChart()
  } finally {
    loading.value = false
  }
}

function renderChart() {
  if (!chartRef.value || !graphData.value) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
    chart.on('click', (params: any) => {
      if (params.dataType === 'node') {
        showNodeDetail(params.data)
      }
    })
  }

  const data = graphData.value
  const categories = data.categories.map(c => ({
    name: c.name,
    itemStyle: { color: nodeColor(c.name) },
  }))

  chart.setOption({
    tooltip: {
      formatter: (params: any) => {
        if (params.dataType === 'node') {
          return `<b>${params.data.name}</b><br/>类型: ${params.data.category}`
        } else if (params.dataType === 'edge') {
          return params.data.relation_type || '关联'
        }
        return ''
      },
    },
    legend: [{
      data: categories.map(c => c.name),
      textStyle: { color: '#606266' },
    }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      label: {
        show: true,
        position: 'right',
        fontSize: 11,
      },
      force: {
        repulsion: 200,
        edgeLength: [80, 200],
        gravity: 0.1,
      },
      categories: categories,
      data: data.nodes.map(n => ({
        ...n,
        itemStyle: { color: nodeColor(n.category) },
      })),
      edges: data.edges.map(e => ({
        ...e,
        label: {
          show: true,
          formatter: e.relation_type,
          fontSize: 9,
          color: '#aaa',
        },
      })),
      lineStyle: {
        color: '#ccc',
        width: 1,
        curveness: 0.1,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 },
      },
    }],
  }, true)
}

function showNodeDetail(node: GraphNode) {
  selectedNode.value = node
  // 查找关联实体
  if (graphData.value) {
    const related: { name: string; type: string }[] = []
    for (const edge of graphData.value.edges) {
      if (edge.source === node.id) {
        const target = graphData.value.nodes.find(n => n.id === edge.target)
        if (target) related.push({ name: target.name, type: edge.relation_type })
      } else if (edge.target === node.id) {
        const source = graphData.value.nodes.find(n => n.id === edge.source)
        if (source) related.push({ name: source.name, type: edge.relation_type })
      }
    }
    relatedEntities.value = related
  }
  detailVisible.value = true
}

function handleResize() {
  chart?.resize()
}

onMounted(() => {
  fetchGraph()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose()
  chart = null
})
</script>
```

- [ ] **Step 4: 在 router/index.ts 新增路由**

```typescript
{ path: '/graph', name: 'graph', component: () => import('../views/GraphView.vue') },
```

- [ ] **Step 5: 在 App.vue 侧边栏新增菜单项**

```vue
<el-menu-item index="/graph">
  <el-icon><Share /></el-icon>
  <span>关系图谱</span>
</el-menu-item>
```

- [ ] **Step 6: 验证构建 + Commit**

Run: `cd web/frontend && npm run build`
Expected: 构建成功

```bash
git add web/frontend/ web/frontend/package.json
git commit -m "feat: 关系图谱页 — ECharts 力导向图 + 节点筛选 + 点击详情"
```

---

## Task 3: 端到端验证 + 实施文档

- [ ] **Step 1: 写图谱端到端测试**

```python
# tests/e2e/test_graph_e2e.py
"""关系图谱端到端测试：验证前端用到的图谱 API 字段完整。"""
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Entity, Relation


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    org = Entity.create(name="测试机构", entity_type="机构")
    person = Entity.create(name="测试人物", entity_type="人物")
    Relation.create(from_entity_id=person.id, to_entity_id=org.id,
                    relation_type="调研", publish_date="2026-07-10")
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_graph_api_frontend_contract(client):
    """验证前端 GraphView.vue 用到的每个 API 字段都存在。"""
    resp = client.get("/api/graph")
    data = resp.json()
    # nodes 字段
    for node in data["nodes"]:
        assert "id" in node
        assert "name" in node
        assert "category" in node
        assert "symbolSize" in node
    # edges 字段
    for edge in data["edges"]:
        assert "source" in edge
        assert "target" in edge
    # 顶层字段
    assert "categories" in data
    assert "total_nodes" in data
    assert "total_edges" in data
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/e2e/test_graph_e2e.py -v`
Expected: 1 passed

Run: `pytest tests/ -v` → 71 passed

- [ ] **Step 3: Commit + 实施文档**

```bash
git add tests/e2e/test_graph_e2e.py
git commit -m "test: 关系图谱端到端测试 — 前端契约校验"
```

撰写 `docs/impl/increment3-graph.md` 并提交。

---

## 完成标准

1. ✅ `pytest tests/ -v` 全部通过（71 个）
2. ✅ 前端 `npm run build` 无错误
3. ✅ 图谱 API 返回 nodes/edges/categories
4. ✅ 前端图谱页可交互（缩放/拖拽/点击节点）
5. ✅ 每个 Task 有 commit
