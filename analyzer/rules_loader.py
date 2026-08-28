# analyzer/rules_loader.py
from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_opp_rules() -> dict:
    """加载商机研判规则。"""
    with open(CONFIG_DIR / "opp_rules.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompt(name: str) -> str:
    """加载提示词文件。name: 'extract_entities' 或 'judge_opportunity'。"""
    with open(CONFIG_DIR / "prompts" / f"{name}.txt", encoding="utf-8") as f:
        return f.read().strip()


def get_pre_filter_keywords() -> list[str]:
    """获取规则预筛关键词列表（正则模式）。"""
    rules = load_opp_rules()
    return rules.get("pre_filter_keywords", [])


def get_model_name() -> str:
    """获取配置的模型名。"""
    return load_opp_rules().get("model", "glm-4-flash")
