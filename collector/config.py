from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"

def load_sources_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("sources", {})

def get_source_config(source_name: str) -> dict:
    sources = load_sources_config()
    if source_name not in sources:
        raise KeyError(f"Unknown source: {source_name}")
    return sources[source_name]
