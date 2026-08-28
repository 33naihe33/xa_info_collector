# 增量 6：推送机制 — 双触发（定时摘要 + 即时预警）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 实现主动推送：按时间触发（每日早报/每周摘要）+ 按重要程度触发（高优先级商机即时预警），用户可配置偏好。

**Architecture:** notifier 模块包含推送管理器、摘要生成器、定时调度器、推送通道。pipeline 分析完成后自动评估新商机优先级触发即时预警。APScheduler 定时生成摘要推送。Web Push 通道（PWA）。

**Tech Stack:** pywebpush（Web Push 协议），APScheduler（定时调度），FastAPI（推送 API）。

---

## 设计要点

- **双触发机制**：定时摘要（Cron）+ 即时预警（pipeline 完成后评估）
- **用户偏好**：预警阈值、关注条线、定时计划、免打扰时段
- **防打扰**：每日即时推送上限、免打扰时段、去重
- **推送通道**：Web Push（主），预留微信/邮件接口

## 文件结构（本增量创建/修改）

```
config/push_rules.yaml              # 推送策略配置
notifier/
├── __init__.py
├── push_manager.py                 # 推送编排（即时/定时）
├── digest_builder.py               # 定时摘要生成
├── channels/
│   ├── __init__.py
│   └── web_push.py                 # Web Push 通道
storage/models.py                   # push_subscriptions/push_settings/push_logs 表
web/api/push.py                     # 推送 API（订阅/设置/状态）
web/app.py                          # 注册路由 + 启动调度器
```

---

## Task 1: 推送数据模型

**Files:**
- Modify: `storage/models.py`
- Test: `tests/storage/test_push_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/storage/test_push_models.py
import pytest
from storage.models import init_db, close_db, PushSubscription, PushSettings, PushLog


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_create_subscription():
    sub = PushSubscription.create(user_id="default", channel="web_push",
                                   endpoint="https://fcm.googleapis.com/xxx",
                                   keys='{"p256dh":"abc","auth":"def"}')
    assert sub.id is not None
    assert sub.user_id == "default"

def test_get_settings_default():
    """无设置时返回默认值。"""
    settings = PushSettings.get_or_create("default")
    assert settings.user_id == "default"
    assert settings.instant_enabled is True
    assert settings.instant_threshold == "high"

def test_update_settings():
    settings = PushSettings.get_or_create("default")
    settings.update(instant_threshold="critical", daily_digest_enabled=False)
    fetched = PushSettings.get_or_create("default")
    assert fetched.instant_threshold == "critical"
    assert fetched.daily_digest_enabled is False

def test_create_push_log():
    log = PushLog.create(user_id="default", trigger_type="instant",
                         channel="web_push", title="测试推送", body="内容")
    assert log.id is not None
    assert log.delivered is False

def test_push_log_count_today():
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                   title="a", body="a")
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                   title="b", body="b")
    count = PushLog.count_today("default", "instant")
    assert count == 2
```

- [ ] **Step 2: 实现 DDL + DAO**

DDL（追加到 SCHEMA_SQL）:
```sql
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    channel TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    keys TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_settings (
    user_id TEXT PRIMARY KEY DEFAULT 'default',
    instant_enabled INTEGER NOT NULL DEFAULT 1,
    instant_threshold TEXT NOT NULL DEFAULT 'high',
    daily_limit INTEGER NOT NULL DEFAULT 5,
    focus_lines TEXT DEFAULT '[]',
    daily_digest_enabled INTEGER NOT NULL DEFAULT 1,
    daily_digest_time TEXT NOT NULL DEFAULT '08:00',
    weekly_digest_enabled INTEGER NOT NULL DEFAULT 1,
    digest_threshold TEXT NOT NULL DEFAULT 'medium',
    dnd_enabled INTEGER NOT NULL DEFAULT 1,
    dnd_start TEXT NOT NULL DEFAULT '22:00',
    dnd_end TEXT NOT NULL DEFAULT '07:00'
);

CREATE TABLE IF NOT EXISTS push_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    opportunity_id INTEGER,
    trigger_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0,
    clicked INTEGER NOT NULL DEFAULT 0,
    clicked_at TEXT
);
```

DAO 类（追加到 models.py）:
```python
class PushSubscription:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.user_id = row["user_id"]
        self.channel = row["channel"]
        self.endpoint = row["endpoint"]
        self.keys = row["keys"]
        self.created_at = row["created_at"]

    @classmethod
    def create(cls, *, user_id="default", channel, endpoint, keys="{}") -> "PushSubscription":
        conn = get_conn()
        import json
        if isinstance(keys, dict):
            keys = json.dumps(keys)
        cur = conn.execute(
            """INSERT INTO push_subscriptions (user_id, channel, endpoint, keys, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, channel, endpoint, keys, datetime.now().isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM push_subscriptions WHERE id = ?", (cur.lastrowid,)).fetchone()
        return cls(row)

    @classmethod
    def list_by_user(cls, user_id="default") -> list["PushSubscription"]:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)).fetchall()
        return [cls(r) for r in rows]


class PushSettings:
    PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, row: sqlite3.Row):
        self.user_id = row["user_id"]
        self.instant_enabled = bool(row["instant_enabled"])
        self.instant_threshold = row["instant_threshold"]
        self.daily_limit = row["daily_limit"]
        self.focus_lines = row["focus_lines"]
        self.daily_digest_enabled = bool(row["daily_digest_enabled"])
        self.daily_digest_time = row["daily_digest_time"]
        self.weekly_digest_enabled = bool(row["weekly_digest_enabled"])
        self.digest_threshold = row["digest_threshold"]
        self.dnd_enabled = bool(row["dnd_enabled"])
        self.dnd_start = row["dnd_start"]
        self.dnd_end = row["dnd_end"]

    @classmethod
    def get_or_create(cls, user_id="default") -> "PushSettings":
        conn = get_conn()
        row = conn.execute("SELECT * FROM push_settings WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO push_settings (user_id) VALUES (?)", (user_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM push_settings WHERE user_id = ?", (user_id,)).fetchone()
        return cls(row)

    def update(self, **kwargs):
        conn = get_conn()
        for key, value in kwargs.items():
            if isinstance(value, bool):
                value = 1 if value else 0
            conn.execute(f"UPDATE push_settings SET {key} = ? WHERE user_id = ?", (value, self.user_id))
        conn.commit()

    def should_send_instant(self, priority: str) -> bool:
        """判断某优先级是否达到即时推送阈值。"""
        if not self.instant_enabled:
            return False
        return self.PRIORITY_ORDER.get(priority, 3) <= self.PRIORITY_ORDER.get(self.instant_threshold, 1)

    def is_dnd_now(self, now_time: str = None) -> bool:
        """判断当前是否在免打扰时段。"""
        if not self.dnd_enabled:
            return False
        from datetime import datetime
        t = now_time or datetime.now().strftime("%H:%M")
        start, end = self.dnd_start, self.dnd_end
        if start <= end:
            return start <= t < end
        else:  # 跨天（如 22:00-07:00）
            return t >= start or t < end

    def to_dict(self) -> dict:
        import json
        return {
            "instant_enabled": self.instant_enabled,
            "instant_threshold": self.instant_threshold,
            "daily_limit": self.daily_limit,
            "focus_lines": json.loads(self.focus_lines) if self.focus_lines else [],
            "daily_digest_enabled": self.daily_digest_enabled,
            "daily_digest_time": self.daily_digest_time,
            "weekly_digest_enabled": self.weekly_digest_enabled,
            "digest_threshold": self.digest_threshold,
            "dnd_enabled": self.dnd_enabled,
            "dnd_start": self.dnd_start,
            "dnd_end": self.dnd_end,
        }


class PushLog:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.user_id = row["user_id"]
        self.opportunity_id = row["opportunity_id"] if "opportunity_id" in row.keys() else None
        self.trigger_type = row["trigger_type"]
        self.channel = row["channel"]
        self.title = row["title"]
        self.body = row["body"]
        self.sent_at = row["sent_at"]
        self.delivered = bool(row["delivered"])
        self.clicked = bool(row["clicked"])

    @classmethod
    def create(cls, *, user_id="default", opportunity_id=None, trigger_type,
               channel, title, body, delivered=False) -> "PushLog":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO push_logs (user_id, opportunity_id, trigger_type, channel,
               title, body, sent_at, delivered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, opportunity_id, trigger_type, channel, title, body,
             datetime.now().isoformat(), 1 if delivered else 0),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, lid: int) -> "PushLog | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM push_logs WHERE id = ?", (lid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def count_today(cls, user_id="default", trigger_type=None) -> int:
        """统计今日推送数。"""
        conn = get_conn()
        today = datetime.now().strftime("%Y-%m-%d")
        if trigger_type:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM push_logs WHERE user_id = ? AND trigger_type = ? AND sent_at LIKE ?",
                (user_id, trigger_type, f"{today}%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM push_logs WHERE user_id = ? AND sent_at LIKE ?",
                (user_id, f"{today}%"),
            ).fetchone()
        return row["c"]

    @classmethod
    def already_sent(cls, user_id="default", opportunity_id=None) -> bool:
        """检查某商机是否已推送过（去重）。"""
        if not opportunity_id:
            return False
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM push_logs WHERE user_id = ? AND opportunity_id = ? LIMIT 1",
            (user_id, opportunity_id),
        ).fetchone()
        return row is not None
```

- [ ] **Step 3: 运行验证 + Commit**

Run: `pytest tests/storage/test_push_models.py -v` → 5 passed
Run: `pytest tests/ -v` → 90 passed (85 + 5)

```bash
git add storage/models.py tests/storage/test_push_models.py
git commit -m "feat: 推送数据模型 — subscriptions/settings/logs + 偏好判断逻辑"
```

---

## Task 2: 推送规则配置 + Web Push 通道

**Files:**
- Create: `config/push_rules.yaml`
- Create: `notifier/__init__.py`
- Create: `notifier/channels/__init__.py`
- Create: `notifier/channels/web_push.py`
- Test: `tests/notifier/test_web_push.py`

- [ ] **Step 1: 创建 push_rules.yaml**

```yaml
# config/push_rules.yaml
# 推送策略配置。改这里不改代码。

# 优先级 → 推送策略映射
priority_strategy:
  critical:
    instant: true        # 立即推送
    daily_cap: 0         # 0 = 无上限
  high:
    instant: true
    daily_cap: 5         # 每日最多5条
  medium:
    instant: false       # 攒入定时摘要
    daily_cap: 0
  low:
    instant: false
    daily_cap: 0

# 定时摘要计划
digest_schedule:
  daily:
    enabled: true
    time: "08:00"
    window_hours: 24     # 汇总过去24小时
  weekly:
    enabled: true
    day: "monday"
    time: "08:00"
    window_days: 7

# Web Push VAPID 密钥对（开发环境用，生产应替换）
# 生成命令：python -c "from pywebpush import webpush, WebPushException; from py_vapid import Vapid; v = Vapid(); v.generate_keys(); v.save_key('vapid_private.pem')"
vapid:
  subject: "mailto:admin@example.com"
  public_key: ""   # 运行时从环境变量或文件加载
  private_key: ""  # 运行时从环境变量或文件加载
```

- [ ] **Step 2: 创建 Web Push 通道**

```python
# notifier/channels/web_push.py
"""Web Push 推送通道（PWA）。

使用 pywebpush 实现 W3C Web Push 协议。
需要 VAPID 密钥对（开发环境可自动生成）。
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

# VAPID 密钥（开发环境自动生成）
_vapid_keys = None


def _get_vapid_keys() -> dict:
    """获取 VAPID 密钥，开发环境自动生成。"""
    global _vapid_keys
    if _vapid_keys:
        return _vapid_keys

    # 从环境变量加载（生产环境）
    public_key = os.environ.get("VAPID_PUBLIC_KEY")
    private_key = os.environ.get("VAPID_PRIVATE_KEY")
    if public_key and private_key:
        _vapid_keys = {
            "subject": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com"),
            "public_key": public_key,
            "private_key": private_key,
        }
        return _vapid_keys

    # 开发环境：生成临时密钥
    try:
        from py_vapid import Vapid
        import tempfile
        v = Vapid()
        # 生成到临时文件
        with tempfile.TemporaryDirectory() as tmpdir:
            v.generate_keys()
            priv_path = os.path.join(tmpdir, "private.pem")
            v.save_key(priv_path)
            with open(priv_path) as f:
                private_key = f.read()
            public_key = v.generate_public_key()
            # 转为 base64url
            import base64
            public_key_b64 = base64.urlsafe_b64encode(public_key).decode().rstrip("=")
        _vapid_keys = {
            "subject": "mailto:admin@example.com",
            "public_key": public_key_b64,
            "private_key": private_key,
        }
        logger.info("Generated temporary VAPID keys for development")
    except Exception as e:
        logger.error(f"Failed to generate VAPID keys: {e}")
        _vapid_keys = None

    return _vapid_keys


def get_public_key() -> str | None:
    """获取 VAPID 公钥（前端订阅用）。"""
    keys = _get_vapid_keys()
    return keys["public_key"] if keys else None


def send_web_push(subscription: dict, payload: dict) -> bool:
    """发送 Web Push 通知。

    Args:
        subscription: 订阅信息 {endpoint, keys: {p256dh, auth}}
        payload: 推送内容 {title, body, url}

    Returns:
        True 成功，False 失败
    """
    keys = _get_vapid_keys()
    if not keys:
        logger.warning("No VAPID keys available, skipping push")
        return False

    try:
        from pywebpush import webpush, WebPushException
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=keys["private_key"],
            vapid_claims={"sub": keys["subject"]},
        )
        return True
    except WebPushException as e:
        logger.error(f"Web Push failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Push error: {e}")
        return False
```

- [ ] **Step 3: 写测试**

```python
# tests/notifier/test_web_push.py
import pytest
from unittest.mock import patch, MagicMock
from notifier.channels.web_push import send_web_push, get_public_key


def test_send_web_push_success():
    """mock pywebpush，验证调用。"""
    sub = {
        "endpoint": "https://fcm.googleapis.com/test",
        "keys": {"p256dh": "abc", "auth": "def"},
    }
    payload = {"title": "测试", "body": "内容"}

    with patch("notifier.channels.web_push._get_vapid_keys", return_value={
        "subject": "mailto:test@test.com", "public_key": "pk", "private_key": "priv"
    }):
        with patch("notifier.channels.web_push.webpush") as mock_push:
            result = send_web_push(sub, payload)
            assert result is True
            mock_push.assert_called_once()

def test_send_web_push_no_keys():
    """无 VAPID 密钥时返回 False。"""
    with patch("notifier.channels.web_push._get_vapid_keys", return_value=None):
        result = send_web_push({}, {"title": "t"})
        assert result is False

def test_send_web_push_exception():
    """推送异常时返回 False 不崩溃。"""
    with patch("notifier.channels.web_push._get_vapid_keys", return_value={
        "subject": "s", "public_key": "pk", "private_key": "priv"
    }):
        with patch("notifier.channels.web_push.webpush", side_effect=Exception("fail")):
            result = send_web_push({}, {"title": "t"})
            assert result is False
```

创建 `tests/notifier/__init__.py`。

- [ ] **Step 4: 运行验证 + Commit**

Run: `pytest tests/notifier/test_web_push.py -v` → 3 passed

```bash
git add config/push_rules.yaml notifier/ tests/notifier/
git commit -m "feat: Web Push 通道 + 推送策略配置"
```

---

## Task 3: 推送管理器（双触发核心逻辑）

**Files:**
- Create: `notifier/push_manager.py`
- Create: `notifier/digest_builder.py`
- Test: `tests/notifier/test_push_manager.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/notifier/test_push_manager.py
import pytest
from unittest.mock import patch, MagicMock
from storage.models import init_db, close_db, Opportunity, PushSettings, PushLog


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_send_instant_alert_high_priority():
    """高优先级商机应触发即时预警。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="重大项目", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10", insight="解读",
    )

    with patch("notifier.push_manager._send_to_user", return_value=True):
        result = send_instant_alert(opp)
    assert result["sent"] is True


def test_skip_low_priority_instant():
    """低优先级不触发即时预警。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="小商机", source_doc_id=None, business_line="inclusive",
        opp_type="sme_retail", priority="low", status="signal",
        publish_date="2026-07-10",
    )

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "below_threshold" in result["reason"]


def test_skip_dnd_period():
    """免打扰时段不推送。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="紧急", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="critical", status="signal",
        publish_date="2026-07-10",
    )

    settings = PushSettings.get_or_create("default")
    settings.update(dnd_enabled=True, dnd_start="00:00", dnd_end="23:59")

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "dnd" in result["reason"]


def test_skip_daily_limit():
    """超过每日上限不推送。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="商机", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10",
    )

    settings = PushSettings.get_or_create("default")
    settings.update(instant_enabled=True, instant_threshold="high", daily_limit=2, dnd_enabled=False)

    # 模拟已推送2条
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push", title="a", body="a")
    PushLog.create(user_id="default", trigger_type="instant", channel="web_push", title="b", body="b")

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "daily_limit" in result["reason"]


def test_skip_duplicate():
    """同一商机不重复推送。"""
    from notifier.push_manager import send_instant_alert

    opp = Opportunity.create(
        title="商机", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10",
    )

    PushLog.create(user_id="default", trigger_type="instant", channel="web_push",
                   title="a", body="a", )
    # 直接标记已推送
    from storage.database import get_conn
    get_conn().execute(
        "UPDATE push_logs SET opportunity_id = ? WHERE id = ?", (opp.id, 1)
    )
    get_conn().commit()

    settings = PushSettings.get_or_create("default")
    settings.update(dnd_enabled=False)

    result = send_instant_alert(opp)
    assert result["sent"] is False
    assert "duplicate" in result["reason"]


def test_digest_builder():
    """摘要生成器应汇总当日商机。"""
    from notifier.digest_builder import build_daily_digest

    Opportunity.create(
        title="商机A", source_doc_id=None, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10",
    )
    Opportunity.create(
        title="商机B", source_doc_id=None, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date="2026-07-10",
    )

    digest = build_daily_digest()
    assert digest["total"] == 2
    assert "high" in digest["by_priority"]
    assert len(digest["opportunities"]) == 2
```

- [ ] **Step 2: 实现 push_manager.py**

```python
# notifier/push_manager.py
"""推送管理器：双触发核心逻辑。

即时预警：pipeline 分析完成后调用 send_instant_alert(opp)
定时摘要：APScheduler 定时调用 send_daily_digest()
"""
import logging

from storage.models import PushSettings, PushLog, PushSubscription, Opportunity

logger = logging.getLogger(__name__)


def send_instant_alert(opp: Opportunity, user_id: str = "default") -> dict:
    """评估单条商机是否需要即时推送。

    Returns: {"sent": bool, "reason": str}
    """
    settings = PushSettings.get_or_create(user_id)

    # 1. 检查优先级阈值
    if not settings.should_send_instant(opp.priority):
        return {"sent": False, "reason": "below_threshold"}

    # 2. 去重
    if PushLog.already_sent(user_id, opp.id):
        return {"sent": False, "reason": "duplicate"}

    # 3. 免打扰
    if settings.is_dnd_now():
        return {"sent": False, "reason": "dnd"}

    # 4. 每日上限
    today_count = PushLog.count_today(user_id, "instant")
    if settings.daily_limit > 0 and today_count >= settings.daily_limit:
        return {"sent": False, "reason": "daily_limit"}

    # 5. 发送
    title = f"🔴 商机预警：{opp.title[:40]}"
    body = f"[{opp.priority}] {opp.business_line} | "
    if opp.fin_scale:
        body += f"规模:{opp.fin_scale} | "
    if opp.insight:
        body += opp.insight[:60]

    sent = _send_to_user(user_id, title, body, opp.id)
    PushLog.create(
        user_id=user_id, opportunity_id=opp.id,
        trigger_type="instant", channel="web_push",
        title=title, body=body, delivered=sent,
    )
    return {"sent": sent, "reason": "ok"}


def _send_to_user(user_id: str, title: str, body: str,
                  opportunity_id: int | None = None) -> bool:
    """向用户的所有订阅发送推送。任一成功即返回 True。"""
    subs = PushSubscription.list_by_user(user_id)
    if not subs:
        logger.info(f"No subscriptions for user {user_id}, skipping push")
        return False

    from notifier.channels.web_push import send_web_push

    any_sent = False
    for sub in subs:
        import json
        subscription = {
            "endpoint": sub.endpoint,
            "keys": json.loads(sub.keys) if sub.keys else {},
        }
        payload = {"title": title, "body": body, "url": "/m/opportunities"}
        if send_web_push(subscription, payload):
            any_sent = True
    return any_sent
```

- [ ] **Step 3: 实现 digest_builder.py**

```python
# notifier/digest_builder.py
"""定时摘要生成器。"""
import json
from datetime import datetime, timedelta

from storage.models import Opportunity


def build_daily_digest(user_id: str = "default") -> dict:
    """构建每日摘要内容。"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    opps = Opportunity.list(limit=500)
    # 过滤昨天的商机（早报汇总过去24小时）
    digest_opps = [o for o in opps if o.publish_date and o.publish_date >= yesterday]

    by_priority = {}
    by_line = {}
    for o in digest_opps:
        by_priority[o.priority] = by_priority.get(o.priority, 0) + 1
        by_line[o.business_line] = by_line.get(o.business_line, 0) + 1

    return {
        "date": today,
        "total": len(digest_opps),
        "by_priority": by_priority,
        "by_line": by_line,
        "opportunities": [
            {
                "id": o.id,
                "title": o.title,
                "priority": o.priority,
                "business_line": o.business_line,
                "fin_scale": o.fin_scale,
            }
            for o in digest_opps[:20]
        ],
    }


def send_daily_digest(user_id: str = "default"):
    """发送每日摘要推送。"""
    from notifier.push_manager import _send_to_user
    from storage.models import PushSettings, PushLog

    settings = PushSettings.get_or_create(user_id)
    if not settings.daily_digest_enabled:
        return {"sent": False, "reason": "disabled"}

    if settings.is_dnd_now():
        return {"sent": False, "reason": "dnd"}

    digest = build_daily_digest(user_id)
    if digest["total"] == 0:
        return {"sent": False, "reason": "no_opportunities"}

    title = f"📊 雄安商机早报：{digest['total']} 条新商机"
    body_parts = []
    for prio in ["critical", "high", "medium"]:
        count = digest["by_priority"].get(prio, 0)
        if count:
            body_parts.append(f"{prio}:{count}")
    body = " | ".join(body_parts) if body_parts else "详见商机列表"

    sent = _send_to_user(user_id, title, body)
    PushLog.create(
        user_id=user_id, trigger_type="scheduled", channel="web_push",
        title=title, body=body, delivered=sent,
    )
    return {"sent": sent, "digest": digest}
```

- [ ] **Step 4: 运行验证 + Commit**

Run: `pytest tests/notifier/test_push_manager.py -v` → 6 passed

```bash
git add notifier/push_manager.py notifier/digest_builder.py tests/notifier/test_push_manager.py
git commit -m "feat: 推送管理器 — 双触发逻辑（即时预警+防打扰+去重）+ 摘要生成"
```

---

## Task 4: pipeline 集成 + 推送 API

**Files:**
- Modify: `analyzer/pipeline.py`（分析后触发推送）
- Create: `web/api/push.py`
- Modify: `web/app.py`
- Test: `tests/web/test_push_api.py`

- [ ] **Step 1: pipeline 分析后触发即时预警**

在 `analyzer/pipeline.py` 的 `analyze_document` 函数中，商机创建后调用推送：

```python
# 在 judge_opportunity 返回 opp 后追加：
    if opp:
        try:
            from notifier.push_manager import send_instant_alert
            send_instant_alert(opp)
        except Exception as e:
            logger.warning(f"Push notification failed for opp {opp.id}: {e}")
```

- [ ] **Step 2: 写推送 API 测试**

```python
# tests/web/test_push_api.py
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_get_push_settings_default(client):
    resp = client.get("/api/push/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["instant_enabled"] is True
    assert data["instant_threshold"] == "high"

def test_update_push_settings(client):
    resp = client.put("/api/push/settings", json={
        "instant_threshold": "critical",
        "daily_limit": 3,
    })
    assert resp.status_code == 200
    assert resp.json()["instant_threshold"] == "critical"

    # 验证持久化
    resp = client.get("/api/push/settings")
    assert resp.json()["daily_limit"] == 3

def test_subscribe_push(client):
    resp = client.post("/api/push/subscribe", json={
        "endpoint": "https://fcm.googleapis.com/test",
        "keys": {"p256dh": "abc", "auth": "def"},
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscribed"

def test_push_stats(client):
    resp = client.get("/api/push/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "today_count" in data
    assert "subscriptions" in data

def test_vapid_public_key(client):
    """前端需要 VAPID 公钥来订阅。"""
    resp = client.get("/api/push/vapid-key")
    assert resp.status_code == 200
    # 可能返回 null（无密钥时），但不应报错
    assert "public_key" in resp.json()
```

- [ ] **Step 3: 实现 web/api/push.py**

```python
# web/api/push.py
"""推送 API：订阅/设置/统计/VAPID 公钥。"""
from fastapi import APIRouter
from pydantic import BaseModel
from storage.models import PushSubscription, PushSettings, PushLog

router = APIRouter()


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict


@router.post("/push/subscribe")
def subscribe(req: SubscribeRequest):
    """注册 Web Push 订阅。"""
    PushSubscription.create(
        channel="web_push", endpoint=req.endpoint, keys=req.keys,
    )
    return {"status": "subscribed"}


@router.get("/push/settings")
def get_settings():
    return PushSettings.get_or_create("default").to_dict()


@router.put("/push/settings")
def update_settings(settings: dict):
    s = PushSettings.get_or_create("default")
    # 只更新有效字段
    valid_fields = {
        "instant_enabled", "instant_threshold", "daily_limit", "focus_lines",
        "daily_digest_enabled", "daily_digest_time", "weekly_digest_enabled",
        "digest_threshold", "dnd_enabled", "dnd_start", "dnd_end",
    }
    updates = {k: v for k, v in settings.items() if k in valid_fields}
    s.update(**updates)
    return PushSettings.get_or_create("default").to_dict()


@router.get("/push/stats")
def push_stats():
    subs = PushSubscription.list_by_user("default")
    today_instant = PushLog.count_today("default", "instant")
    today_scheduled = PushLog.count_today("default", "scheduled")
    return {
        "subscriptions": len(subs),
        "today_count": today_instant + today_scheduled,
        "today_instant": today_instant,
        "today_scheduled": today_scheduled,
    }


@router.get("/push/vapid-key")
def vapid_public_key():
    from notifier.channels.web_push import get_public_key
    return {"public_key": get_public_key()}
```

- [ ] **Step 4: 注册路由 + 运行测试 + Commit**

在 app.py 添加 `from web.api import ..., push` 和 `app.include_router(push.router, prefix="/api")`

Run: `pytest tests/web/test_push_api.py -v` → 5 passed
Run: `pytest tests/ -v` → 全部 passed

```bash
git add web/api/push.py web/app.py analyzer/pipeline.py tests/web/test_push_api.py
git commit -m "feat: 推送 API + pipeline 集成即时预警"
```

---

## Task 5: 前端推送设置对接 + 实施文档

**Files:**
- Modify: `web/frontend/src/views/mobile/MobileSettings.vue`（对接真实 API）
- Modify: `web/frontend/src/api/client.ts`（新增推送 API）

- [ ] **Step 1: 在 client.ts 新增推送 API**

```typescript
export interface PushSettings {
  instant_enabled: boolean
  instant_threshold: string
  daily_limit: number
  focus_lines: string[]
  daily_digest_enabled: boolean
  daily_digest_time: string
  weekly_digest_enabled: boolean
  digest_threshold: string
  dnd_enabled: boolean
  dnd_start: string
  dnd_end: string
}

export interface PushStats {
  subscriptions: number
  today_count: number
  today_instant: number
  today_scheduled: number
}
```

apiClient 追加：
```typescript
  getPushSettings: () => api.get<PushSettings>('/push/settings'),
  updatePushSettings: (settings: Partial<PushSettings>) => api.put<PushSettings>('/push/settings', settings),
  subscribePush: (endpoint: string, keys: any) => api.post('/push/subscribe', { endpoint, keys }),
  getPushStats: () => api.get<PushStats>('/push/stats'),
  getVapidKey: () => api.get<{ public_key: string | null }>('/push/vapid-key'),
```

- [ ] **Step 2: 改造 MobileSettings.vue 对接真实 API**

将设置页改为从 API 加载/保存设置，替换之前的占位 toast。关键改动：
- onMounted 时调用 getPushSettings 加载设置
- handleSave 调用 updatePushSettings 持久化
- 显示推送统计（今日推送数、订阅状态）

- [ ] **Step 3: 验证构建 + Commit + 实施文档**

Run: `cd web/frontend && npm run build`

撰写 `docs/impl/increment6-push.md` 并提交。

```bash
git add web/frontend/ docs/impl/increment6-push.md
git commit -m "feat: 移动端推送设置对接 + 增量6实施文档"
```

---

## 完成标准

1. ✅ `pytest tests/ -v` 全部通过
2. ✅ 前端 `npm run build` 无错误
3. ✅ 推送双触发逻辑工作（即时预警+定时摘要）
4. ✅ 用户可配置推送偏好（阈值/条线/免打扰）
5. ✅ 防打扰机制（每日上限+免打扰+去重）
6. ✅ 每个 Task 有 commit
