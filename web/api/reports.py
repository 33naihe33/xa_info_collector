"""报告 API：生成/列表/详情/导出。"""
import json
import os
from datetime import datetime as _dt

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from storage.models import Report, Opportunity
from reporter.generator import generate_report, generate_line_briefs
from reporter.exporter import export_to_docx
from analyzer.llm_client import LLMClient

router = APIRouter()

_VALID_REPORT_TYPES = {"daily", "weekly", "monthly"}


class GenerateReportRequest(BaseModel):
    report_type: str  # daily / weekly / monthly
    date_from: str
    date_to: str
    business_lines: list[str] | None = None

    # F-15：输入校验
    @field_validator("report_type")
    @classmethod
    def _valid_report_type(cls, v):
        if v not in _VALID_REPORT_TYPES:
            raise ValueError(f"report_type 必须是 {sorted(_VALID_REPORT_TYPES)} 之一")
        return v

    @field_validator("date_from", "date_to")
    @classmethod
    def _valid_date_format(cls, v):
        try:
            _dt.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须为 YYYY-MM-DD")
        return v

    def _date_order_ok(self):
        return self.date_from <= self.date_to


@router.post("/reports/generate")
def generate_report_api(req: GenerateReportRequest):
    """生成报告（同步执行）。"""
    # F-15：date_from <= date_to
    if not req._date_order_ok():
        raise HTTPException(status_code=422, detail="date_from 必须早于或等于 date_to")
    llm_client = LLMClient()

    content = generate_report(
        report_type=req.report_type,
        period_start=req.date_from,
        period_end=req.date_to,
        llm_client=llm_client,
        business_lines=req.business_lines,
    )

    # F-12：查询包含的商机 ID（SQL 层日期/条线过滤，无 limit 截断）
    opps = Opportunity.list_for_period(
        date_from=req.date_from, date_to=req.date_to,
        business_lines=req.business_lines or None,
    )
    opp_ids = [o.id for o in opps]

    report = Report.create(
        report_type=req.report_type,
        period_start=req.date_from,
        period_end=req.date_to,
        content=json.dumps(content, ensure_ascii=False),
        opportunity_ids=json.dumps(opp_ids),
    )
    return {"report_id": report.id, "content": content}


class LineBriefsRequest(BaseModel):
    date_from: str
    date_to: str

    # M-03：与 GenerateReportRequest 一致的日期校验
    @field_validator("date_from", "date_to")
    @classmethod
    def _valid_date_format(cls, v):
        try:
            _dt.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须为 YYYY-MM-DD")
        return v


@router.post("/reports/line-briefs")
def generate_line_briefs_api(req: LineBriefsRequest):
    """生成各条线短结论预览（快速浏览）。"""
    # M-03：date_from <= date_to
    if req.date_from > req.date_to:
        raise HTTPException(status_code=422, detail="date_from 必须早于或等于 date_to")
    from reporter.generator import generate_line_briefs as _gen
    llm_client = LLMClient()
    briefs = _gen(
        period_start=req.date_from,
        period_end=req.date_to,
        llm_client=llm_client,
    )
    return {"briefs": briefs}


@router.get("/reports")
def list_reports(limit: int = Query(20, ge=1, le=100)):
    reports = Report.list(limit=limit)
    # F-21：total 返回真实总数（原 len(reports) = 页长度）
    return {"total": Report.count(), "items": [r.to_dict() for r in reports]}


@router.get("/reports/{report_id}")
def get_report(report_id: int):
    report = Report.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report.to_dict()


@router.post("/reports/{report_id}/generate-file")
def generate_report_file(report_id: int):
    """预生成 Word 文件到磁盘，返回文件信息。"""
    report = Report.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    content = json.loads(report.content) if report.content else {}
    # A-02: 用统一 DATA_DIR 派生报告路径
    from storage.paths import reports_dir
    os.makedirs(reports_dir(), exist_ok=True)
    output_path = os.path.join(reports_dir(), f"report_{report.id}.docx")
    export_to_docx(content, output_path)
    report.update_files(docx_path=output_path)

    file_size = os.path.getsize(output_path)
    return {"report_id": report.id, "file_path": output_path, "file_size": file_size,
            "download_url": f"/api/reports/{report.id}/download"}


@router.get("/reports/{report_id}/download")
def download_report_file(report_id: int):
    """下载已生成的 Word 文件。"""
    report = Report.get_by_id(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # A-02: 用统一 DATA_DIR 派生报告路径
    from storage.paths import reports_dir
    output_path = report.docx_path or os.path.join(reports_dir(), f"report_{report.id}.docx")
    if not os.path.exists(output_path):
        # 文件不存在则生成
        content = json.loads(report.content) if report.content else {}
        os.makedirs(reports_dir(), exist_ok=True)
        export_to_docx(content, output_path)
        report.update_files(docx_path=output_path)

    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"{report.report_type}_{report.period_start}_{report.period_end}.docx",
    )


@router.get("/reports/{report_id}/export")
def export_report(report_id: int, format: str = Query("docx")):
    """导出报告文件（兼容旧接口）。"""
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
