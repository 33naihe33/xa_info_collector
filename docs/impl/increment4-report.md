# 增量 4 实施文档：报告生成 — 日/周/月报 + Word 导出

> 创建日期：2026-07-10
> 状态：已完成

## 交付内容

### 后端
- **`reports` 表 + `Report` DAO**（`storage/models.py`）
  - 字段：`id, report_type, period_start, period_end, content(JSON), opportunity_ids(JSON), docx_path, pdf_path, generated_at`
  - 方法：`create / get_by_id / list / update_files / to_dict`
- **报告生成器**（`reporter/generator.py`）
  - `generate_report(report_type, period_start, period_end, llm_client, business_lines)`
  - 按日期/业务条线过滤商机 → 构建摘要文本 → 调 LLM(`generate_report` 提示词) → 返回结构化 JSON
  - 无商机时返回基本结构，不调 LLM
- **Word 导出器**（`reporter/exporter.py`）
  - `export_to_docx(report_content, output_path)` → 用 python-docx 生成正式公文格式
  - 结构：标题 → 一、本期概要 → 各条线章节（中文序号）→ 每条商机的规模/产品/解读/建议 → 重点关注与建议
- **报告提示词**（`config/prompts/generate_report.txt`）
  - 要求 LLM 按业务条线分章节，返回 `{title, summary, sections[], recommendations, stats}`

### API（`web/api/reports.py`）

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/reports/generate` | POST | 生成报告（同步），返回 `{report_id, content}` |
| `/api/reports` | GET | 历史报告列表，返回 `{total, items[]}` |
| `/api/reports/{id}` | GET | 报告详情（含 content） |
| `/api/reports/{id}/export?format=docx` | GET | 导出 Word 文件（FileResponse） |

### 前端（`web/frontend/src/views/ReportView.vue`）
- 生成表单：报告类型（日/周/月）+ 时间范围 + 业务条线多选
- 报告预览卡片：概要 / 商机总数 / 各条线商机明细 / 重点关注
- 导出 Word 按钮（`window.open` 下载）
- 历史报告表格：类型 / 时间范围 / 生成时间 / 商机数 / 预览 / 导出
- 路由 `/reports`，菜单项「报告」（Tickets 图标）

## API 契约（前端 ↔ 后端映射）

| 前端调用 | 后端接口 | 用途 |
|----------|----------|------|
| `apiClient.generateReport({ report_type, date_from, date_to, business_lines })` | `POST /api/reports/generate` | 生成新报告 |
| `apiClient.getReports()` | `GET /api/reports` | 历史报告列表 |
| `apiClient.getReport(id)` | `GET /api/reports/{id}` | 报告详情 |
| `apiClient.exportReportUrl(id, format)` | `GET /api/reports/{id}/export?format=docx` | 导出 Word（浏览器直接打开下载） |

## 报告内容 JSON 结构

```json
{
  "title": "雄安新区金融业务机会周报（2026-07-04 ~ 2026-07-10）",
  "summary": "本期概要（2-3句）",
  "sections": [
    { "line": "对公业务", "opportunities": [
      { "title": "商机标题", "scale": "规模", "products": "产品",
        "action": "建议", "insight": "解读" }
    ] }
  ],
  "recommendations": "重点关注与建议",
  "stats": { "total": 12, "by_priority": { "high": 3, "medium": 6, "low": 3 } }
}
```

## 测试覆盖（新增 14 个，累计 85 passed）

| 测试文件 | 数量 | 覆盖内容 |
|----------|------|----------|
| `tests/storage/test_report_models.py` | 4 | Report DAO 增查改 |
| `tests/reporter/test_generator.py` | 2 | 生成器（有/无商机） |
| `tests/reporter/test_exporter.py` | 2 | Word 导出（有/无章节） |
| `tests/web/test_reports_api.py` | 5 | API 生成/列表/详情/404/导出 |
| `tests/e2e/test_report_e2e.py` | 1 | 前端契约全流程 |

## 文件清单

- `storage/models.py` — 新增 `reports` 表 DDL + `Report` 类
- `reporter/__init__.py`、`reporter/generator.py`、`reporter/exporter.py`
- `config/prompts/generate_report.txt`
- `web/api/reports.py`、`web/app.py`（注册路由）
- `web/frontend/src/api/client.ts` — 报告类型 + 4 个 API 方法
- `web/frontend/src/views/ReportView.vue`
- `web/frontend/src/router/index.ts`、`web/frontend/src/App.vue`
