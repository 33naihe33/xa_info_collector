# analyzer/entity_extractor.py
"""实体+关系抽取：调用 LLM 从文档中抽取实体和关系，写入数据库。"""
import json
import logging

from analyzer.result import TaskResult, validate_llm_dict, EntityLLMResult, ok, retryable_error
from analyzer.rules_loader import load_prompt
from storage.models import Entity, Relation

logger = logging.getLogger(__name__)


def extract_entities(*, doc_id: int, text: str, llm_client, publish_date: str = "") -> TaskResult:
    """从文档中抽取实体和关系，写入 entities/relations 表。

    返回 TaskResult：
    - ok(stats={"entities": n, "relations": m})：正常完成（含"无实体"的成功分类）
    - retryable_error：LLM 返回 None / 非 dict（输出合约不合）
    注意：业务逻辑的编程错误不在此捕获，向上抛出由 pipeline 兜底。
    """
    system_prompt = load_prompt("extract_entities")
    user_prompt = f"请从以下新闻中抽取实体和关系：\n\n{text[:2000]}"

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        doc_id=doc_id, task_type="extract_entities",
    )
    # 形状校验：None / 非 dict / 缺必需键 → retryable_error（P1-05 字段级 schema）
    bad = validate_llm_dict(result, schema=EntityLLMResult)
    if bad is not None:
        logger.warning(f"Entity extraction contract violation for doc {doc_id}: {bad.payload}")
        return bad

    # 创建实体并记录来源文档
    entity_map = {}  # name → Entity
    for ent_data in result.get("entities", []):
        name = ent_data.get("name", "").strip()
        ent_type = ent_data.get("type", "其他")
        if not name:
            continue
        entity = Entity.find_or_create(name=name, entity_type=ent_type)
        Entity.add_source_doc(entity.id, doc_id)
        entity_map[name] = entity

    # 创建关系（upsert + publish_date）
    relations_count = 0
    for rel_data in result.get("relations", []):
        from_name = rel_data.get("from", "").strip()
        to_name = rel_data.get("to", "").strip()
        rel_type = rel_data.get("type", "").strip()
        if from_name in entity_map and to_name in entity_map:
            Relation.create(
                from_entity_id=entity_map[from_name].id,
                to_entity_id=entity_map[to_name].id,
                relation_type=rel_type,
                source_doc_id=doc_id,
                publish_date=publish_date or None,
            )
            relations_count += 1

    return ok(stats={"entities": len(entity_map), "relations": relations_count})
