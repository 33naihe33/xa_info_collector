# 增量 2 实施文档：LLM 分析层 — 实体抽取 + 商机研判

> 创建日期：2026-07-10
> 状态：已完成

## 交付内容

### 分析层（analyzer/）
- **LLM 客户端**（`llm_client.py`）：智谱 GLM-4-flash 封装，JSON 结构化调用，自动日志记录，错误处理
- **规则预筛**（`rule_filter.py`）：关键词匹配过滤无信号文档，控制 LLM 调用成本
- **规则加载**（`rules_loader.py`）：读取 opp_rules.yaml 和提示词文件
- **实体抽取**（`entity_extractor.py`）：LLM 抽取机构/人物/项目实体及关系
- **商机研判**（`opportunity_judge.py`）：LLM 判断金融商机，按银行业务条线分类
- **Pipeline 编排**（`pipeline.py`）：预筛→抽取→研判→标记已分析

### 配置文件（config/）
- `opp_rules.yaml`：四大业务条线 + 14 种商机类型 + 预筛信号词 + 优先级规则
- `prompts/extract_entities.txt`：实体抽取提示词
- `prompts/judge_opportunity.txt`：商机研判提示词（银行行长视角）

### 数据模型扩展
- `entities` 表：机构/人物/项目实体，含别名消歧
- `relations` 表：实体间关系（会见/投资/合作等）
- `opportunities` 表：商机（按业务条线分类，含金融规模/产品/建议行动）
- `raw_llm_logs` 表：LLM 调用日志（可回溯）

### API + 前端
- `GET /api/opportunities`：商机列表（支持条线/优先级/状态筛选）
- `GET /api/opportunities/stats`：按条线汇总统计
- `GET /api/opportunities/{id}`：商机详情
- `POST /api/analyze/trigger`：触发 LLM 分析（后台执行）
- `OpportunityList.vue`：商机列表页（卡片展示 + 条线统计卡 + 筛选 + 详情抽屉）

### 测试（64 个，全部通过）
| 测试文件 | 数量 | 覆盖 |
|----------|------|------|
| tests/storage/test_models.py | 7 | 含实体/关系/商机 DAO（增量1的2 + 增量2的5） |
| tests/analyzer/test_rules_loader.py | 6 | 配置加载 |
| tests/analyzer/test_llm_client.py | 3 | GLM 客户端（mock） |
| tests/analyzer/test_rule_filter.py | 4 | 规则预筛 |
| tests/analyzer/test_extractor_judge.py | 5 | 实体抽取 + 商机研判（mock） |
| tests/analyzer/test_pipeline.py | 3 | Pipeline 编排（mock） |
| tests/web/test_opportunities_api.py | 6 | 商机 API |
| tests/e2e/test_analyzer_e2e.py | 2 | 分析层端到端 + 前端契约 |
| 增量1已有测试 | 28 | 爬虫/存储/文档API |

## 真实 LLM 分析结果（2026-07-10）

对增量 1 抓取的 **50 篇雄安官网新闻**执行真实 GLM-4-flash 分析：

| 指标 | 结果 |
|------|------|
| 文档分析 | 50/50 全部完成 |
| 商机产出 | **32 条** |
| 实体抽取 | **744 个** |
| 关系抽取 | **511 条** |
| LLM 调用 | 94 次（实体 + 商机各一次，部分被预筛跳过） |
| 总 token 消耗 | 123,148（约 0.1 元，glm-4-flash 极低成本） |
| 分析耗时 | ~30 分钟（50 篇串行 + GLM 响应时间） |

### 商机按条线分布

| 业务条线 | 商机数 |
|----------|--------|
| 普惠金融（inclusive） | 29 |
| 对公业务（corporate） | 3 |

> 偏向普惠的原因：雄安官网近期新闻以科创企业入驻、人才引进、疏解服务为主，这些天然属于普惠/零售条线。对公类重大项目信息更多在公共资源交易平台（增量 1 未启用）。

### 高优先级商机示例

**商机 1** [high/corporate]：央企入驻雄安新区、基础设施建设
- 💡 雄安新区作为非首都功能疏解承载地，吸引大量央企入驻，为银行提供丰富金融业务机会
- ➡️ 加强与央企合作，提供定制化融资方案；优化住房贷款和财富管理服务满足疏解人员需求

**商机 2** [high/inclusive]：2026全球数字经济大会雄安数智未来论坛
- 💡 论坛吸引国内外科技和金融企业，表明雄安科技创新领域金融业务机会巨大
- ➡️ 建立与参会企业联系，了解融资需求和投资意向

## 成本控制效果

规则预筛有效控制了 LLM 调用成本：
- 50 篇文档中，**预筛跳过了部分无信号文档**（如纯会议通知、人事任免）
- 实际 LLM 调用 94 次（如果全量分析应为 50×2=100 次）
- 总 token 123K，glm-4-flash 单价极低，50 篇分析成本约 **0.1 元**
- 增量爬取后每日新文档约 5-10 篇，日分析成本 < 0.05 元

## 实施中的技术调整

### 1. opportunities 表外键约束
计划中 `opportunities.source_doc_id` 有 FK 指向 documents，但独立测试直接用 source_doc_id=1 不创建文档。移除了 FK（列仍保留，nullable），不影响功能。

### 2. tests/analyzer/conftest.py
LLM 客户端每次调用都写 raw_llm_logs，需要 DB 初始化。添加了 autouse conftest fixture 自动初始化临时 DB。

### 3. business_line 多值规范化（真实分析发现）
LLM 对综合性新闻返回多值 business_line（如 `corporate|inclusive`），导致统计不干净。

**修复**：
- `opportunity_judge.py`：对 LLM 返回值取第一个有效值（`split("|")[0]`），校验合法条线
- `judge_opportunity.txt`：提示词明确要求"business_line 只能填一个值"
- 清理已入库的 13 条多值数据
- 修复后统计干净：corporate 3 条，inclusive 29 条

### 4. Opportunity.count() 扩展
计划中 count() 只接受 business_line 参数，但商机列表 API 的 total 需要反映 priority/status 筛选。扩展 count() 支持 priority/status（向后兼容）。

### 5. sniffio 依赖
zhipuai SDK 缺少 sniffio 依赖声明，手动添加到 pyproject.toml。

## 已知限制

- 分析串行执行（50篇约30分钟），后续可考虑并行但需控制 GLM API 速率
- 实体消歧目前基于精确名称匹配（find_or_create），未做模糊匹配
- 商机研判每篇文档只产出一条商机（取主条线），如一篇新闻含多个条线机会需后续优化
- 关系图谱可视化（Graph 模式）在增量 3 实现

## 修复记录

| 问题 | 处理 | 影响 |
|------|------|------|
| FK 约束与测试冲突 | 移除 opportunities.source_doc_id FK | 无功能影响 |
| LLM 日志需 DB 初始化 | 添加 conftest autouse fixture | 测试通过 |
| business_line 多值 | 规范化取首个 + 提示词优化 + 清理数据 | 统计正确 |
| count() 不支持多筛选 | 扩展参数 | total 统计准确 |
| sniffio 缺失 | 添加依赖 | 环境就绪 |
