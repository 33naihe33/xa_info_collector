# tests/analyzer/test_rules_loader.py
from analyzer.rules_loader import load_opp_rules, load_prompt, get_pre_filter_keywords, get_model_name

def test_load_opp_rules_has_business_lines():
    rules = load_opp_rules()
    assert "business_lines" in rules
    assert "corporate" in rules["business_lines"]

def test_load_opp_rules_has_opportunity_types():
    rules = load_opp_rules()
    assert "opportunity_types" in rules
    assert "corporate_construction" in rules["opportunity_types"]

def test_pre_filter_keywords_nonempty():
    keywords = get_pre_filter_keywords()
    assert len(keywords) > 0
    assert any("项目" in kw for kw in keywords)

def test_load_prompt_extract_entities():
    prompt = load_prompt("extract_entities")
    assert "实体" in prompt
    assert "JSON" in prompt

def test_load_prompt_judge_opportunity():
    prompt = load_prompt("judge_opportunity")
    assert "商机" in prompt
    assert "business_line" in prompt

def test_get_model_name():
    assert get_model_name() == "glm-4-flash"
