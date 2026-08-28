# 雄安信息商机挖掘系统 — 技术报告

> 版本：2.0 | 日期：2026-07-13
> 代码规模：后端 3271 行 Python / 前端 1786 行 Vue+TS / 119 个测试

---

## 一、系统概述

### 1.1 目标

从雄安新区官方网站和公众号自动抓取政务信息，经 AI 智能分析，挖掘面向银行分行行长（厅级）的金融业务合作机会，按九大业务条线分类，产出正式报告并提供移动端推送。

### 1.2 系统架构

系统分为六个独立模块，数据单向流动：

```
 ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────────┐
 │  爬虫层   │ ──→ │  存储层   │ ──→ │  分析层   │ ──→ │报告/推送层 │ ──→ │   服务层      │
 │Collector │     │ Storage  │     │Analyzer │     │Reporter/ │     │     Web      │
 │          │     │          │     │          │     │Notifier  │     │              │
 │11个数据源 │     │SQLite    │     │GLM-4-flash│    │Word/Push │     │FastAPI+Vue   │
 │增量+限速  │     │12张表     │     │规则预筛   │    │          │     │桌面+移动PWA  │
 │三层去重   │     │FTS全文搜索│    │9条线研判  │    │双触发    │     │条线卡片入口   │
 └──────────┘     └──────────┘    └──────────┘    └──────────┘     └──────────────┘
```

### 1.3 技术栈

| 层 | 技术 | 选型理由 |
|----|------|---------|
| 爬虫 | httpx + BeautifulSoup | SSR 静态 HTML 解析，配合 respx 单元测试 |
| 存储 | SQLite + FTS5 | 本地零运维，单文件，万级文档毫秒响应 |
| LLM | 智谱 GLM-4-flash | 中文公文理解准确，成本极低（142篇分析约0.15元） |
| 后端 | FastAPI | 异步高性能，自动 API 文档 |
| 前端 | Vue 3 + Element Plus + ECharts | 响应式 PWA 一套代码适配桌面/移动 |
| 报告 | python-docx | 正式公文排版 |
| 推送 | pywebpush + VAPID | PWA Web Push 无需安装 App |

---

## 二、爬虫层（Collector）

### 2.1 模块职责

从多个雄安信息源自动抓取政务新闻，去重后存入数据库。

### 2.2 数据源覆盖

| 数据源 | 类型 | URL | 文档数 | 技术方案 |
|--------|------|-----|--------|---------|
| 中国雄安官网 | 网站 | www.xiongan.gov.cn | 50 | JSON datasource API（隐藏接口） |
| 人民雄安网 | 网站 | www.rmxiongan.com | 20 | HTML 列表页解析（人民网模板） |
| 长城新媒体雄安频道 | 网站 | xiongan.hebccw.cn | 16 | HTML 列表页解析（帝国CMS） |
| 容城县政府 | 网站 | www.hbrc.gov.cn | 9 | HTML 列表页解析（党政集群CMS） |
| 雄县政府 | 网站 | www.xiongxian.gov.cn | 20 | HTML 列表页解析（table布局，GBK编码） |
| 安新县政府 | 网站 | www.anxin.gov.cn | 19 | 首页链接解析（列表页JS渲染） |
| 雄安发布 | 公众号 | 搜狗微信搜索 | 8 | 搜狗搜索标题+摘要 |
| 容城发布 | 公众号 | 搜狗微信搜索 | 待触发 | 同上（反爬限制） |
| 雄州之声 | 公众号 | 搜狗微信搜索 | 待触发 | 同上 |
| 雁翎之声 | 公众号 | 搜狗微信搜索 | 待触发 | 同上 |
| 雄安教育发布 | 公众号 | 搜狗微信搜索 | 待触发 | 同上 |

### 2.3 BaseAdapter 抽象基类（collector/base.py）

所有数据源 adapter 继承 `BaseAdapter`，统一抓取流程。

**核心方法：**

```python
class BaseAdapter(ABC):
    def run(self, since=None) -> dict:
        """完整抓取流程：列表→详情→去重→入库"""
```

**run() 执行流程：**

1. 读取 `crawl_runs.last_crawled_date` 作为增量基准
2. 调 `fetch_list(since)` 获取新条目列表
3. 逐条调 `fetch_detail(url)` 获取正文
4. 如果详情页正文为空（如公众号只有摘要），用列表摘要填充
5. `is_duplicate(text)` 去重检查
6. 写入 documents 表 + 保存 HTML 快照
7. 更新 `last_crawled_date` 记录

### 2.4 并发控制（保护目标服务器）

用户明确要求避免对被爬取方造成压力，实现三层保护：

| 保护层 | 实现 | 参数 |
|--------|------|------|
| 单线程顺序 | 禁止任何 async/concurrent/线程池 | — |
| QPS 限速 | `_throttle()` 强制请求间隔 | 官网 qps=2（0.5秒），县政府 qps=1（1秒），公众号 qps=0.2（5秒） |
| 首次全量限制 | INITIAL_BATCH 限制首批抓取量 | 网站20-50条，避免一次性扫1000条 |

```python
def _throttle(self):
    """强制请求间隔，保护目标服务器。每次HTTP请求前必须调用。"""
    elapsed = time.time() - self._last_request
    if elapsed < self._min_interval:
        time.sleep(self._min_interval - elapsed)
    self._last_request = time.time()
```

### 2.5 增量爬取

**原理**：`crawl_runs` 表记录每次成功抓取的最新发布日期（`last_crawled_date`）。下次 `run()` 自动读取此日期作为 `since` 参数，只获取该日期之后的新内容。

```python
def run(self, since=None):
    if since is None:
        since = CrawlRun.get_last_crawled_date(self.source_name)  # 增量基准
    items = self.fetch_list(since=since)  # 只返回 since 之后的新条目
```

### 2.6 三层去重

| 去重层 | 实现 | 原理 |
|--------|------|------|
| content_hash | SHA256(正文)[:16]，UNIQUE 约束 | 相同内容直接拒绝写入 |
| is_duplicate() | 入库前查询 hash 是否存在 | 跳过重复不报错 |
| url UNIQUE | URL 唯一约束 | 同一篇文章不重复入库 |

**实际验证**：142篇文档中0个重复 content_hash。

### 2.7 各 adapter 实现细节

**中国雄安官网（JSON datasource API）**：
探测发现官网有隐藏的 JSON 接口——栏目页 `<ul>` 标签上的 `data="datasource:{hex}"` 属性指向一个返回完整列表（最多1000条）的 JSON 文件。一次请求拿全部列表，无需翻页。

**县政府站（HTML 解析）**：
- 容城/安新：党政集群 CMS，`li.xxgk-comm-line` 列表项
- 雄县：旧版 table 布局，`table.list tr`，需 GBK 编码检测
- 安新：列表页 JS 渲染，改为从首页 `/news/00-` 链接抓取

**微信公众号（搜狗搜索）**：
通过搜狗微信搜索（weixin.sogou.com）间接获取公众号文章标题和摘要。由于反爬限制无法获取完整正文，但摘要足够 LLM 分析。搜索结果为 `div.txt-box` 列表项。

---

## 三、存储层（Storage）

### 3.1 模块职责

SQLite 存储所有结构化数据，提供数据访问接口。

### 3.2 数据库表结构（12张表）

| 表名 | 列数 | 职责 |
|------|------|------|
| documents | 11 | 原始文档（标题/正文/来源/日期/哈希） |
| crawl_errors | 6 | 抓取失败记录（可重跑） |
| crawl_runs | 8 | 抓取运行记录（含增量基准 last_crawled_date） |
| entities | 7 | 实体（机构/人物/项目，含别名消歧） |
| relations | 7 | 实体关系（会见/投资/合作等） |
| opportunities | 21 | 商机（核心产出，9条线分类+金融字段） |
| raw_llm_logs | 10 | LLM 调用日志（可回溯，调提示词后可对比） |
| reports | 9 | 生成的报告（日/周/月报） |
| push_subscriptions | 6 | Web Push 订阅 |
| push_settings | 12 | 用户推送偏好 |
| push_logs | 11 | 推送发送记录 |

### 3.3 连接管理（storage/database.py）

```python
def init_db(db_path="data/xac.db"):
    """初始化连接，幂等（已有连接时不重复初始化）"""
    # check_same_thread=False: FastAPI 请求线程复用连接
    # WAL 模式: 读写并发安全
    # foreign_keys=ON: 外键约束
```

**设计要点**：
- `init_db()` 幂等守卫——测试 fixture 先调用后，FastAPI lifespan 不会覆盖测试临时库
- WAL 模式支持并发读写
- `check_same_thread=False` 允许 FastAPI 线程池访问

### 3.4 DAO 模式

每张表对应一个数据访问对象（DAO），封装 CRUD 操作：

- `Document`: create / get_by_id / list(source, limit, offset) / count / compute_hash
- `Entity`: create / find_or_create（消歧）/ list / get_by_name
- `Opportunity`: create / list(business_line, priority, status) / count
- `CrawlRun`: start / finish / get_last_crawled_date / latest_by_source
- `Report`: create / list / update_files

---

## 四、分析层（Analyzer）

### 4.1 模块职责

对文档进行 LLM 智能分析，抽取实体/关系，研判金融商机，按9条线分类。

### 4.9 处理流程（analyzer/pipeline.py）

```
文档入库
  │
  ▼
1. 规则预筛（rule_filter.py，零成本）
   关键词匹配判断文档是否含商机信号
   不含信号的文档（天气预报/人事任免）直接跳过，不调 LLM
  │
  ▼ （仅命中的文档）
2. 实体抽取（entity_extractor.py，LLM 调用 #1）
   GLM 从正文抽取机构/人物/项目实体及关系
   正文截断到2000字，超长文档(>1500字)跳过实体抽取避免超时
   → 写入 entities + relations 表
  │
  ▼
3. 商机研判（opportunity_judge.py，LLM 调用 #2，核心）
   GLM 按银行行长视角判断：
   - 是否构成商机？
   - 属于9条线中哪一条？（business_line 规范化为单一值）
   - 预估金融规模？适配哪些产品？
   - 金融解读 + 建议行动 + 优先级
   → 写入 opportunities 表
  │
  ▼
4. 推送触发
   如果产出高优先级商机，调用 send_instant_alert() 触发即时预警
   （try/except 包裹，推送失败不影响分析）
  │
  ▼
5. 标记已分析
   documents.is_analyzed = 1
```

### 4.3 九大业务条线

根据用户提供的《数据抓取关键词和事件》文档，定义9条线（替换原4条线）：

| 条线 | 标识 | 关键词类别 | 事件类型示例 |
|------|------|-----------|-------------|
| 对公业务 | corporate | 疏解/产业/建设/合作 | 央企签约入驻、项目开工 |
| 跨境业务 | cross_border | 跨境支付/国际业务/自贸区 | 首次跨境人民币结算 |
| 普惠金融 | inclusive | 中小微/绿色金融/涉农 | 科技企业入驻孵化器 |
| 对私（个金） | retail | 人才/消费/住房/服务 | 人才引进政策发布 |
| 营运条线 | operations | 网点/支付/现金 | 政务平台与银行系统对接 |
| 金融科技 | fintech | 创新平台/技术应用/新基建 | 重点实验室引进 |
| 综合条线 | synergy | 党建/宣传/活动/荣誉 | 党建共建活动 |
| 风控条线 | risk_control | 监管/信用/风险/合规 | 金融科技创新监管试点 |
| 数字人民币 | digital_currency | 应用场景/产品创新/试点推广 | 数币消费券发放 |

全部定义在 `config/opp_rules.yaml`，包含每条线的关键词、信号词、适配产品映射。**改配置不改代码。**

### 4.4 规则预筛（analyzer/rule_filter.py）

**原理**：用正则表达式匹配预定义的关键词，快速判断文档是否值得调 LLM。

```python
def should_analyze(text: str) -> bool:
    for pattern in _get_patterns():  # 从 opp_rules.yaml 加载的正则
        if pattern.search(text):
            return True
    return False
```

**成本控制效果**：142篇文档中部分被预筛跳过（如纯会议通知），实际 LLM 调用173次。

### 4.5 GLM 客户端封装（analyzer/llm_client.py）

```python
class LLMClient:
    def chat_json(self, system, user, doc_id=None, task_type="unknown") -> dict | None:
        """调用 GLM 返回 JSON dict。失败返回 None。"""
        # 1. 使用 response_format={"type": "json_object"} 保证结构化输出
        # 2. 每次调用记录到 raw_llm_logs（prompt/response/tokens/duration）
        # 3. JSON 解析失败返回 None，不崩溃
```

### 4.6 商机研判（analyzer/opportunity_judge.py）

**LLM 提示词**（config/prompts/judge_opportunity.txt）：
- 系统角色："银行分行行长的情报分析助手"
- 列出9条线的详细关键词和事件类型，要求 LLM 进行语义匹配
- 要求 `business_line` 只能填一个值（规范化处理）
- 返回 JSON：is_opportunity / business_line / opp_type / fin_scale / fin_products / insight / action_suggest / priority

**business_line 规范化**：LLM 可能返回 `corporate|inclusive` 多值组合，代码取第一个有效值：
```python
raw_line = result.get("business_line") or "corporate"
business_line = raw_line.split("|")[0].strip()
if business_line not in valid_lines:
    business_line = "corporate"
```

### 4.7 实际分析结果

| 指标 | 数据 |
|------|------|
| 文档总数 | 142篇 |
| 已分析 | 114篇（待分析28篇，进行中） |
| 商机产出 | 63条 |
| 实体抽取 | 1176个 |
| 关系抽取 | 883条 |
| LLM 调用 | 173次 |
| Token 消耗 | ~220K（约0.15元） |

---

## 五、报告层（Reporter）

### 5.1 模块职责

按时间范围和业务条线，用 LLM 汇总商机，生成结构化报告内容，导出 Word 公文。

### 5.2 条线短结论速览（generator.py: generate_line_briefs）

**原理**：按条线分组查询时段内商机，每个有条线商机的条线调 LLM 生成一句话新闻线索摘要。

```
POST /api/reports/line-briefs {date_from, date_to}
  → 查询时段商机 → 按条线分组 → 每条线调 LLM 生成摘要
  → 返回 [{line, label, brief, count}, ...]
```

输出格式：`【新闻线索】普惠金融领域商机活跃，绿色发展、人才交流等多方面进展显著`

### 5.3 完整报告生成（generator.py: generate_report）

**原理**：查询时段内全部商机（可按条线过滤），构建商机摘要传给 LLM，生成结构化报告。

```
POST /api/reports/generate {report_type, date_from, date_to, business_lines}
  → 查询时段商机 → 构建摘要 → LLM 汇总
  → 返回 {title, summary, sections[{line, opportunities}], recommendations}
```

报告结构（按条线分章节）：
```
一、本期概要
二、对公业务机会（逐条：规模/产品/解读/建议）
三、普惠金融机会
...
N、重点关注与建议
```

### 5.4 Word 导出（exporter.py）

**原理**：用 python-docx 将报告 JSON 渲染为正式公文格式 Word 文档。

```python
def export_to_docx(report_content: dict, output_path: str) -> str:
    doc = Document()
    doc.add_heading(title, level=0)          # 标题居中
    doc.add_heading("一、本期概要", level=1)   # 分章节
    for section in sections:
        for opp in section.opportunities:
            doc.add_heading(f"{j}. {opp.title}", level=2)
            doc.add_paragraph(f"预估规模：{opp.scale}")
            # ...
    doc.save(output_path)
```

### 5.5 报告 API

| 端点 | 功能 |
|------|------|
| POST /api/reports/line-briefs | 生成各条线短结论速览 |
| POST /api/reports/generate | 生成完整报告（支持条线勾选） |
| GET /api/reports | 历史报告列表 |
| GET /api/reports/{id} | 报告详情 |
| GET /api/reports/{id}/export?format=docx | 下载 Word |

---

## 六、推送层（Notifier）

### 6.1 模块职责

主动推送商机信息到用户设备，支持双触发机制。

### 6.2 双触发机制

| 触发方式 | 逻辑 | 内容 | 场景 |
|----------|------|------|------|
| 按时间（定时摘要） | 每日/每周定时 | 汇总型 | 早报"今日5条新商机" |
| 按重要程度（即时预警） | pipeline 分析完成后立即评估 | 单条 | "🔴 重大商机：央企落户" |

### 6.3 即时预警四级检查（push_manager.py: send_instant_alert）

```python
def send_instant_alert(opp, user_id="default") -> dict:
    settings = PushSettings.get_or_create(user_id)
    # 1. 优先级阈值：critical/high 触发，medium/low 攒入摘要
    if not settings.should_send_instant(opp.priority):
        return {"sent": False, "reason": "below_threshold"}
    # 2. 去重：同一商机只推一次
    if PushLog.already_sent(user_id, opp.id):
        return {"sent": False, "reason": "duplicate"}
    # 3. 免打扰：夜间不推送（支持跨午夜 22:00-07:00）
    if settings.is_dnd_now():
        return {"sent": False, "reason": "dnd"}
    # 4. 每日上限：默认≤5条
    if today_count >= settings.daily_limit:
        return {"sent": False, "reason": "daily_limit"}
    # 发送
    _send_to_user(user_id, title, body, opp.id)
```

### 6.4 推送通道

PWA Web Push（VAPID 协议）：浏览器/添加到桌面后收到系统级通知，无需安装 App。开发环境自动生成 VAPID 密钥。

### 6.5 pipeline 集成

分析 pipeline 每产出一条商机，自动调用 `send_instant_alert(opp)` 评估推送：
```python
if opp:
    try:
        from notifier.push_manager import send_instant_alert
        send_instant_alert(opp)
    except Exception as e:
        logger.warning(f"Push failed: {e}")  # 推送失败不影响分析
```

---

## 七、服务层（Web）

### 7.1 模块职责

提供 Web 界面，桌面端和移动端展示商机/报告/数据源状态。

### 7.2 后端 API（7个路由模块）

| 模块 | 端点数 | 功能 |
|------|--------|------|
| documents | 2 | 文档列表/详情 |
| collect | 4 | 抓取触发/状态/数据源列表/分析触发 |
| opportunities | 3 | 商机列表/统计/详情 |
| reports | 5 | 短结论/生成/列表/详情/导出 |
| push | 5 | 订阅/设置/统计/VAPID公钥 |
| graph | 1 | 图谱数据（保留，前端已下线） |

### 7.3 前端桌面端（4个页面）

| 页面 | 功能 |
|------|------|
| 商机列表（OpportunityList.vue） | **9条线卡片入口** → 点击进入条线商机列表 |
| 报告（ReportView.vue） | 条线短结论速览 + 完整报告生成（条线勾选）+ Word导出 |
| 信息源状态（SourceStatus.vue） | 11个数据源表格 + 立即抓取 |
| 文档列表（DocumentList.vue） | 142篇文档 + 筛选 + 正文预览 |

**条线卡片入口设计**：
- 9个条线卡片网格（3列），每卡含图标+颜色+商机数
- 点击进入该条线商机列表（淡入淡出过渡）
- 返回按钮回到卡片总览

### 7.4 前端移动端（3个 Tab）

| Tab | 页面 | 功能 |
|-----|------|------|
| 商机 | MobileOpportunities.vue | 信息流卡片 + 筛选 + 详情（底部弹出） |
| 报告 | MobileReports.vue | 报告列表 + 阅读（底部弹出） |
| 我的 | MobileSettings.vue | 推送偏好设置 |

### 7.5 PWA 配置

vite-plugin-pwa 实现：
- manifest.webmanifest：应用名/图标/主题色
- Service Worker：离线缓存（API 响应 NetworkFirst 策略，5分钟过期）
- 可安装到手机桌面

### 7.6 响应式布局切换

`useDevice.ts` composable 检测屏幕宽度：
```typescript
const isMobile = ref(false)
function check() {
    isMobile.value = window.innerWidth < 768  // 断点
}
```
`App.vue` 根据 `isMobile` 切换 `DesktopLayout` / `MobileLayout`，路由守卫自动重定向。

### 7.7 端到端一致性保障

用户要求"不出现后台功能前台未实现或前台 icon 无后台接口"：

| 保障机制 | 实现 |
|----------|------|
| API 测试 | 每个端点有独立单元测试（tests/web/） |
| E2E 契约测试 | 前端每个 API 调用有契约校验（tests/e2e/） |
| TypeScript 类型检查 | 前端构建含 vue-tsc，编译期保证 API 契约 |
| 前后端类型同步 | client.ts 定义所有接口类型，与后端 pydantic 模型对应 |

---

## 八、配置层

### 8.1 配置驱动设计

所有可变逻辑外置为配置文件，**改配置不改代码**：

| 文件 | 用途 | 调整场景 |
|------|------|---------|
| config/sources.yaml | 11个数据源配置（URL/QPS/启用状态） | 增删数据源 |
| config/opp_rules.yaml | 9条线规则（关键词/信号词/产品映射/预筛词） | 调整商机分类（最常改） |
| config/push_rules.yaml | 推送策略（优先级映射/定时计划/防打扰） | 调推送阈值 |
| config/prompts/extract_entities.txt | 实体抽取提示词 | 调抽取效果 |
| config/prompts/judge_opportunity.txt | 商机研判提示词（含9条线全部关键词和事件） | 调研判效果 |
| config/prompts/generate_report.txt | 报告生成提示词 | 调报告风格 |

---

## 九、测试体系

### 9.1 测试覆盖（119个测试）

| 层 | 测试数 | 覆盖 |
|----|--------|------|
| 存储 | 16 | 12张表 CRUD + 去重约束 + 偏好判断 |
| 爬虫 | 24 | 6个网站adapter + 去重 + 增量 + 配置加载 |
| 分析 | 21 | 规则加载 + GLM客户端 + 预筛 + 抽取 + 研判 + pipeline |
| 报告 | 4 | 报告生成 + Word导出 |
| 推送 | 14 | WebPush通道 + 双触发 + 防打扰 + 去重 |
| Web API | 27 | 全部API端点 |
| E2E | 9 | 前后端一致性 + 完整业务流程 |
| 爬虫集成 | 4 | 完整抓取→入库→列表 |

### 9.2 真实验证数据

| 验证项 | 结果 |
|--------|------|
| 6个网站抓取 | 134篇文档，0错误 |
| 公众号抓取 | 雄安发布8篇（搜狗反爬限制） |
| LLM 分析 | 63商机/1176实体/883关系/173次调用 |
| 去重验证 | 142篇中0重复 |
| 增量爬取 | 第二次抓取0新增（正确） |
| 并发控制 | QPS限速生效，无服务器压力 |

---

## 十、已知限制与后续优化

| 项目 | 现状 | 优化方向 |
|------|------|---------|
| 公众号抓取稳定性 | 搜狗反爬限制，频繁搜索被临时封IP | 考虑企业微信API或第三方聚合服务 |
| 分析速度 | 每篇约1-5分钟（GLM API响应时间） | 并行调用（需控速）、跳过超长文档实体抽取 |
| LLM 分析完整性 | 142篇中待分析28篇（进行中） | 等待完成 |
| 定时调度 | 需手动触发抓取和分析 | 接入 APScheduler 每日自动运行 |
| 实体消歧 | 精确名匹配（find_or_create） | 模糊匹配/别名合并 |
| 推送实际触达 | 逻辑已实现，需真实VAPID密钥+浏览器订阅 | 生产环境配置 |
| 多用户 | 表结构预留user_id，未实现认证 | 后续加认证层 |
