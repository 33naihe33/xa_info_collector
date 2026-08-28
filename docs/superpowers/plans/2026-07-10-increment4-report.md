# 增量 4：报告生成 — 日/周/月报 + Word/PDF 导出

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 用户选择报告类型（日/周/月）+ 时间范围 + 业务条线 → LLM 汇总该时段商机 → 预览 → 导出 Word/PDF 正式报告，按业务条线分章节。

**Architecture:** 后端 reporter 模块用 GLM 汇总商机生成报告内容（JSON），python-docx 生成 Word，PDF 从 Word 转换。API 支持生成/列表/预览/下载。前端报告页支持参数选择 → 预览 → 导出。

**Tech Stack:** python-docx（Word 生成），GLM-4-flash（内容汇总），FastAPI（API），Vue（报告页）。

---

## 文件结构（本增量创建/修改）

```
reporter/
├── __init__.py
├── generator.py       # 报告内容生成（LLM 汇总）
├── exporter.py        # Word/PDF 导出
storage/models.py     # 新增 reports 表 + Report DAO
web/api/reports.py     # 报告 API
web/app.py             # 注册路由
config/prompts/generate_report.txt  # 报告生成提示词
web/frontend/src/views/ReportView.vue  # 报告页
web/frontend/src/api/client.ts         # 新增报告 API
```

---

## Task 1: reports 表 + Report DAO

**Files:**
- Modify: `storage/models.py`
- Test: `tests/storage/test_report_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/storage/test_report_models.py
import pytest
from storage.models import init_db, close_db, Report


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_create_report():
    report = Report.create(
        report_type="weekly",
        period_start="2026-07-04",
        period_end="2026-07-10",
        content='{"summary": "测试"}',
        opportunity_ids="[1,2,3]",
    )
    assert report.id is not None
    assert report.report_type == "weekly"

def test_get_report_by_id():
    report = Report.create(
        report_type="daily", period_start="2026-07-10", period_end="2026-07-10",
        content="{}", opportunity_ids="[]",
    )
    fetched = Report.get_by_id(report.id)
    assert fetched.report_type == "daily"

def test_list_reports():
    Report.create(report_type="daily", period_start="2026-07-09", period_end="2026-07-09",
                  content="{}", opportunity_ids="[]")
    Report.create(report_type="weekly", period_start="2026-07-04", period_end="2026-07-10",
                  content="{}", opportunity_ids="[]")
    reports = Report.list()
    assert len(reports) == 2

def test_update_file_paths():
    report = Report.create(report_type="daily", period_start="2026-07-10", period_end="2026-07-10",
                           content="{}", opportunity_ids="[]")
    report.update_files(docx_path="reports/daily.docx", pdf_path="reports/daily.pdf")
    fetched = Report.get_by_id(report.id)
    assert fetched.docx_path == "reports/daily.docx"
    assert fetched.pdf_path == "reports/daily.pdf"
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/storage/test_report_models.py -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 在 models.py 新增 reports 表 DDL + Report DAO**

DDL（追加到 SCHEMA_SQL）:
```sql
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    content TEXT DEFAULT '{}',
    opportunity_ids TEXT DEFAULT '[]',
    docx_path TEXT,
    pdf_path TEXT,
    generated_at TEXT NOT NULL
);
```

Report DAO:
```python
class Report:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.report_type = row["report_type"]
        self.period_start = row["period_start"]
        self.period_end = row["period_end"]
        self.content = row["content"]
        self.opportunity_ids = row["opportunity_ids"]
        self.docx_path = row["docx_path"] if "docx_path" in row.keys() else None
        self.pdf_path = row["pdf_path"] if "pdf_path" in row.keys() else None
        self.generated_at = row["generated_at"]

    @classmethod
    def create(cls, *, report_type, period_start, period_end,
               content="{}", opportunity_ids="[]") -> "Report":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO reports (report_type, period_start, period_end, content,
               opportunity_ids, generated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_type, period_start, period_end, content, opportunity_ids,
             datetime.now().isoformat()),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, rid: int) -> "Report | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, limit: int = 20) -> list["Report"]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM reports ORDER BY generated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [cls(r) for r in rows]

    def update_files(self, *, docx_path: str | None = None, pdf_path: str | None = None):
        conn = get_conn()
        conn.execute(
            "UPDATE reports SET docx_path = ?, pdf_path = ? WHERE id = ?",
            (docx_path, pdf_path, self.id),
        )
        conn.commit()
        self.docx_path = docx_path
        self.pdf_path = pdf_path

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id, "report_type": self.report_type,
            "period_start": self.period_start, "period_end": self.period_end,
            "content": json.loads(self.content) if self.content else {},
            "opportunity_ids": json.loads(self.opportunity_ids) if self.opportunity_ids else [],
            "docx_path": self.docx_path, "pdf_path": self.pdf_path,
            "generated_at": self.generated_at,
        }
```

- [ ] **Step 4: 运行验证通过 + Commit**

Run: `pytest tests/storage/test_report_models.py -v` → 4 passed
Run: `pytest tests/ -v` → 75 passed (71 + 4)

```bash
git add storage/models.py tests/storage/test_report_models.py
git commit -m "feat: reports 表 + Report DAO"
```

---

## Task 2: 报告生成提示词 + 生成器

**Files:**
- Create: `config/prompts/generate_report.txt`
- Create: `reporter/__init__.py`
- Create: `reporter/generator.py`
- Test: `tests/reporter/test_generator.py`

- [ ] **Step 1: 创建报告生成提示词**

`config/prompts/generate_report.txt`:
```
你是银行分行行长的情报分析助手。根据给定时间段内的商机信息，生成一份结构化的金融业务机会报告。

报告要求：
1. 语言正式、专业，适合行长阅读和转发
2. 按业务条线（对公/普惠/个金/政银）分章节
3. 每个商机简要列出：商机描述、预估规模、适配产品、建议行动
4. 末尾给出"重点关注与建议"章节，推荐本周最该跟进的 3 个商机

以 JSON 格式返回：
{"title": "报告标题（含时间范围）",
 "summary": "本期概要（2-3句话总结）",
 "sections": [
   {"line": "对公业务", "opportunities": [
     {"title": "商机标题", "scale": "规模", "products": "产品", "action": "建议", "insight": "解读"}
   ]}
 ],
 "recommendations": "重点关注与建议（列出最该跟进的商机）",
 "stats": {"total": 总数, "by_priority": {"high": n, "medium": n, "low": n}}}
```

- [ ] **Step 2: 写失败测试**

```python
# tests/reporter/test_generator.py
import pytest
from unittest.mock import MagicMock
from storage.models import init_db, close_db, Opportunity


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_generate_report_with_opportunities():
    """生成报告应调用 LLM 汇总商机并返回结构化内容。"""
    Opportunity.create(
        title="项目融资A", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-08", insight="解读A", action_suggest="行动A",
        fin_scale="10亿", fin_products='["项目贷"]',
    )
    Opportunity.create(
        title="科创企业B", source_doc_id=None, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date="2026-07-06", insight="解读B",
    )

    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "title": "周报",
        "summary": "本期2条商机",
        "sections": [{"line": "对公", "opportunities": []}],
        "recommendations": "重点跟进A",
        "stats": {"total": 2},
    }

    from reporter.generator import generate_report
    result = generate_report(
        report_type="weekly",
        period_start="2026-07-04", period_end="2026-07-10",
        llm_client=mock_llm,
    )

    assert result["title"] == "周报"
    assert mock_llm.chat_json.call_count == 1
    # 验证商机信息被传入 prompt
    call_args = mock_llm.chat_json.call_args
    user_prompt = call_args.kwargs["user"]
    assert "项目融资A" in user_prompt


def test_generate_report_no_opportunities():
    """无商机时仍应返回基本结构。"""
    mock_llm = MagicMock()
    from reporter.generator import generate_report
    result = generate_report(
        report_type="daily",
        period_start="2026-07-10", period_end="2026-07-10",
        llm_client=mock_llm,
    )
    assert "title" in result
    assert result["summary"] == "本期无新增商机线索。"
    mock_llm.chat_json.assert_not_called()
```

- [ ] **Step 3: 实现 generator.py**

```python
# reporter/generator.py
"""报告生成器：汇总指定时段商机，调 LLM 生成结构化报告内容。"""
import json
import logging

from analyzer.rules_loader import load_prompt
from storage.models import Opportunity

logger = logging.getLogger(__name__)

LINE_LABELS = {
    "corporate": "对公业务", "inclusive": "普惠金融",
    "retail": "个人金融", "partnership": "政银合作",
}


def generate_report(*, report_type: str, period_start: str, period_end: str,
                    llm_client, business_lines: list[str] | None = None) -> dict:
    """生成报告内容。返回结构化 dict。"""
    # 查询时段内商机
    opps = Opportunity.list(limit=500)
    # 按日期过滤
    opps = [o for o in opps if o.publish_date and period_start <= o.publish_date <= period_end]
    # 按条线过滤
    if business_lines:
        opps = [o for o in opps if o.business_line in business_lines]

    if not opps:
        return {
            "title": f"雄安新区金融业务机会{report_type}（{period_start} ~ {period_end}）",
            "summary": "本期无新增商机线索。",
            "sections": [],
            "recommendations": "",
            "stats": {"total": 0},
            "opportunity_count": 0,
        }

    # 构建商机摘要给 LLM
    opp_summaries = []
    for o in opps:
        products = json.loads(o.fin_products) if o.fin_products else []
        opp_summaries.append(
            f"- [{o.priority}] {LINE_LABELS.get(o.business_line, o.business_line)} | "
            f"{o.title} | 规模:{o.fin_scale or '未知'} | "
            f"产品:{','.join(products)} | 解读:{o.insight or ''} | "
            f"建议:{o.action_suggest or ''}"
        )
    opp_text = "\n".join(opp_summaries)

    # 调 LLM 生成报告
    system_prompt = load_prompt("generate_report")
    user_prompt = (
        f"报告类型：{report_type}\n"
        f"时间范围：{period_start} ~ {period_end}\n"
        f"商机数量：{len(opps)}\n\n"
        f"商机列表：\n{opp_text}"
    )

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        task_type="generate_report",
    )

    if not result:
        # LLM 失败，返回基本结构
        result = {
            "title": f"雄安新区金融业务机会{report_type}（{period_start} ~ {period_end}）",
            "summary": f"本期共监测到 {len(opps)} 条商机线索。",
            "sections": [],
            "recommendations": "",
            "stats": {"total": len(opps)},
        }

    result["opportunity_count"] = len(opps)
    return result
```

- [ ] **Step 4: 运行验证通过 + Commit**

Run: `pytest tests/reporter/test_generator.py -v` → 2 passed

```bash
git add reporter/ config/prompts/generate_report.txt tests/reporter/
git commit -m "feat: 报告生成器 — LLM 汇总商机生成结构化报告"
```

---

## Task 3: Word/PDF 导出

**Files:**
- Create: `reporter/exporter.py`
- Test: `tests/reporter/test_exporter.py`

- [ ] **Step 1: 写测试**

```python
# tests/reporter/test_exporter.py
import os
import json
import pytest
from reporter.exporter import export_to_docx


def test_export_to_docx_creates_file(tmp_path):
    """导出 Word 应生成 .docx 文件。"""
    report_content = {
        "title": "测试周报",
        "summary": "本期概要",
        "sections": [
            {
                "line": "对公业务",
                "opportunities": [
                    {"title": "商机A", "scale": "10亿", "products": "项目贷",
                     "action": "跟进", "insight": "解读"}
                ],
            },
        ],
        "recommendations": "重点跟进商机A",
        "stats": {"total": 1},
    }

    output_path = str(tmp_path / "test_report.docx")
    result = export_to_docx(report_content, output_path)

    assert os.path.exists(result)
    assert result.endswith(".docx")
    assert os.path.getsize(result) > 0


def test_export_to_docx_empty_sections(tmp_path):
    """无商机章节时也能正常导出。"""
    report_content = {
        "title": "空周报",
        "summary": "无商机",
        "sections": [],
        "recommendations": "",
        "stats": {"total": 0},
    }
    output_path = str(tmp_path / "empty.docx")
    result = export_to_docx(report_content, output_path)
    assert os.path.exists(result)
```

- [ ] **Step 2: 实现 exporter.py**

```python
# reporter/exporter.py
"""Word 导出器：用 python-docx 生成正式公文格式报告。"""
import os
from docx import Document
from docx.shared import Pt, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH


def export_to_docx(report_content: dict, output_path: str) -> str:
    """将报告内容导出为 Word 文档。返回文件路径。"""
    doc = Document()

    # 设置默认字体
    style = doc.styles['Normal']
    font = style.font
    font.name = 'SimSun'
    font.size = Pt(12)

    # 标题
    title = doc.add_heading(report_content.get("title", "雄安新区金融业务机会报告"), level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 概要
    doc.add_heading("一、本期概要", level=1)
    doc.add_paragraph(report_content.get("summary", ""))

    # 统计信息
    stats = report_content.get("stats", {})
    if stats:
        doc.add_paragraph(f"商机总数：{stats.get('total', 0)}")

    # 各条线章节
    sections = report_content.get("sections", [])
    for i, section in enumerate(sections, start=2):
        line_name = section.get("line", "其他")
        opps = section.get("opportunities", [])
        doc.add_heading(f"{'一二三四五六七八九十'[i-2] if i-2 < 10 else i}、{line_name}（{len(opps)}条）", level=1)

        if not opps:
            doc.add_paragraph("本期暂无相关商机。")
            continue

        for j, opp in enumerate(opps, 1):
            doc.add_heading(f"{j}. {opp.get('title', '')}", level=2)
            if opp.get("scale"):
                doc.add_paragraph(f"预估规模：{opp['scale']}")
            if opp.get("products"):
                doc.add_paragraph(f"适配产品：{opp['products']}")
            if opp.get("insight"):
                doc.add_paragraph(f"金融解读：{opp['insight']}")
            if opp.get("action"):
                doc.add_paragraph(f"建议行动：{opp['action']}")

    # 重点关注
    recommendations = report_content.get("recommendations", "")
    if recommendations:
        doc.add_heading("重点关注与建议", level=1)
        doc.add_paragraph(recommendations)

    # 确保目录存在
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    doc.save(output_path)
    return output_path
```

- [ ] **Step 3: 运行验证通过 + Commit**

Run: `pytest tests/reporter/test_exporter.py -v` → 2 passed

```bash
git add reporter/exporter.py tests/reporter/test_exporter.py
git commit -m "feat: Word 导出器 — python-docx 正式公文格式"
```

---

## Task 4: 报告 API

**Files:**
- Create: `web/api/reports.py`
- Modify: `web/app.py`
- Test: `tests/web/test_reports_api.py`

- [ ] **Step 1: 写测试**

```python
# tests/web/test_reports_api.py
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Report, Opportunity


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    Opportunity.create(
        title="商机A", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-08",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_list_reports_empty(client):
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

def test_generate_report(client):
    """生成报告应创建 Report 记录并返回内容。"""
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "title": "周报", "summary": "概要",
        "sections": [], "recommendations": "", "stats": {"total": 1},
    }
    with patch("web.api.reports.LLMClient", return_value=mock_llm):
        resp = client.post("/api/reports/generate", json={
            "report_type": "weekly",
            "date_from": "2026-07-04",
            "date_to": "2026-07-10",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "report_id" in data
    assert "content" in data
    assert data["content"]["title"] == "周报"

    # 列表能查到
    resp = client.get("/api/reports")
    assert resp.json()["total"] == 1

def test_get_report_detail(client):
    report = Report.create(report_type="daily", period_start="2026-07-10",
                           period_end="2026-07-10", content='{"title":"日报"}')
    resp = client.get(f"/api/reports/{report.id}")
    assert resp.status_code == 200
    assert resp.json()["content"]["title"] == "日报"

def test_get_report_404(client):
    resp = client.get("/api/reports/99999")
    assert resp.status_code == 404

def test_export_report_docx(client, tmp_path):
    """导出 Word 文件。"""
    report = Report.create(report_type="weekly", period_start="2026-07-04",
                           period_end="2026-07-10",
                           content='{"title":"周报","summary":"概要","sections":[],"recommendations":"","stats":{"total":1}}')
    resp = client.get(f"/api/reports/{report.id}/export?format=docx")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in resp.headers.get("content-type", "")
```

- [ ] **Step 2: 实现 web/api/reports.py**

```python
# web/api/reports.py
"""报告 API：生成/列表/详情/导出。"""
import json
import os
import tempfile

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from storage.models import Report, Opportunity
from reporter.generator import generate_report
from reporter.exporter import export_to_docx

router = APIRouter()


class GenerateReportRequest(BaseModel):
    report_type: str  # daily / weekly / monthly
    date_from: str
    date_to: str
    business_lines: list[str] | None = None


@router.post("/reports/generate")
def generate_report_api(req: GenerateReportRequest):
    """生成报告（同步执行）。"""
    from analyzer.llm_client import LLMClient
    llm_client = LLMClient()

    content = generate_report(
        report_type=req.report_type,
        period_start=req.date_from,
        period_end=req.date_to,
        llm_client=llm_client,
        business_lines=req.business_lines,
    )

    # 查询包含的商机 ID
    opps = Opportunity.list(limit=500)
    opp_ids = [o.id for o in opps
               if o.publish_date and req.date_from <= o.publish_date <= req.date_to
               and (not req.business_lines or o.business_line in req.business_lines)]

    report = Report.create(
        report_type=req.report_type,
        period_start=req.date_from,
        period_end=req.date_to,
        content=json.dumps(content, ensure_ascii=False),
        opportunity_ids=json.dumps(opp_ids),
    )
    return {"report_id": report.id, "content": content}


@router.get("/reports")
def list_reports(limit: int = Query(20, ge=1, le=100)):
    reports = Report.list(limit=limit)
    return {"total": len(reports), "items": [r.to_dict() for r in reports]}


@router.get("/reports/{report_id}")
def get_report(report_id: int):
    report = Report.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report.to_dict()


@router.get("/reports/{report_id}/export")
def export_report(report_id: int, format: str = Query("docx")):
    """导出报告文件。"""
    from fastapi.responses import FileResponse

    report = Report.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    content = json.loads(report.content) if report.content else {}
    os.makedirs("data/reports", exist_ok=True)

    if format == "docx":
        output_path = f"data/reports/report_{report.id}.docx"
        export_to_docx(content, output_path)
        report.update_files(docx_path=output_path)
        return FileResponse(
            output_path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=f"{report.report_type}_{report.period_start}_{report.period_end}.docx",
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
```

- [ ] **Step 3: 注册路由 + 运行测试 + Commit**

在 app.py 添加 `from web.api import ..., reports` 和 `app.include_router(reports.router, prefix="/api")`

Run: `pytest tests/web/test_reports_api.py -v` → 5 passed
Run: `pytest tests/ -v` → 82 passed

```bash
git add web/api/reports.py web/app.py tests/web/test_reports_api.py
git commit -m "feat: 报告 API — 生成/列表/详情/Word 导出"
```

---

## Task 5: 前端报告页

**Files:**
- Modify: `web/frontend/src/api/client.ts`
- Create: `web/frontend/src/views/ReportView.vue`
- Modify: `web/frontend/src/router/index.ts`
- Modify: `web/frontend/src/App.vue`

- [ ] **Step 1: 在 client.ts 新增报告 API**

```typescript
export interface ReportContent {
  title: string
  summary: string
  sections: { line: string; opportunities: any[] }[]
  recommendations: string
  stats: { total: number; by_priority?: Record<string, number> }
  opportunity_count?: number
}

export interface ReportItem {
  id: number
  report_type: string
  period_start: string
  period_end: string
  content: ReportContent
  opportunity_ids: number[]
  docx_path: string | null
  pdf_path: string | null
  generated_at: string
}
```

apiClient 追加：
```typescript
  generateReport: (params: { report_type: string; date_from: string; date_to: string; business_lines?: string[] }) =>
    api.post<{ report_id: number; content: ReportContent }>('/reports/generate', params),
  getReports: () => api.get<{ total: number; items: ReportItem[] }>('/reports'),
  getReport: (id: number) => api.get<ReportItem>(`/reports/${id}`),
  exportReportUrl: (id: number, format: string) => `/api/reports/${id}/export?format=${format}`,
```

- [ ] **Step 2: 创建 ReportView.vue**

```vue
<!-- web/frontend/src/views/ReportView.vue -->
<template>
  <div>
    <h2 style="margin: 0 0 16px 0;">报告管理</h2>

    <!-- 生成参数 -->
    <el-card shadow="never" style="margin-bottom: 16px;">
      <template #header><strong>生成新报告</strong></template>
      <el-form :inline="true">
        <el-form-item label="类型">
          <el-select v-model="form.reportType" style="width: 100px;">
            <el-option label="日报" value="daily" />
            <el-option label="周报" value="weekly" />
            <el-option label="月报" value="monthly" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker v-model="dateRange" type="daterange"
            value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束"
            style="width: 260px;" />
        </el-form-item>
        <el-form-item label="条线">
          <el-select v-model="form.lines" multiple placeholder="全部条线" style="width: 250px;">
            <el-option label="对公" value="corporate" />
            <el-option label="普惠" value="inclusive" />
            <el-option label="个金" value="retail" />
            <el-option label="政银" value="partnership" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="generating" @click="handleGenerate">
            生成报告
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 报告预览 -->
    <el-card v-if="previewContent" shadow="never" style="margin-bottom: 16px;">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <strong>{{ previewContent.title }}</strong>
          <div>
            <el-button size="small" type="success" @click="handleExport('docx')">导出 Word</el-button>
          </div>
        </div>
      </template>
      <div style="line-height: 1.8;">
        <p><strong>本期概要：</strong>{{ previewContent.summary }}</p>
        <p v-if="previewContent.stats">
          <strong>商机总数：</strong>{{ previewContent.stats.total }}
        </p>
        <el-divider />
        <div v-for="(section, i) in previewContent.sections" :key="i">
          <h3>{{ section.line }}（{{ section.opportunities?.length || 0 }}条）</h3>
          <div v-for="(opp, j) in section.opportunities" :key="j" style="margin-bottom: 12px; padding: 8px; background: #f5f7fa; border-radius: 4px;">
            <p style="margin: 0;"><strong>{{ j + 1 }}. {{ opp.title }}</strong></p>
            <p v-if="opp.scale" style="margin: 4px 0; font-size: 13px;">规模：{{ opp.scale }}</p>
            <p v-if="opp.products" style="margin: 4px 0; font-size: 13px;">产品：{{ opp.products }}</p>
            <p v-if="opp.insight" style="margin: 4px 0; font-size: 13px;">解读：{{ opp.insight }}</p>
            <p v-if="opp.action" style="margin: 4px 0; font-size: 13px;">建议：{{ opp.action }}</p>
          </div>
        </div>
        <div v-if="previewContent.recommendations">
          <h3>重点关注与建议</h3>
          <p>{{ previewContent.recommendations }}</p>
        </div>
      </div>
    </el-card>

    <!-- 历史报告 -->
    <el-card shadow="never">
      <template #header><strong>历史报告</strong></template>
      <el-table :data="reports" v-loading="loading">
        <el-table-column prop="report_type" label="类型" width="80">
          <template #default="{ row }">
            <el-tag size="small">{{ typeLabel(row.report_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间范围" width="200">
          <template #default="{ row }">{{ row.period_start }} ~ {{ row.period_end }}</template>
        </el-table-column>
        <el-table-column prop="generated_at" label="生成时间" width="180" />
        <el-table-column label="商机数" width="80">
          <template #default="{ row }">{{ row.content?.stats?.total || row.opportunity_ids?.length || 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="handlePreview(row)">预览</el-button>
            <el-button size="small" type="success" @click="handleExportExisting(row)">导出</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { apiClient, type ReportItem, type ReportContent } from '../api/client'

const form = ref({
  reportType: 'weekly',
  lines: [] as string[],
})
const dateRange = ref<[string, string] | null>(null)
const generating = ref(false)
const loading = ref(false)
const previewContent = ref<ReportContent | null>(null)
const reports = ref<ReportItem[]>([])

function typeLabel(t: string) {
  return { daily: '日报', weekly: '周报', monthly: '月报' }[t] || t
}

async function handleGenerate() {
  if (!dateRange.value) {
    ElMessage.warning('请选择时间范围')
    return
  }
  generating.value = true
  try {
    const resp = await apiClient.generateReport({
      report_type: form.value.reportType,
      date_from: dateRange.value[0],
      date_to: dateRange.value[1],
      business_lines: form.value.lines.length ? form.value.lines : undefined,
    })
    previewContent.value = resp.data.content
    ElMessage.success('报告生成成功')
    await fetchReports()
  } catch {
    ElMessage.error('生成失败')
  } finally {
    generating.value = false
  }
}

function handlePreview(report: ReportItem) {
  previewContent.value = report.content
}

function handleExport(_format: string) {
  // 用最新生成的报告 ID 导出（从 reports 列表第一条获取）
  if (reports.value.length > 0) {
    window.open(apiClient.exportReportUrl(reports.value[0].id, 'docx'), '_blank')
  }
}

function handleExportExisting(report: ReportItem) {
  window.open(apiClient.exportReportUrl(report.id, 'docx'), '_blank')
}

async function fetchReports() {
  loading.value = true
  try {
    const resp = await apiClient.getReports()
    reports.value = resp.data.items
  } finally {
    loading.value = false
  }
}

onMounted(() => fetchReports())
</script>
```

- [ ] **Step 3: 路由 + 菜单 + 构建 + Commit**

router 添加: `{ path: '/reports', name: 'reports', component: () => import('../views/ReportView.vue') }`
App.vue 菜单添加（用 `Document` 或 `Tickets` 图标）:
```vue
<el-menu-item index="/reports">
  <el-icon><Tickets /></el-icon>
  <span>报告</span>
</el-menu-item>
```

Run: `cd web/frontend && npm run build` → 必须通过

```bash
git add web/frontend/
git commit -m "feat: 报告页 — 参数选择 + 预览 + Word 导出 + 历史报告"
```

---

## Task 6: 端到端验证 + 实施文档

- [ ] **Step 1: 端到端测试**

```python
# tests/e2e/test_report_e2e.py
"""报告端到端测试。"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Opportunity


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    Opportunity.create(
        title="测试商机", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-08",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_report_frontend_contract(client):
    """验证前端报告页用到的 API 都存在。"""
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "title": "周报", "summary": "概要", "sections": [],
        "recommendations": "", "stats": {"total": 1},
    }
    with patch("web.api.reports.LLMClient", return_value=mock_llm):
        # 生成
        resp = client.post("/api/reports/generate", json={
            "report_type": "weekly", "date_from": "2026-07-04", "date_to": "2026-07-10",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "report_id" in data
        assert "content" in data
        report_id = data["report_id"]

    # 列表
    resp = client.get("/api/reports")
    assert resp.json()["total"] >= 1

    # 详情
    resp = client.get(f"/api/reports/{report_id}")
    assert resp.status_code == 200

    # 导出
    resp = client.get(f"/api/reports/{report_id}/export?format=docx")
    assert resp.status_code == 200
```

- [ ] **Step 2: 运行 + Commit + 实施文档**

Run: `pytest tests/ -v` → 83 passed

Commit test + write `docs/impl/increment4-report.md`.

---

## 完成标准

1. ✅ `pytest tests/ -v` 全部通过
2. ✅ 前端 `npm run build` 无错误
3. ✅ 报告生成 → 预览 → Word 导出全流程可用
4. ✅ 每个 Task 有 commit
