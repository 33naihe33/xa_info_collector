# 增量 6 实施文档：推送机制 — 双触发（定时摘要 + 即时预警）

> 创建日期：2026-07-10
> 状态：已完成

## 交付内容

实现主动推送：pipeline 分析完成且商机达阈值时即时预警；APScheduler 定时生成每日早报（调度器逻辑就绪，cron 装配留待部署）。用户可在移动端设置页配置阈值/免打扰/每日上限。

### 数据模型（`storage/models.py`）

三张新表，均通过既有 `SCHEMA_SQL` 初始化（`init_db` 时 `CREATE TABLE IF NOT EXISTS`）：

| 表 | 用途 |
|------|------|
| `push_subscriptions` | Web Push 订阅信息（endpoint + keys），按 user_id 归属 |
| `push_settings` | 用户推送偏好（每用户一行，user_id 主键） |
| `push_logs` | 推送记录（去重键 opportunity_id + 计数依据 sent_at 日期） |

DAO 类：

- `PushSubscription.create / list_by_user`
- `PushSettings.get_or_create / update / should_send_instant / is_dnd_now / to_dict`
- `PushLog.create / count_today / already_sent`

核心判断逻辑：

- **`should_send_instant(priority)`**：用 `PRIORITY_ORDER = {critical:0, high:1, medium:2, low:3}`，priority 序号 ≤ threshold 序号才推送（数值越小优先级越高）。
- **`is_dnd_now(now_time=None)`**：支持跨午夜窗口。`start <= end` 为同日窗口（`start <= t < end`）；`start > end` 为跨午夜（如 22:00-07:00，命中条件 `t >= start or t < end`）。
- **`count_today(trigger_type=None)`**：按 `sent_at LIKE 'YYYY-MM-DD%'` 统计当日推送数。
- **`already_sent(opportunity_id)`**：按 (user_id, opportunity_id) 去重。

### 推送通道（`notifier/channels/web_push.py`）

基于 `pywebpush`（W3C Web Push 协议）。

- `_get_vapid_keys()`：优先从环境变量 `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` 加载（生产）；否则用 `py_vapid` 生成临时密钥对（开发），公钥转为未压缩点（65 字节 `0x04 + X + Y`）的 base64url 编码。密钥缓存于模块级 `_vapid_keys`。
- `get_public_key()`：返回 VAPID 公钥供前端订阅。
- `send_web_push(subscription, payload)`：发送一条推送，捕获所有异常返回 bool，绝不抛出（避免影响分析主流程）。

### 推送管理器（`notifier/push_manager.py`）

`send_instant_alert(opp, user_id="default")` —— 即时预警核心，**短路顺序**检查：

1. 阈值 `should_send_instant` → 否则 `below_threshold`
2. 去重 `already_sent` → 否则 `duplicate`
3. 免打扰 `is_dnd_now` → 否则 `dnd`
4. 每日上限 `count_today("instant") >= daily_limit`（`daily_limit=0` 表示不限）→ 否则 `daily_limit`
5. 通过 `_send_to_user` 向用户所有订阅发送 → 记录 `PushLog(delivered=sent)` → `ok`

`_send_to_user(user_id, title, body)`：遍历用户订阅，任一通道成功即返回 True；无订阅返回 False（不视为错误）。

### 摘要生成器（`notifier/digest_builder.py`）

- `build_daily_digest()`：汇总过去 24 小时（按 `publish_date >= 昨天`）的商机，返回 `{date, total, by_priority, by_line, opportunities[<=20]}`。
- `send_daily_digest()`：遵守日报开关 + 免打扰；无商机不推送；标题 "📊 雄安商机早报：N 条新商机"。由 APScheduler 定时触发（调度器 cron 装配留待部署阶段，当前为可调用函数）。

### pipeline 集成（`analyzer/pipeline.py`）

在 `judge_opportunity` 返回 opp 后，`analyze_document` 内追加：

```python
if opp:
    try:
        from notifier.push_manager import send_instant_alert
        send_instant_alert(opp)
    except Exception as e:
        logger.warning(f"Push notification failed for opp {opp.id}: {e}")
```

推送失败仅记日志，不影响分析结果与文档标记已分析。

### 推送策略配置（`config/push_rules.yaml`）

`priority_strategy`（各优先级是否即时 + 每日上限）、`digest_schedule`（日/周报时间与窗口）、`vapid`（subject/密钥占位，生产用环境变量覆盖）。

## API 契约（`web/api/push.py`，前缀 `/api`）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/push/subscribe` | 注册 Web Push 订阅（body: `{endpoint, keys}`） |
| GET | `/api/push/settings` | 获取默认用户推送偏好 |
| PUT | `/api/push/settings` | 更新偏好（字段白名单过滤后落库） |
| GET | `/api/push/stats` | 推送统计（订阅数 / 今日总数 / 今日即时 / 今日定时） |
| GET | `/api/push/vapid-key` | VAPID 公钥（前端订阅用，无密钥时 `public_key: null`） |

`PUT /api/push/settings` 仅接受白名单字段：`instant_enabled, instant_threshold, daily_limit, focus_lines, daily_digest_enabled, daily_digest_time, weekly_digest_enabled, digest_threshold, dnd_enabled, dnd_start, dnd_end`。

路由在 `web/app.py` 中通过 `app.include_router(push.router, prefix="/api")` 注册。

## 前端对接（`web/frontend/src`）

- **`api/client.ts`**：新增 `PushSettings` / `PushStats` 接口与 5 个 API 方法（`getPushSettings / updatePushSettings / subscribePush / getPushStats / getVapidKey`）。
- **`views/mobile/MobileSettings.vue`**：从占位 toast 改为真实 API 对接：
  - `onMounted` 加载设置（snake_case → camelCase 视图模型）与推送统计
  - `handleSave` 调 `updatePushSettings` 持久化（camelCase → snake_case）
  - 新增"推送状态"卡片：今日推送数 / 即时预警数 / 订阅设备数
  - `handleSubscribe`：检测 Push API 支持 → 申请通知权限 → `pushManager.subscribe` → 调 `subscribePush` 落库
  - 新增"每日上限"输入项（对应后端 `daily_limit`）

## 设计决策

1. **短路检查顺序**：阈值→去重→DND→每日上限，把最廉价的判断放前面，命中即返回不写日志。
2. **VAPID 密钥开发态自动生成**：`py_vapid` 生成临时密钥，免去本地配置；生产用环境变量覆盖，公钥按 Web Push 规范编码为未压缩点 base64url。
3. **推送失败隔离**：`send_web_push` 与 pipeline 集成均用 try/except 包裹，分析主流程永不被推送故障拖垮。
4. **去重键为 opportunity_id**：同一商机只推送一次，避免重复分析/重跑触发多次预警。
5. **DND 支持跨午夜**：22:00-07:00 这类窗口用 `t >= start or t < end` 判定，避免简单区间比较在跨午夜时漏判。
6. **调度器 cron 装配留待部署**：当前 `send_daily_digest` 为可直接调用的函数；APScheduler 实际定时任务按 `push_rules.yaml` 配置在部署阶段接入。

## 验证

- `pytest tests/storage/test_push_models.py -v` → 5 passed
- `pytest tests/notifier/test_web_push.py -v` → 3 passed
- `pytest tests/notifier/test_push_manager.py -v` → 6 passed
- `pytest tests/web/test_push_api.py -v` → 5 passed
- `pytest tests/ -v` → 104 passed（85 既有 + 19 新增）
- `npm run build`（含 `vue-tsc --noEmit`）通过，dist 生成正常

## 文件清单

新增：
- `config/push_rules.yaml`
- `notifier/__init__.py`
- `notifier/push_manager.py`
- `notifier/digest_builder.py`
- `notifier/channels/__init__.py`
- `notifier/channels/web_push.py`
- `web/api/push.py`
- `tests/storage/test_push_models.py`
- `tests/notifier/__init__.py`
- `tests/notifier/test_web_push.py`
- `tests/notifier/test_push_manager.py`
- `tests/web/test_push_api.py`

修改：
- `storage/models.py` — 三张推送表 DDL + 三个 DAO 类
- `analyzer/pipeline.py` — 商机创建后触发即时预警（try/except 隔离）
- `web/app.py` — 注册 push 路由
- `web/frontend/src/api/client.ts` — PushSettings/PushStats 类型 + 5 个 API 方法
- `web/frontend/src/views/mobile/MobileSettings.vue` — 真实 API 对接 + 推送状态卡 + 本机订阅
