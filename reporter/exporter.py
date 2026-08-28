"""Word 导出器：用 python-docx 生成正式公文格式报告。"""
import os
import logging
import tempfile

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.shared import OxmlElement, qn

from storage.models import resolve_image_path_for_export

logger = logging.getLogger(__name__)

# 中文序号（用于章节标题）
CN_NUMS = "一二三四五六七八九十"

# 优先级 -> 中文标签
PRIORITY_LABELS = {
    "critical": "极高优先级",
    "high": "高优先级",
    "medium": "中优先级",
    "low": "低优先级",
}


def _format_date(raw: str) -> str:
    """把 publish_date 标准化为 YYYY-MM-DD（截取前10位）。"""
    if not raw:
        return ""
    s = raw.strip()
    return s[:10] if len(s) >= 10 else s


def add_hyperlink(paragraph, url, text, color="0563C1", underline=True):
    """在段落中插入可点击的超链接（python-docx 原生不支持，需操作 XML）。"""
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)
    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    if color:
        c = OxmlElement('w:color')
        c.set(qn('w:val'), color)
        rPr.append(c)
    if underline:
        u = OxmlElement('w:u')
        u.set(qn('w:val'), 'single')
        rPr.append(u)
    new_run.append(rPr)
    t = OxmlElement('w:t')
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def export_to_docx(report_content: dict, output_path: str) -> str:
    """将报告内容导出为 Word 文档。返回文件路径。

    report_content 结构：
    {"title", "summary", "sections": [{"line", "opportunities": [...]}],
     "recommendations", "stats"}
    """
    doc = Document()

    # 设置默认字体
    style = doc.styles['Normal']
    font = style.font
    font.name = 'SimSun'
    font.size = Pt(12)

    # 标题
    title = doc.add_heading(
        report_content.get("title", "雄安新区金融业务机会报告"), level=0
    )
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 概要
    doc.add_heading("一、本期概要", level=1)
    doc.add_paragraph(report_content.get("summary", ""))

    # 统计信息
    stats = report_content.get("stats", {})
    if stats:
        doc.add_paragraph(f"商机总数：{stats.get('total', 0)}")

    # 各条线章节（章节序号从"二"开始，概要占"一"）
    sections = report_content.get("sections", [])
    for i, section in enumerate(sections, start=2):
        line_name = section.get("line", "其他")
        opps = section.get("opportunities", [])
        num = CN_NUMS[i - 1] if i - 1 < len(CN_NUMS) else str(i)
        doc.add_heading(f"{num}、{line_name}（{len(opps)}条）", level=1)

        if not opps:
            doc.add_paragraph("本期暂无相关商机。")
            continue

        for j, opp in enumerate(opps, 1):
            # 优先级标签 + 标题
            priority = opp.get("priority")
            priority_label = PRIORITY_LABELS.get(priority, "") if priority else ""
            p = doc.add_paragraph()
            if priority_label:
                run = p.add_run(f"【{priority_label}】")
                run.bold = True
                # 颜色：high/critical 红色，medium 橙色，low 灰色
                if priority in ("high", "critical"):
                    run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)
                elif priority == "medium":
                    run.font.color.rgb = RGBColor(0xCC, 0x66, 0x00)
                else:
                    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
            title_run = p.add_run(f" {j}. {opp.get('title', '')}")
            title_run.bold = True

            # 发布时间（如有）
            publish_date = opp.get("publish_date")
            if publish_date:
                p = doc.add_paragraph()
                run = p.add_run("发布时间：")
                run.bold = True
                p.add_run(_format_date(publish_date))

            # 领导调研条目同时展示实际调研日期；普通商机没有该字段。
            visit_date = opp.get("visit_date")
            if visit_date:
                p = doc.add_paragraph()
                run = p.add_run("调研时间：")
                run.bold = True
                p.add_run(_format_date(visit_date))

            # 领导调研摘要（仅领导调研板块有此字段）
            if opp.get("summary"):
                p = doc.add_paragraph()
                run = p.add_run("调研摘要：")
                run.bold = True
                p.add_run(opp["summary"])

            # 信息来源（可点击超链接）
            source_url = opp.get("source_url")
            if source_url:
                p = doc.add_paragraph()
                run = p.add_run("信息来源：")
                run.bold = True
                link_text = opp.get("source_name") or "查看原文"
                add_hyperlink(p, source_url, link_text)

            # 原新闻图片（全部展示，有几张放几张）
            for raw_img in opp.get("images", []):
                if not raw_img:
                    continue
                # F-14：图片路径可能是 /images/... API URL 或本地路径，
                # 统一解析为本地文件路径（exporter 专用）
                img_path = resolve_image_path_for_export(raw_img)
                if not img_path:
                    continue
                try:
                    # 获取图片数据（本地或在线）
                    img_data = None
                    if os.path.exists(img_path) and os.path.getsize(img_path) > 1000:
                        with open(img_path, 'rb') as f:
                            img_data = f.read()
                    elif img_path.startswith("http"):
                        import httpx
                        resp = httpx.get(img_path, timeout=30, headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                                          "Chrome/125.0.0.0 Safari/537.36",
                            "Referer": "https://www.xiongan.gov.cn/",
                        }, follow_redirects=True)
                        if resp.status_code == 200 and len(resp.content) > 1000:
                            img_data = resp.content

                    if not img_data:
                        continue

                    # 压缩图片（超过500KB的缩小到1200px宽，JPEG质量85%）
                    try:
                        from PIL import Image
                        from io import BytesIO
                        img = Image.open(BytesIO(img_data))
                        # 缩放到最大1200px宽
                        if img.width > 1200:
                            ratio = 1200 / img.width
                            img = img.resize((1200, int(img.height * ratio)), Image.LANCZOS)
                        # 转为RGB（去掉alpha通道）再保存为JPEG
                        if img.mode in ('RGBA', 'P'):
                            img = img.convert('RGB')
                        buf = BytesIO()
                        img.save(buf, format='JPEG', quality=85)
                        img_data = buf.getvalue()
                    except Exception:
                        pass  # Pillow 处理失败用原图

                    # 写入唯一临时文件再插入
                    tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                    tmp.write(img_data)
                    tmp.close()
                    try:
                        doc.add_picture(tmp.name, width=Inches(4.0))
                    finally:
                        os.unlink(tmp.name)
                except Exception as e:
                    logger.warning(f"Image processing failed for {img_path}: {type(e).__name__}: {e}")

    # 重点关注
    recommendations = report_content.get("recommendations", "")
    if recommendations:
        doc.add_heading("重点关注与建议", level=1)
        doc.add_paragraph(recommendations)

    # 确保目录存在
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    doc.save(output_path)
    return output_path
