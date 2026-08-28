# 雄安信息商机挖掘系统（xa_info_collector）设计文档

> 创建日期：2026-07-10
> 状态：待评审

## 1. 项目概述

### 1.1 目标

从雄安新区各类官方网站自动抓取政务公开信息（领导会见、政策发文、招标采购、疏解落地等），经 LLM 智能分析，挖掘面向**银行分行行长（厅级）**视角的金融业务合作机会，产出可导出的正式报告。

### 1.2 核心用户与场景

| 维度 | 说明 |
|------|------|
| 最终用户 | 银行业地方分行行长（厅级）及其 BD/业务团队 |
| 核心诉求 | 从雄安政务动态中识别融资、存款、获客、政银合作等金融业务机会 |
| 使用场景 | 桌面端深度分析 + 移动端随时查看 + 主动推送获知重要商机 |
| 产出物 | Web 服务（商机列表/关系图谱/报告三模式）+ 可导出 Word/PDF 正式报告 |

### 1.3 设计原则

- **解耦优先**：各模块职责单一、接口清晰，可独立开发测试。试用后调整分类、字段、提示词时改配置不改代码。
- **行长视角**：商机的定义、字段、分类、报告结构均围绕银行业务条线和厅级领导决策习惯设计。
- **配置驱动**：数据源、商机规则、LLM 提示词、推送策略全部外置为 YAML/文本配置文件。

## 2. 整体架构

系统分五个独立模块，数据单向流动：

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   爬虫层     │ ──→ │   存储层     │ ──→ │   分析层     │ ──→ │  推送/报告   │ ──→ │   服务层     │
│  Collector   │     │  Storage     │     │  Analyzer    │     │  Notifier/   │     │   Web UI     │
│             │     │              │     │              │     │  Reporter    │     │              │
│ 各源 adapter │     │ SQLite + FTS │     │ LLM 抽取研判 │     │ 推送+报告生成│     │ FastAPI+Vue  │
│ 定时调度     │     │ 原始快照     │     │ 规则预筛     │     │ Word/PDF导出 │     │ 响应式 PWA   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

**数据流**：爬虫抓原文 → 存原始快照 + 解析结构化字段 → LLM 抽取（实体/关系/商机）→ 触发推送 / 生成报告 → 服务层查询展示。

### 2.1 模块接口边界

| 模块 | 输入 | 输出 | 依赖 |
|------|------|------|------|
| Collector | 数据源配置 | 标准文档（title/url/source/date/raw_html/text） | 无 |
| Storage | 文档 / 查询请求 | 文档 + 抽取结果（按 API 查询） | 无 |
| Analyzer | 文档文本 | 实体 / 关系 / 商机判断 | Storage（读文档写结果） |
| Notifier | 新商机 + 推送规则 | 推送通知 | Storage（读商机） |
| Reporter | 时间范围 + 条线筛选 | 报告内容 / Word / PDF 文件 | Storage + Analyzer（LLM 生成） |
| Web | 用户请求 | 页面数据 / 报告文件 | 以上全部（查询只读） |

每个模块可独立开发和测试——先让爬虫跑通，再接 LLM，最后做前端。

## 3. 数据模型

存储层用 **SQLite**（本地部署、零运维），配合 FTS5 全文索引。

### 3.1 documents（原始文档）

| 字段 | 说明 |
|------|------|
| id | 主键 |
| source | 来源（xiongan_portal / public_resource / xiongan_group / county_provincial） |
| doc_type | 文档类型（新闻 / 招标 / 中标 / 政策 / 疏解公告） |
| title | 标题 |
| url | 原文 URL |
| publish_date | 发布日期 |
| crawled_at | 抓取时间 |
| raw_html | 原始 HTML（快照） |
| text | 正文纯文本 |
| content_hash | 内容哈希（去重用） |

### 3.2 entities（实体——图谱节点）

| 字段 | 说明 |
|------|------|
| id | 主键 |
| name | 名称（如"雄安集团"/"张国华"） |
| type | 类型（机构 / 人物 / 项目） |
| aliases | 别名列表（JSON，用于消歧合并） |
| source_doc_ids | 出现的文档列表（JSON） |
| metadata | 附加信息（JSON，如机构性质/职务） |

### 3.3 relations（关系——图谱边）

| 字段 | 说明 |
|------|------|
| id | 主键 |
| from_entity_id | 起始实体 |
| to_entity_id | 目标实体 |
| relation_type | 关系类型（会见 / 招标 / 中标 / 隶属 / 合作 / 商机关联） |
| source_doc_id | 来源文档 |
| confidence | 置信度 |
| publish_date | 关系发生日期 |

### 3.4 opportunities（商机——核心产出）

| 字段 | 说明 |
|------|------|
| id | 主键 |
| title | 商机标题 |
| source_doc_id | 来源文档 |
| extracted_at | 抽取时间 |
| opp_type | 商机类型（见第 4 节，如 corporate_financing / sme_tech） |
| business_line | 归属业务条线（corporate / inclusive / retail / partnership） |
| fin_scale | 预估金融规模（亿元） |
| fin_products | 适配金融产品（JSON，可跨条线） |
| target_client | 目标客户/主体 |
| buyer_dept | 对接政府部门 |
| relocate_from | 迁出地（疏解落地专属，如"北京"） |
| relocate_scale | 迁移规模（人员/资产/面积） |
| relocate_phase | 疏解阶段（planning / construction / settlement） |
| trigger_event | 触发事件摘要 |
| timing_window | 介入时点建议 |
| insight | LLM 金融视角解读 |
| action_suggest | 建议行动（拜访/方案/上报） |
| priority | 优先级（critical / high / medium / low） |
| status | 状态（signal / tracking / progressing / converted / lost） |
| publish_date | 发布日期 |
| deadline | 截止日期（若有） |

### 3.5 reports（报告）

| 字段 | 说明 |
|------|------|
| id | 主键 |
| report_type | 类型（daily / weekly / monthly） |
| period_start | 周期开始 |
| period_end | 周期结束 |
| generated_at | 生成时间 |
| content | 报告内容（JSON 结构化） |
| docx_path | Word 文件路径 |
| pdf_path | PDF 文件路径 |
| opportunity_ids | 包含的商机 ID 列表（JSON） |

### 3.6 推送相关表

> 用户模型说明：本地/内网部署，采用轻量用户机制。MVP 阶段单用户（一个配置文件定义推送偏好），数据表预留 user_id 字段以便后续扩展为多用户。推送相关表当前以单用户方式使用，user_id 默认值为 "default"。

**push_subscriptions**

| 字段 | 说明 |
|------|------|
| id | 主键 |
| user_id | 用户标识 |
| channel | 通道（web_push / wechat / email） |
| endpoint | 订阅地址 / openid / 邮箱 |
| keys | 加密密钥（JSON，PWA Web Push 用） |
| created_at | 订阅时间 |

**push_settings**

| 字段 | 说明 |
|------|------|
| id | 主键 |
| user_id | 用户标识 |
| instant_enabled | 是否开启即时预警 |
| instant_threshold | 预警阈值（critical / high） |
| daily_limit | 每日即时推送上限 |
| focus_lines | 关注的业务条线（JSON） |
| daily_digest_enabled | 是否开启每日早报 |
| daily_digest_time | 早报时间（如 08:00） |
| weekly_digest_enabled | 是否开启每周摘要 |
| monthly_digest_enabled | 是否开启每月摘要 |
| digest_threshold | 摘要包含的最低优先级 |
| dnd_enabled | 是否开启免打扰 |
| dnd_start / dnd_end | 免打扰时段（如 22:00-07:00） |
| weekend_dnd | 周末免打扰 |

**push_logs**

| 字段 | 说明 |
|------|------|
| id | 主键 |
| user_id | 用户标识 |
| opportunity_id | 关联商机（即时预警时） |
| digest_report_id | 关联报告（定时摘要时） |
| channel | 推送通道 |
| trigger_type | 触发类型（instant / scheduled） |
| title | 推送标题 |
| body | 推送内容 |
| sent_at | 发送时间 |
| delivered | 是否送达 |
| clicked | 是否点击 |
| clicked_at | 点击时间 |

### 3.7 辅助表

- **crawl_errors**：抓取失败记录（source / url / error / timestamp / retried），可重跑。
- **raw_llm_logs**：LLM 每次调用的原始输入/输出/模型/耗时，可回溯和对比提示词效果。

### 3.8 全文搜索

SQLite FTS5 虚拟表建在 documents.text 和 opportunities.title/insight 上，支持前端搜索。

### 3.9 关键设计点

1. **实体消歧**：同一机构多种叫法（"雄安集团"/"中国雄安集团"），用 aliases + 消歧逻辑合并，保证图谱节点不重复。
2. **商机是一等公民**：独立建表，商机列表模式直接读这张表，不藏在文档里。
3. **可追溯**：每条商机/关系记录 source_doc_id，点开回到原文核实。
4. **business_line 字段**：报告按条线归口分章节展示，行长看到直接知道分派给哪个部门。

## 4. 业务条线与商机类型

### 4.1 四大业务条线

同一事件可同时触发多条业务线机会。例如中国星网集团迁入：对公（开户结算融资）+ 普惠（产业链配套中小微）+ 个金（员工代发购房贷）+ 政银（战略合作信号）。

| 条线 | 标识 | 面向 |
|------|------|------|
| 对公业务 | corporate | 大型机构/央企国企/政府平台 |
| 普惠金融 | inclusive | 中小微/个体/科创企业 |
| 个人金融/零售 | retail | 个人客户/居民/职工 |
| 政银合作 | partnership | 政府对接/政策窗口/特色金融 |

### 4.2 商机类型清单

所有类型定义在 `config/opp_rules.yaml`，增删类型只改配置。

| 条线 | 商机类型 | 标识 | 触发信号示例 |
|------|----------|------|-------------|
| 对公 | 重大项目融资 | corporate_financing | 开工/奠基/总投资/建设/扩建 |
| 对公 | 央企国企入驻 | corporate_account | 央企/国企/总部/落户/注册 |
| 对公 | 机构存款 | deposit | 专项资金/资金监管/土地出让金 |
| 对公 | 债券承销 | bond_underwriting | 发债/城投/平台公司 |
| 普惠 | 产业链配套 | sme_supply_chain | 产业链/配套/供应商/上下游 |
| 普惠 | 科创企业 | sme_tech | 科技企业/创新园/孵化器/中关村 |
| 普惠 | 商贸个体 | sme_retail | 商户/个体工商户/商业街/商贸 |
| 普惠 | 本地企业转型 | sme_transform | 搬迁/升级/改造/转产 |
| 个金 | 代发工资 | payroll | 招聘/用工/就业/职工/工人 |
| 个金 | 个人住房贷款 | mortgage | 商品房/共有产权/安置房/保障房/交房 |
| 个金 | 财富管理 | wealth | 高净值/居民收入/人才引进/落户 |
| 个金 | 消费/经营贷 | consumer_loan | 居民消费/个体经营 |
| 政银 | 战略合作 | partnership_deal | 战略合作/签约/会见.*银行/框架协议 |
| 政银 | 政策窗口 | partnership_policy | 数字人民币/智慧城市/专项债/绿色/低碳 |

> **疏解落地的特殊处理**：疏解落地不是独立的商机类型，而是一类高价值事件。它在 opp_rules.yaml 中按 relocate_phase 映射到不同条线的商机类型和行动建议：
> - **planning（选址规划期）**→ 触发 corporate_account + partnership_deal，建议"上报总行，跟踪选址动态，投行咨询介入"
> - **construction（建设期）**→ 触发 corporate_financing，建议"对接基建融资需求，准备项目贷/保函方案"
> - **settlement（入驻期）**→ 触发 payroll + sme_supply_chain + wealth，建议"全力争取代发工资和结算资格，跟进产业链配套中小企业"
>
> 每条疏解落地商机记录 relocate_from / relocate_scale / relocate_phase 三个专属字段，便于追踪迁移进度和对应阶段的金融需求变化。

## 5. 爬虫层（Collector）

### 5.1 架构

```
Scheduler（APScheduler，每日凌晨触发，支持手动触发）
    │
    ▼
BaseAdapter（抽象基类：fetch_list → fetch_detail → normalize）
    │
    ├── XionganPortalAdapter     中国雄安官网
    ├── PublicResourceAdapter    公共资源交易平台
    ├── XionganGroupAdapter      雄安集团采购平台
    └── CountyProvincialAdapter  县区 + 省级政府
    │
    ▼
Deduper + RateLimiter（框架内置）
    │
    ▼
documents 表 + snapshots/
```

### 5.2 BaseAdapter 接口

```python
class BaseAdapter(ABC):
    source_name: str  # 数据源标识

    def fetch_list(self, since) -> list[ListItem]:
        """抓取列表页，返回标题/URL/日期，只取 since 之后的新条目"""

    def fetch_detail(self, url) -> RawDoc:
        """抓取详情页，返回原始 HTML + 正文文本"""

    def normalize(self, raw) -> Document:
        """统一格式化为标准 Document"""
```

框架内置（各 adapter 不用实现）：去重（content_hash）、限速（每源可配 QPS）、重试（失败 3 次记入 crawl_errors）、遵守 robots.txt。

### 5.3 数据源策略

| 数据源 | 内容 | 价值 | 技术 |
|--------|------|------|------|
| 中国雄安官网 | 雄安新闻、新闻发布会、领导活动、政务公开 | 领导会见（政银信号）、政策发布、重大事件 | requests + BeautifulSoup |
| 公共资源交易平台 | 招标公告、中标公示、采购需求 | 项目融资机会、甲方信息 | requests，动态加载则 Playwright |
| 雄安集团采购 | 集团及子公司采购/招标 | 平台公司动态，存款+融资 | 逐一适配多平台 |
| 县区 + 省级 | 雄县/容城/安新政府、河北省政府/发改委 | 本地企业转型（普惠）、上级政策 | 关键词过滤涉雄安内容 |

### 5.4 健壮性

- **增量抓取**：只取上次成功后的新内容。
- **去重**：content_hash，同一篇不重复入库。
- **限速**：对政府站点礼貌请求，每源可配 QPS。
- **快照**：原始 HTML 存档 `data/snapshots/`，网站改版/删稿可回溯。
- **错误隔离**：单个 adapter 失败不影响其他源继续抓取，错误记入 crawl_errors 可重跑。

## 6. 分析层（Analyzer）

试用后最可能调整的模块。核心设计：**提示词、分类体系、研判规则全部外置为配置，改配置不改代码**。

### 6.1 处理流程

```
文档入库
  │
  ▼
1. 分类预筛（规则层，零成本）
   关键词匹配判断 doc_type + 初步标签
   大部分文档不含商机信号，不调 LLM
  │
  ▼
2. 实体抽取（LLM 调用 #1）
   抽取机构、人物、项目、金额、时间
   输出 entities[] + relations[]
  │
  ▼
3. 商机研判（LLM 调用 #2，核心）
   按 config/opp_rules.yaml 定义的类型和逻辑判断：
   - 是否构成商机？哪个类型？哪个条线？
   - 金融规模？适配产品？优先级？
   - 建议行动？介入时点？
  │
  ▼
4. 入库归档
   商机 → opportunities 表
   实体关系 → entities/relations 表
   LLM 原始输入输出 → raw_llm_logs 表（可回溯）
```

### 6.2 LLM 选型

智谱 GLM，对中文政府公文理解好、价格低、符合本地化需求。通过 llm_client.py 封装，可切换其他模型。

### 6.3 成本控制

- 先规则预筛，只有命中信号的文档才调 LLM。
- 预估每天约 50-100 篇新文档，实际调 LLM 的约 10-20 篇。
- 每次调用的输入输出存 raw_llm_logs，判断出错可回查，调提示词后可对比效果。

### 6.4 外置配置文件

| 文件 | 用途 | 调整频率 |
|------|------|----------|
| config/sources.yaml | 数据源 URL、CSS 选择器、抓取频率 | 偶尔 |
| config/opp_rules.yaml | 商机类型定义、信号词、规模估算、行动建议模板 | **最常改** |
| config/prompts/extract_entities.txt | 实体抽取提示词 | 偶尔 |
| config/prompts/judge_opportunity.txt | 商机研判提示词 | 偶尔 |
| config/prompts/generate_report.txt | 报告生成提示词 | 偶尔 |

## 7. 推送机制（Notifier）

### 7.1 双触发机制

| 触发方式 | 逻辑 | 内容 | 场景 |
|----------|------|------|------|
| 按时间（定时摘要） | Cron 定时 | 汇总型，一段时间内全部商机 | 每日早报/每周周报摘要/每月月报摘要 |
| 按重要程度（即时预警） | 分析完成后立即评估 | 单条即时，高价值商机 | 重大项目开工/重大政策发布 |

### 7.2 优先级 → 推送策略映射

定义在 `config/push_rules.yaml`，可配置。

| 优先级 | 触发条件 | 推送方式 |
|--------|----------|----------|
| critical | 金融规模≥10亿 或 央企总部疏解 | 即时推送（无上限），醒目样式 |
| high | 金融规模 1-10亿 或 政策窗口 或 领导会见金融机构 | 即时推送（每日≤5条上限） |
| medium | 有明确业务价值但量级一般 | 攒入定时摘要，不单独推送 |
| low | 弱信号/远期/信息不全 | 不推送，仅列表可见 |

### 7.3 用户推送偏好

用户在移动端「我的」页面配置（存 push_settings）：
- 即时预警开关 + 预警阈值（critical / high）+ 每日上限 + 关注条线
- 定时摘要开关 + 时间计划（每日/每周/每月）+ 摘要包含阈值
- 免打扰时段 + 周末免打扰

### 7.4 推送通道

| 通道 | 定位 | 技术 |
|------|------|------|
| PWA Web Push | 主要通道，无需 App | VAPID + Web Push API |
| 微信/企业微信 | 可选，最强触达 | 企业微信 API |
| 邮件 | 可选，适合周报/月报 | SMTP，附报告附件 |

### 7.5 防打扰设计

- 每日即时推送上限（默认≤5条）。
- 免打扰时段（夜间/周末可关，攒到下次定时摘要）。
- 去重：同一商机只推一次；同一事件衍生多个商机合并推送。
- 送达+点击追踪（push_logs），长期可优化推送策略。

### 7.6 模块结构

```
notifier/
├── push_manager.py     推送编排（即时/定时两类调度）
├── digest_builder.py   定时摘要内容生成（LLM 汇总）
├── scheduler.py        定时摘要 Cron 调度
└── channels/
    ├── web_push.py     PWA Web Push
    ├── wechat.py       微信/企业微信
    └── email.py        邮件
```

## 8. 报告生成（Reporter）

### 8.1 生成流程

1. 用户选参数：报告类型（日/周/月）+ 时间范围 + 业务条线（可只选某条线出专项）+ 优先级。
2. 点击生成 → LLM 汇总该时段全部商机。
3. Web 内嵌预览。
4. 导出 Word / PDF。

### 8.2 报告结构

```
雄安新区金融业务机会周报
（2026.07.04 - 2026.07.10）

一、本期概要
   本期共监测到商机线索 N 条，其中高优先级 M 条...

二、对公业务机会
   逐条列出，含规模/产品/建议行动

三、普惠金融机会

四、个人金融机会

五、政银合作机会

六、重点关注与建议
   建议本周重点跟进：...
```

按业务条线分章节，各条线部门各取所需。报告内容存 reports.content（JSON），便于复用和二次编辑。

### 8.3 导出格式

- **Word**：python-docx 生成，正式公文排版（封面、目录、正文分章节、表格汇总商机清单），行长可转发/批注/二次编辑。
- **PDF**：从 Word 转换或直接生成，适合存档/打印。

## 9. Web 服务层

### 9.1 技术栈

- 后端：FastAPI（Python）
- 前端：Vue 3 + Vite
- 图谱：ECharts / D3.js 力导向图
- 移动端：响应式 PWA，同一套代码

### 9.2 桌面端三模式

顶部 tab 切换，全局共享时间范围和业务条线筛选。

**模式一：商机列表**（BD 日常高频）
- 卡片流展示，每张卡含优先级/条线/类型/规模/产品/建议行动。
- 多维筛选：条线/类型/优先级/状态/全文搜索。
- 点击卡片展开详情：含原文链接、关联实体小图谱、LLM 研判过程。
- 可手动更新商机状态（signal → tracking → progressing → converted）。

**模式二：关系图谱**（战略分析）
- 全屏力导向图：机构（蓝）/人物（绿）/项目（橙）/商机（红）为节点。
- 关系类型筛选：会见/招标/中标/隶属/合作/商机关联。
- 交互：缩放/拖拽/点击节点弹出详情和关联商机。
- 价值：看清"谁和谁有关系"，发现隐藏的对接路径。

**模式三：报告生成**
- 选参数 → 生成 → 预览 → 导出。详见第 8 节。

### 9.3 移动端

**定位差异**：桌面端是"分析工具"，移动端是"信息触达"。

三个 Tab：
- **商机**：信息流，按时间/优先级排序，下拉刷新，按条线标签快速筛选。点开看详情。
- **报告**：阅读已生成的报告（桌面端生成），移动端优化排版，可转发。
- **我的**：跟进中的商机、标记的重点、推送设置。

裁掉的复杂功能：全屏力导向图谱拖拽、报告生成。商机详情保留简版关系图（静态展示）。

**PWA 特性**：可添加到手机桌面、离线缓存（报告已下载可离线看）、Web Push 推送通知。

### 9.4 API 设计

```
# 商机
GET  /api/opportunities          ?line=&type=&priority=&date_from=&date_to=&q=&compact=
GET  /api/opportunities/{id}     商机详情（含关联实体、原文）
PUT  /api/opportunities/{id}/status   手动更新状态

# 图谱
GET  /api/graph                  ?entity_types=&relation_types=&date_from=&date_to=
    返回 nodes[] + edges[]

# 报告
POST /api/reports/generate       {type, date_from, date_to, lines[], priority[]}
GET  /api/reports                历史报告列表
GET  /api/reports/{id}           报告内容（预览）
GET  /api/reports/{id}/export?format=docx|pdf   下载文件

# 抓取
POST /api/collect/trigger        手动触发抓取
GET  /api/collect/status         抓取状态/上次成功时间

# 移动端
GET  /api/dashboard/today        首页聚合（今日统计 + Top 商机 + 最近报告）

# 推送
POST /api/push/subscribe         PWA Web Push 订阅注册
PUT  /api/push/settings          推送偏好设置
```

## 10. 项目目录结构

```
xa_info_collector/
├── config/
│   ├── sources.yaml          数据源配置
│   ├── opp_rules.yaml        商机研判规则（核心可配置）
│   ├── push_rules.yaml       推送策略配置
│   └── prompts/              LLM 提示词模板
│       ├── extract_entities.txt
│       ├── judge_opportunity.txt
│       └── generate_report.txt
├── collector/                爬虫层
│   ├── base.py               BaseAdapter
│   ├── scheduler.py          定时调度
│   └── adapters/
│       ├── xiongan_portal.py
│       ├── public_resource.py
│       ├── xiongan_group.py
│       └── county_provincial.py
├── storage/                  存储层
│   ├── models.py             数据模型/表定义
│   ├── database.py           SQLite 连接管理
│   └── search.py             FTS5 全文搜索
├── analyzer/                 分析层
│   ├── pipeline.py           处理流程编排
│   ├── rule_filter.py        规则预筛
│   ├── llm_client.py         智谱 GLM 封装
│   └── rules_loader.py       读取 opp_rules.yaml
├── notifier/                 推送模块
│   ├── push_manager.py       推送编排
│   ├── digest_builder.py     定时摘要生成
│   ├── scheduler.py          定时调度
│   └── channels/
│       ├── web_push.py
│       ├── wechat.py
│       └── email.py
├── reporter/                 报告生成
│   ├── generator.py          日报/周报/月报生成
│   └── exporter.py           Word/PDF 导出
├── web/                      服务层
│   ├── app.py                FastAPI 主应用
│   ├── api/                  REST API
│   └── frontend/             Vue 前端
│       └── src/views/
│           ├── OpportunityList.vue   商机列表模式
│           ├── Graph.vue             关系图谱模式
│           ├── Report.vue            报告模式
│           └── mobile/              移动端视图
├── data/
│   ├── xac.db                SQLite 数据库
│   └── snapshots/            原始 HTML 快照
├── tests/
└── pyproject.toml
```

## 11. 技术选型汇总

| 层 | 技术 | 理由 |
|----|------|------|
| 爬虫 | requests + BeautifulSoup / Playwright | 静态页面用 requests，动态加载用 Playwright |
| 存储 | SQLite + FTS5 | 本地部署零运维，全文搜索 |
| LLM | 智谱 GLM（llm_client 封装，可切换） | 中文公文理解好、价格低、本地化 |
| 定时调度 | APScheduler | Python 生态成熟，支持 Cron |
| 报告导出 | python-docx + PDF 转换 | 正式公文排版 |
| 后端 | FastAPI | 异步高性能，自动生成 API 文档 |
| 前端 | Vue 3 + Vite | 响应式 PWA，一套代码桌面+移动 |
| 图谱 | ECharts / D3.js | 力导向图交互 |
| 推送 | VAPID + Web Push API | 无需 App，浏览器原生 |

## 12. 实施顺序

建议分阶段交付，每阶段可独立验证：

1. **阶段一：数据采集** — 爬虫层 + 存储层。先跑通一个数据源（雄安官网），再扩展到四个。
2. **阶段二：LLM 分析** — 分析层。接智谱 GLM，跑通商机研判 pipeline。
3. **阶段三：Web 服务** — 桌面端三模式（商机列表 / 图谱 / 报告）。
4. **阶段四：报告导出** — Word/PDF 生成。
5. **阶段五：移动端** — 响应式 PWA。
6. **阶段六：推送机制** — 即时预警 + 定时摘要。

每阶段完成后可试用反馈，据反馈调整配置（opp_rules.yaml / push_rules.yaml / 提示词）。
