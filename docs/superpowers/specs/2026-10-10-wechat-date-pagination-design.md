# 微信公众号按日期分页采集设计

## 目标

补采指定日期范围内的公众号搜索结果，不因首页十条结果上限遗漏较早文章，同时保持对搜狗微信搜索的低频访问。分页不会假设搜狗结果严格按时间排序：实测结果大体降序，但可混入置顶或相关度导致的离群旧文章。

## 方案

`WechatSearchAdapter.fetch_list()` 以 1 为起点按 `page=N` 请求搜索结果。分页配置沿用完整性设计的命名：

- `initial_page_budget: 2`：未传 `since` 的冷启动每轮最多两页；避免五个公众号一次性产生 25 次低频请求。本次不实现既有完整性设计中的自适应预算升级。
- `hard_page_limit: 5`：带日期下界的手动回填每轮最多五页，且硬限制不超过 10 页。
- `results_per_page: 10`：搜狗当前每页的预期结果数；它与 `hard_page_limit` 共同推导未显式配置时的跨页 `max_results` 默认值，并用于测试夹具。
- `max_results: 50`：跨页保留结果的总量保护上限；默认值由 `results_per_page * hard_page_limit` 推导。原有 `max_results: 10` 的“首页截断”语义会被移除；五个来源在同一变更中显式迁移上述配置，避免静默的破坏性解释变化。

每页请求之间复用适配器的节流逻辑（当前公众号来源为每五秒最多一次请求）。URL 去重集合创建在分页循环外，保证跨页重复文章只保留一次。日期在 `since` 前的条目不返回。

若带 `since` 的一页中存在已解析日期，但没有任何日期 `>= since`，该页视为已越过日期边界并停止继续翻页。单个早于 `since` 的离群条目不会停止分页；只含无日期条目的页面也不会触发日期边界停止，仍受页数硬上限约束。仅在至少已解析到一页非空结果后，后续可识别的空结果页才视为 `source_exhausted` 并正常结束；第 1 页即为空属于 `suspicious_empty_first_page`，按无效页面失败，避免软封页面静默推进游标。

### 反爬、游标与可观测性

验证码与正常空页必须区分。响应 URL 含 `/antispider/`、HTTP 403/429，或命中已知验证码页面标记时，适配器记录来源、页码和检测标记后抛出 `SogouBlockedError`，而不是返回空列表。`BaseAdapter.run()` 将该异常记为失败运行并记录列表级 `crawl_errors`；由于没有成功完成运行，`last_crawled_date` 不推进。本轮已抓到但尚未入库的列表结果不作为成功结果提交。

仅在已解析过非空页后，后续页命中已实测的搜狗空态标记（`id="noresult_part1_container"`、其他含 `noresult` 的 id，或正文“没有找到”）时，才返回空列表并记录 `stop_reason=source_exhausted`；运行可正常完成并按既有规则推进游标。非验证码、但没有 `div.txt-box` 且未命中上述空态标记的响应，或第 1 页即为空时，记录 `stop_reason=invalid_page`（后者附带 `suspicious_empty_first_page` 标记）并抛出解析异常，同样不推进游标。网络超时和 5xx 保持既有请求异常路径，记录为 `network_error` 并不推进游标。这样各情形可从运行状态与错误记录中区分：`source_exhausted` 为成功且无错误，`blocked` 为失败并带反爬错误，`invalid_page` 为失败并带解析错误，`network_error` 为失败并带请求错误。

## 配置

五个公众号来源均迁移为 `initial_page_budget: 2`、`hard_page_limit: 5`、`results_per_page: 10` 和 `max_results: 50`。显式传入 `since` 的补采可请求最多五页；不传 `since` 的冷启动最多请求两页。冷启动两页不构成历史完整回填；更早历史仍由 `scripts/backfill_range.py <since>` 的显式范围任务负责，并由其后续的 `run(since, until)` 范围运行路径避免写入日常增量游标。二者均受跨页 50 条总量上限和现有 5 秒间隔约束。

## 测试

新增测试夹具使用 `span.s2` 内的 `document.write(timeConvert('...'))` 日期形式，并覆盖：

- 请求确实携带 1-based `page` 参数，且第二页的范围内文章会被收集；
- 页面包含单条早于 `since` 的离群文章时仍继续翻页；只有整页没有任何 `>= since` 的已解析日期才停止；无日期条目不触发该停止条件；
- URL 在相邻页面重复时只保留一次；
- 冷启动遵守 `initial_page_budget`，日期回填遵守 `hard_page_limit`，并且 `max_results` 在跨页累计后截断；
- `/antispider/` 跳转后的 200 页面、403、429 和验证码标记均抛出阻断异常，运行失败、记录错误且游标不推进；
- 首屏空结果记录 `suspicious_empty_first_page` 并不推进游标；仅已见非空页后的可识别空搜索结果页记录 `source_exhausted` 并正常完成；无法识别的页面记录 `invalid_page` 并不推进游标，正常结果页不会误判；
- 请求超时与 5xx 走既有 `network_error` 路径并不推进游标；
- 保留现有单页日期解析与严格 `since` 过滤的回归测试。
