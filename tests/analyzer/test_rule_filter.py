# tests/analyzer/test_rule_filter.py
from analyzer.rule_filter import should_analyze

def test_should_analyze_project_news():
    """含项目建设关键词的新闻应分析。"""
    text = "张国华调研启动区重点项目建设工作，推进投资"
    assert should_analyze(text) is True

def test_should_analyze_relocation_news():
    """含疏解搬迁的新闻应分析。"""
    text = "央企总部落户雄安新区，搬迁工作有序推进"
    assert should_analyze(text) is True

def test_should_not_analyze_irrelevant():
    """无关新闻不应分析（省 LLM 成本）。"""
    text = "今天天气晴朗，适合户外运动，公园里花开了"
    assert should_analyze(text) is False

def test_should_not_analyze_empty():
    assert should_analyze("") is False
    assert should_analyze("   ") is False
