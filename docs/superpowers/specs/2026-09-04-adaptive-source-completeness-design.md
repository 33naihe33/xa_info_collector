# 自适应来源完整性修复设计

## 背景与目标

2026-08-29 至 2026-09-04 的多轮核查表明，现有爬取流程可以正常请求和入库，但“运行成功”不等于“日期区间完整”。本次修复的目标是在维持严格限速的前提下，自动扫描到指定日期边界，对不完整运行不推进游标，并对近期内容进行有限重叠回扫。

成功标准：

- 所有支持分页的官方站点都会翻页到 `since` 日期边界，而非只扫首页。
- 日常增量抓取默认向前重叠回扫 3 天，应对延迟发布、置顶和排序变动。
- 只有当来源已达到日期边界或有可验证的穷尽条件时，本次运行才标记为覆盖完整并推进游标。
- 403、429、验证码、异常空页和请求预算耗尽均不会被记为完整。
- 重叠回扫保持幂等，不会重复生成文档。
- 首次自动运行只负责可配置的冷启动窗口，默认最近 7 天；更早历史数据使用显式 `since` 回填。

## 已确认的根因

1. 微信适配器只请求搜狗微信搜索首页，然后再按 `max_results: 10` 截断。当一周发文量超过 10 条时，必然无法覆盖整个日期区间。
2. 中国雄安官网仅抓取已配置 `datasource_path` 的栏目；“通知公告”被直接跳过，从而遗漏普通话测试、知识产权需求等内容。
3. 人民雄安网、长城新媒体以及县级政府适配器普遍只解析首页，没有“翻页直到日期下界”的通用能力。
4. `crawl_runs.status = success` 只表示没有抛出请求或详情异常，并不证明列表已经覆盖到日期边界；当列表被截断时仍会推进游标。
5. 2026-09-04 实测搜狗微信时，请求先以 HTTP 302 跳转到 `/antispider/`，再返回 HTTP 200 验证码页。现有适配器跟随跳转后只看终态 200，将“被拦截的空结果”误记为成功。

## 方案设计

### 1. 统一的覆盖结果

列表抓取不再只返回条目数组，而是同时产生覆盖元数据：

- `items`：去重后的列表条目。
- `boundary_reached`：是否看到早于 `since` 的内容，或已明确穷尽列表。
- `stop_reason`：`date_boundary`、`source_exhausted`、`request_budget`、`blocked`、`invalid_page` 或 `page_limit`。
- `pages_fetched`：实际请求页数。
- `oldest_seen_date` 和 `newest_seen_date`：本次列表扫描的日期范围。

新结果是所有已启用适配器的强制接口。本次修复在同一版本内一次性迁移 `xiongan_portal`、`rmxiongan`、`hebccw`、`rongcheng_gov`、`xiongxian_gov`、`anxin_gov` 和全部微信适配器，在全部合同测试通过前不部署。修复后运行时收到旧的 `list[ListItem]` 属于合同违约：运行记为 `incomplete/invalid_result`，不存在“逐个迁移期间的 unknown 游标冻结”。数据库中的历史运行仍保持 `unknown`，仅作展示，不作为新游标。

### 2. 自适应翻页与请求预算

每个来源配置 `initial_page_budget`、`hard_page_limit`、`max_requests_per_run` 和现有 `qps`。列表页预算可以在连续不完整时自适应提升，但整次运行的列表与详情 HTTP 请求总数不得超过 `max_requests_per_run`。适配器按页串行请求，一旦看到早于日期下界的条目即停止（明确不按时间排序的微信搜索除外）。如果任一预算先耗尽，保留已抓内容，但运行状态记为 `incomplete`，不推进游标。

默认值如下，来源配置可以收紧，但不能超过硬上限：

| 来源类型 | `initial_page_budget` | `hard_page_limit` | `max_requests_per_run` | 限速 |
|---|---:|---:|---:|---|
| 雄安官网 JSON/栏目 | 5 | 20 | 120 | 保留现有 `qps: 2` |
| 其他官网/媒体 HTML | 5 | 20 | 100 | 保留现有 `qps: 1` |
| 搜狗微信 | 2 | 10 | 30 | 保留 `qps: 0.2`，每次请求额外抖动 0–2 秒 |

日常运行的有效日期下界为 `saved_cursor - 3 days`。显式传入 `since` 的回填命令保持用户给定的下界，不再额外减 3 天。

#### 冷启动

当来源/栏目没有任何 `coverage_status = complete` 的游标时，自动运行使用 `today - bootstrap_lookback_days` 作为明确下界，`bootstrap_lookback_days` 默认为 7。冷启动不表示从站点诞生日开始的历史全量；更早范围必须用 `scripts/backfill_range.py <since>` 显式启动。

`page_limit` 不是完整的穷尽条件。冷启动仍须到达上述日期下界或 `source_exhausted` 才能推进游标，避免把未扫描的页面误标为完整。

为避免预算不足时每天从第 1 页重扫的死循环，运行会保存 `coverage_window_start`、`continuation_page` 和 `episode_newest_seen_date`。下次运行将预算拆成两部分：先用 1 页扫描最新首页，避免继续回填时漏掉新发布内容；其余预算从 `max(1, continuation_page - 1)` 继续，重叠 1 页容忍分页漂移。达到日期下界或结果穷尽后，用整个覆盖 episode 的 `episode_newest_seen_date` 建立首个完整游标并清空续扫状态。

#### 连续不完整的升级

请求预算分为配置的初始值和硬上限。同一来源/栏目因 `request_budget` 或 `page_limit` 连续 2 次不完整时，下次预算翻倍，但不超过硬上限；同时使用上述续扫状态持续向日期下界推进，而不是每次从头开始。连续 3 次或已到硬上限仍不完整时，日志记录 ERROR，状态 API 返回 `needs_attention: true`。本次不自动发送外部通知，不绕过硬上限，也不立即密集重试。

### 3. 中国雄安官网

- 保留已知 JSON datasource 作为首选入口。
- 对没有 `datasource_path` 的栏目解析列表页，发现其 datasource 地址或直接提取文章链接。
- 通知公告不再被静默跳过；无法解析时形成栏目级错误和不完整运行。
- 每个栏目保持独立游标、请求预算和覆盖状态，一个栏目失败不阻断其他栏目。

### 4. 微信来源

- 保持单线程和低 QPS，在请求之间增加有界随机抖动。
- 搜索页按 `page` 页码扫描，页数上限使用返回页实际呈现的下一页链接与配置硬上限共同确定。
- 不假设搜狗结果按时间降序，因此不会因为单页出现早于 `since` 的条目就停止；必须扫完可访问的结果页后再按发布日期过滤。
- 2026-09-04 的实测因搜狗返回 `/antispider/` 而无法验证可靠的时间排序或时间范围参数。本版本不使用未验证的 `tsn` 或其他时间参数，也不把“按日期拆分查询”作为完整性前提。后续只能在固定 fixture 和非拦截的实时响应都证明语义稳定后再启用这类参数。
- 检测验证码、访问过于频繁、403、429、非预期页面结构和异常空页。命中后立即停止该来源，将运行标记为 `blocked` 或 `incomplete`，由后续运行指数退避重试。
- 配置引入 `results_per_page`。为兼容现有 `sources.yaml`，一个版本内允许用 `max_results` 作为其别名并记录弃用警告；本分支同时将现有五个微信来源迁移为 `results_per_page: 10`。它不再是整次运行的硬截断上限。

### 5. 其他官方与媒体来源

对已知分页规则的站点实现逐页扫描。对安新县等列表无日期、详情页才有日期的站点，覆盖结果分两阶段完成：

1. 列表阶段收集全部可访问页的 URL，并记录是否存在下一页。当页面明确没有下一页时，可记为 `source_exhausted`；单页列表只要页面结构可验证且确实无翻页链接，也是可验证的穷尽。
2. 详情阶段逐条解析日期，再计算 `oldest_seen_date` 和 `newest_seen_date`。只有列表已穷尽或已达日期边界，且范围内详情页没有未解决错误时，才最终标记 `complete`。

因此，适配器列表返回的覆盖元数据是初值，`BaseAdapter.run()` 会用详情阶段的 `IngestResult.publish_date` 完成日期范围并得出最终覆盖状态。

### 6. 游标、状态与可观测性

`crawl_runs` 增加向后兼容的覆盖字段：

- `coverage_status`：`complete`、`incomplete`、`blocked` 或 `unknown`。
- `stop_reason`、`pages_fetched`、`oldest_seen_date`、`newest_seen_date`。
- `consecutive_incomplete`、`effective_page_budget`、`next_retry_at` 和 `needs_attention`。
- `coverage_window_start`、`continuation_page` 和 `episode_newest_seen_date`，用于在多次有界运行间续扫同一覆盖窗口。

只有 `status = success` 且 `coverage_status = complete` 的运行才能成为下次自动抓取的游标来源。`CrawlRun.get_last_crawled_date()` 的两个分支（全局来源和栏目来源）都必须在 SQL 中显式加入 `coverage_status = 'complete'`，不完整或历史 `unknown` 运行不得被选为游标。不完整运行仍保留已成功入库的文档，同时在日志和状态 API 中显示终止原因。

每日增量运行结束后，日粒度条目数按 `documents.source + documents.publish_date` 统计首次成功入库的文档，等价于按发布日期归属的 inserted 口径；不使用包含重叠回扫的扫描数，也不直接使用某次运行的 `new_count`。它与该来源近 4 个同周期日的中位数比较；在历史样本足够且数量异常下降时，仅标记“疑似不完整”并扩大下次回扫窗口，不立即密集重试。

`stop_reason` 与覆盖状态的映射是固定合同：

| `stop_reason` | `coverage_status` | 游标 | 后续动作 |
|---|---|---|---|
| `date_boundary` | `complete` | 推进 | 正常调度 |
| `source_exhausted` | `complete` | 推进 | 正常调度 |
| `request_budget` | `incomplete` | 保留 | 连续 2 次后提升预算 |
| `page_limit` | `incomplete` | 保留 | 连续 2 次后提升预算 |
| `invalid_page` | `incomplete` | 保留 | 记录解析错误，等待下次调度 |
| `invalid_result` | `incomplete` | 保留 | 记录程序合同错误 |
| `detail_error` | `incomplete` | 保留 | 执行 URL 级退避重试 |
| `network_error` | `incomplete` | 保留 | 等待下次调度 |
| `blocked` | `blocked` | 保留 | 指数退避 |

`blocked` 的来源级退避不复用 URL 级 `crawl_errors.next_retry_at`。它存在最新 `crawl_runs.next_retry_at` 中，调度器启动该来源前先检查此时间；退避从 6 小时开始，每次翻倍，最长 72 小时。成功且覆盖完整后清零连续拦截计数。

## 数据流

1. 调度器读取上次覆盖完整的游标；有游标时计算 3 天重叠下界，无游标时计算 7 天冷启动下界。
2. 如果存在未完成的覆盖 episode，本次预算先保留 1 页给最新内容，其余从带 1 页重叠的续扫位置开始。
3. 适配器在请求预算内逐页获取列表，返回条目和初始覆盖元数据。
4. 入库流程按已有内容哈希保持幂等，用详情日期完成覆盖日期范围，详情错误继续进入分类重试队列。
5. 运行结束时同时保存处理结果、覆盖结果、预算升级计数和续扫状态。
6. 只有覆盖完整的成功运行推进游标；预算不足的运行下次从续扫位置继续，其他不完整运行按终止原因退避或重试。

## 错误处理

- 单条详情抓取失败：保持现有 URL 级重试，该运行不推进游标。
- 列表页失败：保存已获取页面和续扫位置，覆盖状态为 `incomplete`。
- 反爬命中：停止当前来源，覆盖状态为 `blocked`，在 `crawl_runs.next_retry_at` 中保存 6–72 小时的来源级指数退避，不立即循环重试。
- 页面结构变更：当响应成功但提取为空，且页面不是可验证的空列表时，记为 `invalid_page` 而非成功。
- 数据库迁移：使用幂等加列，旧运行默认 `coverage_status = unknown`，不破坏历史数据。

## 测试策略

实现严格遵循测试先行：

- 基类测试：3 天重叠边界、完整/不完整游标推进、列表与详情两阶段覆盖收敛。
- 冷启动测试：无游标时使用 7 天下界，预算耗尽后持久化续扫位置，下次保留首页预算并从重叠页继续，最终建立完整游标。
- 迁移合同测试：全部已启用适配器都返回新覆盖结果；旧 `list[ListItem]` 返回值被标记为 `incomplete/invalid_result`，不推进游标。
- 雄安官网测试：通知公告入口发现、栏目隔离、达到日期边界和解析失败不推游标。
- 微信测试：超过 10 条时翻页、非时间排序结果全页扫描后过滤、预算截止、HTTP 302 跳转后的 200 验证码页/403/429 停止、跨页去重，以及 `max_results` 别名兼容。
- 其他来源测试：分页 URL 生成、日期下界终止、页面穷尽和异常空页。
- 数据库测试：新字段迁移、覆盖与续扫状态持久化、旧数据兼容，以及 `get_last_crawled_date()` 仅选择 `coverage_status = 'complete'`。
- 预算升级测试：连续 2 次因预算中止后翻倍，不超过硬上限；连续 3 次后 `needs_attention = true`。
- 端到端回归：模拟列表延迟、分页和中途限流，验证文档无重复、游标不越过未覆盖日期。

## 范围边界

- 不引入付费数据服务、登录态自动化或验证码绕过。
- 不提高并发度，不移除现有 QPS 限制。
- 不把条目数统计当成绝对完整性证明；它只用于发现异常并触发后续回扫。
- 本次不改动 LLM 分析、报告和通知逻辑。
