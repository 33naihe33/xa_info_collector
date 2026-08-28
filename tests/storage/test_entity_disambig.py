# tests/storage/test_entity_disambig.py
"""实体消歧增强测试：模糊匹配 + 别名合并。"""
import pytest
from storage.models import init_db, close_db, Entity


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_exact_name_match():
    """精确名称匹配不创建新实体。"""
    e1 = Entity.find_or_create("雄安集团", "机构")
    e2 = Entity.find_or_create("雄安集团", "机构")
    assert e1.id == e2.id


def test_alias_match():
    """别名匹配：已有实体的别名能被找到。"""
    # 创建带别名的实体
    Entity.create(name="中国雄安集团", entity_type="机构", aliases='["雄安集团"]')
    # 通过别名查找
    matched = Entity.get_by_alias("雄安集团")
    assert matched is not None
    assert matched.name == "中国雄安集团"


def test_find_or_create_adds_alias():
    """find_or_create 模糊匹配后自动添加别名。"""
    # 创建"中国雄安集团"
    original = Entity.find_or_create("中国雄安集团", "机构")
    # 用短名称查找 → 应模糊匹配到已有实体（"雄安集团"是"中国雄安集团"的子串）
    matched = Entity.find_or_create("雄安集团", "机构")
    assert matched.id == original.id

    import json
    aliases = json.loads(matched.aliases) if matched.aliases else []
    assert "雄安集团" in aliases


def test_fuzzy_match_contains():
    """包含关系模糊匹配。"""
    Entity.find_or_create("中国建设银行", "机构")
    # 短名"建设银行"应匹配到长名"中国建设银行"（后缀去除后包含关系）
    matched = Entity.find_or_create("建设银行", "机构")
    assert matched.name == "中国建设银行"


def test_no_cross_type_merge():
    """不同类型实体不合并（人物"雄安"vs机构"雄安"）。"""
    person = Entity.find_or_create("张国华", "人物")
    # 同名但不同类型应创建新实体
    org = Entity.find_or_create("张国华工作室", "机构")
    assert person.id != org.id


def test_short_name_no_fuzzy():
    """过短名称（<3字）不做模糊匹配，避免误合并。"""
    e1 = Entity.find_or_create("新区", "机构")
    e2 = Entity.find_or_create("新区建设", "机构")
    # "新区"太短不做模糊匹配，应创建不同实体
    assert e1.id != e2.id
