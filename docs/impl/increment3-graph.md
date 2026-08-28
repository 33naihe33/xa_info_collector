# 增量 3 实施文档：关系图谱模式 — ECharts 力导向图可视化

> 创建日期：2026-07-10
> 状态：已完成

## 交付内容

### 后端 API
- **`GET /api/graph`**：返回 ECharts 力导向图所需的 nodes/edges/categories 数据
  - 支持查询参数：
    - `entity_types`：逗号分隔的实体类型筛选（如 `机构,人物`）
    - `relation_types`：逗号分隔的关系类型筛选
    - `limit`：最大节点数（1-500，默认 200）
  - 返回结构：`{ nodes, edges, categories, total_nodes, total_edges }`

### 前端
- **`GraphView.vue`**：ECharts 力导向图可视化页面
  - 力导向布局（repulsion/edgeLength/gravity 可配）
  - 节点缩放、拖拽、平移（roam + draggable）
  - 节点类型筛选（机构/人物/项目 多选）+ 节点上限选择
  - 点击节点弹出详情抽屉，展示关联实体
  - 图表生命周期管理（onMounted 初始化 / onBeforeUnmount dispose）
  - 窗口 resize 自适应
- **`client.ts`**：新增 `GraphNode`/`GraphEdge`/`GraphData` 类型 + `getGraph` 方法
- **路由**：`/graph`
- **菜单项**：「关系图谱」（Share 图标）

### 数据约定
| 项 | 说明 |
|----|------|
| 节点类别 | 机构 / 人物 / 项目（其他类型归为"其他"） |
| 节点大小 | 机构 40 / 人物 30 / 项目 25（其他 20） |
| 节点颜色 | 机构 #409eff / 人物 #67c23a / 项目 #e6a23c / 其他 #909399 |
| 边 | 仅包含图谱中实际存在节点之间的关系，避免悬空边 |

## API 契约（前端 ↔ 后端映射）

| 前端调用 | 后端接口 | 用途 |
|----------|----------|------|
| `apiClient.getGraph({ entity_types, limit })` | `GET /api/graph` | 获取图谱 nodes/edges/categories |

> GraphView.vue 仅调用 `GET /api/graph` 一个后端端点，节点详情（关联实体）通过前端遍历本地 nodes/edges 计算，无额外后端调用。

## 测试（71 个，全部通过）

| 测试文件 | 数量 | 覆盖 |
|----------|------|------|
| tests/web/test_graph_api.py | 6 | 图谱 API（nodes/edges/categories 字段、筛选、limit） |
| tests/e2e/test_graph_e2e.py | 1 | 前端契约校验（GraphView 用到的每个字段都存在） |
| 增量 1-2 已有测试 | 64 | 爬虫/存储/文档/商机/分析层 |

新增测试明细：
- `test_graph_returns_nodes_and_edges`：基本数据返回
- `test_node_has_required_fields`：节点字段（id/name/category/symbolSize）
- `test_edge_has_required_fields`：边字段（source/target/relation_type）
- `test_graph_filter_by_entity_type`：实体类型筛选
- `test_graph_limit`：节点数上限
- `test_graph_categories`：图例类别列表
- `test_graph_api_frontend_contract`（e2e）：前端用到字段全覆盖

## 前端构建

```
cd web/frontend && npm run build
```
- `vue-tsc --noEmit` 通过（无 TS 类型错误）
- `vite build` 成功产出 dist/
- ECharts 作为依赖打包进 GraphView chunk

## 实施中的技术调整

### 1. ECharts 回调参数类型
ECharts 的 `chart.on('click', cb)` 和 tooltip `formatter` 回调参数类型较松散（`ECElementEvent` 的 `dataType` 为 `string | undefined`），与严格的内联类型签名不兼容，会导致 `vue-tsc` 报 TS2345。

**处理**：回调参数标注为 `any`，这是 ECharts 回调的常见用法（其 API 本身高度动态），不影响运行时正确性，避免与 echarts 类型定义纠缠。

### 2. categories 排序
后端对 categories 按 `CATEGORY_ORDER`（机构/人物/项目/其他）预定义顺序排序，保证图例顺序稳定、颜色映射可预期，而非按数据库查询顺序。

### 3. 边过滤保证一致性
后端只返回两端节点都在当前 `entity_types`/`limit` 范围内的边（`from_entity_id IN ids AND to_entity_id IN ids`），避免前端渲染悬空边指向不存在节点。

## 已知限制

- 力导向图为一次性渲染全部节点（最大 500），未做分页/聚类；超大图谱性能可能下降
- 节点详情的关联实体仅基于当前加载到前端的边计算，若节点数被 limit 截断，部分关联可能不可见
- 关系类型筛选（`relation_types` 查询参数）后端已实现，前端 UI 暂未提供（后续可加多选）

## 修复记录

| 问题 | 处理 | 影响 |
|------|------|------|
| ECharts 回调类型不匹配 | 回调参数标 `any` | vue-tsc 通过 |
