# analyzer/rule_filter.py
"""规则预筛：用关键词快速判断文档是否值得调 LLM 分析。

大部分政务新闻（会议通知、人事任免等）不含商机信号，
跳过它们可大幅降低 LLM 调用成本。
"""
import re

from analyzer.rules_loader import get_pre_filter_keywords

# 编译正则（模块级缓存）
_patterns: list[re.Pattern] | None = None


def _get_patterns() -> list[re.Pattern]:
    global _patterns
    if _patterns is None:
        keywords = get_pre_filter_keywords()
        _patterns = [re.compile(kw) for kw in keywords]
    return _patterns


def should_analyze(text: str) -> bool:
    """判断文档是否含商机信号关键词，决定是否调 LLM。"""
    if not text or not text.strip():
        return False
    for pattern in _get_patterns():
        if pattern.search(text):
            return True
    return False
