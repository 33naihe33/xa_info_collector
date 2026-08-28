# analyzer/result.py
"""分析子任务统一结果协议。

所有 LLM 驱动的分析子任务（实体抽取、商机研判、领导调研）统一返回
``TaskResult``，便于 pipeline 据此记录 ``analysis_task_states``。

设计原则（仅两态）：
- ``succeeded``：任务正常完成，包括"明确判定无实体/无商机/非领导调研"
  这类成功的分类（payload=None）。
- ``retryable_error``：LLM 调用失败、返回 None、JSON 解析失败，或返回内容
  违反输出合约（非对象、字段类型错误、缺少必需键）。payload 为错误描述。

异常边界：业务逻辑的真正编程错误（如 KeyError、AttributeError）**不应**
被 extractor 捕获，也不应被标为 retryable_error——让其向上抛出，由 pipeline
的兜底 except 记录。只有"LLM 调用 + 结果形状校验"阶段捕获并转为
retryable_error。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel, ValidationError, model_validator

# 合法状态枚举（字符串常量，避免拼写错误）
SUCCEEDED = "succeeded"
RETRYABLE_ERROR = "retryable_error"


# ---- P1-05: LLM 输出合约 schema（字段级校验）----


class EntityLLMResult(BaseModel):
    """extract_entities 的 LLM 输出合约：必需 entities/relations 键（无默认，缺则失败）。"""
    entities: list[dict]
    relations: list[dict]

    model_config = {"extra": "allow"}


class JudgeLLMResult(BaseModel):
    """judge_opportunity 的 LLM 输出合约。

    A-06：is_opportunity=true 时要求 business_line/opp_type 必填（原 true 分支
    缺业务字段仍创建空商机标成功）。
    """
    is_opportunity: bool
    business_line: str | None = None
    opp_type: str | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _require_business_fields_when_true(self):
        if self.is_opportunity:
            if not self.business_line:
                raise ValueError("is_opportunity=true 时 business_line 必填")
            if not self.opp_type:
                raise ValueError("is_opportunity=true 时 opp_type 必填")
        return self


class LeadershipLLMResult(BaseModel):
    """extract_leadership 的 LLM 输出合约。

    A-06：is_leadership_visit=true 时要求 leader_name 必填（原 true 分支缺
    leader_name 仍标成功但不入库）。
    """
    is_leadership_visit: bool
    leader_name: str | None = None

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _require_leader_name_when_true(self):
        if self.is_leadership_visit and not self.leader_name:
            raise ValueError("is_leadership_visit=true 时 leader_name 必填")
        return self


@dataclass
class TaskResult:
    """分析子任务的统一返回类型。

    Attributes:
        status: ``succeeded`` 或 ``retryable_error``
        payload: 成功时为任务相关数据（可为 None，如"判定无商机"）；
                 失败时为错误描述字符串（可选）。
        stats: 可选的任务统计（如 {"entities": 3, "relations": 2}），便于日志。
    """
    status: str
    payload: Any = None
    stats: Optional[dict] = None

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCEEDED

    @property
    def retryable(self) -> bool:
        return self.status == RETRYABLE_ERROR


def ok(payload: Any = None, stats: Optional[dict] = None) -> "TaskResult":
    """构造成功结果。"""
    return TaskResult(SUCCEEDED, payload, stats)


def retryable_error(error: str = "", stats: Optional[dict] = None) -> "TaskResult":
    """构造可重试错误结果。"""
    return TaskResult(RETRYABLE_ERROR, error, stats)


def validate_llm_dict(result: Any, schema: type[BaseModel] | None = None) -> "TaskResult | None":
    """校验 LLM 返回是否为合约要求的 dict（P1-05：含字段级 schema 校验）。

    返回 None 表示校验通过；返回 TaskResult（retryable_error）表示合约不合。
    - result is None 或非 dict → retryable_error
    - schema 提供时，用 Pydantic 校验必需键/类型；缺键或类型错 → retryable_error
    """
    if result is None:
        return retryable_error("LLM returned None")
    if not isinstance(result, dict):
        return retryable_error(f"LLM returned non-dict: {type(result).__name__}")
    if schema is not None:
        try:
            schema(**result)
        except ValidationError as e:
            return retryable_error(f"LLM output contract violation: {e}")
    return None
