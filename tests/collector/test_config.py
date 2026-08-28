from collector.config import load_sources_config, get_source_config

def test_load_sources_has_portal():
    sources = load_sources_config()
    assert "xiongan_portal" in sources
    assert sources["xiongan_portal"]["name"] == "中国雄安官网"

def test_portal_has_categories():
    cfg = get_source_config("xiongan_portal")
    assert "zxyw" in cfg["categories"]
    assert cfg["categories"]["zxyw"]["datasource_path"] is not None

def test_unknown_source_raises():
    import pytest
    with pytest.raises(KeyError):
        get_source_config("nonexistent")
