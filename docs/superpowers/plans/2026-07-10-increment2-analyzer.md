# 增量 2：LLM 分析层 — 实体抽取 + 商机研判 + 端到端展示

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接入智谱 GLM，对抓取的文档进行实体抽取和商机研判，产出结构化的商机/实体/关系数据，并在前端新增"商机列表"模式展示分析结果。

**Architecture:** 分析层 pipeline：文档入库后 → 规则预筛（零成本关键词匹配）→ 命中信号的文档调 GLM 做实体+商机抽取 → 结果写入 entities/relations/opportunities 表。新增 FastAPI 商机 API + Vue 商机列表页。所有规则/提示词外置为配置文件。

**Tech Stack:** 智谱 GLM-4-flash（通过 zhipuai SDK），response_format=json_object 保证结构化输出。配置文件 YAML + 提示词文本文件。

---

## 已确认的技术细节

**智谱 GLM SDK 调用方式**（已验证）：
```python
from zhipuai import ZhipuAI
client = ZhipuAI(api_key=os.environ["ZHIPUAI_API_KEY"])
response = client.chat.completions.create(
    model="glm-4-flash",
    messages=[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
    response_format={"type": "json_object"},
)
result = response.choices[0].message.content  # JSON 字符串
```

**API Key**：存于 `.env` 文件（已 gitignore），环境变量名 `ZHIPUAI_API_KEY`。已验证 Key 有效。

**模型选型**：glm-4-flash（速度快、成本低，适合批量文档处理）。可通过配置切换。

---

## 文件结构（本增量创建/修改）

```
config/
├── opp_rules.yaml             # 商机研判规则（商机类型、信号词、条线映射）
└── prompts/
    ├── extract_entities.txt    # 实体抽取提示词
    └── judge_opportunity.txt   # 商机研判提示词
analyzer/
├── __init__.py
├── llm_client.py              # 智谱 GLM 封装（含重试、JSON解析、日志）
├── rule_filter.py             # 规则预筛（关键词匹配）
├── rules_loader.py            # 读取 opp_rules.yaml
├── entity_extractor.py        # 实体+关系抽取
├── opportunity_judge.py       # 商机研判
└── pipeline.py                # 流程编排（预筛→抽取→研判→入库）
storage/
└── models.py                  # 新增 Entity/Relation/Opportunity DAO + raw_llm_logs 表
web/
├── api/
│   └── opportunities.py       # 商机列表/详情 API
└── frontend/src/
    ├── views/OpportunityList.vue  # 商机列表页
    └── api/client.ts             # 新增商机 API 方法
.env                           # ZHIPUAI_API_KEY（已 gitignore）
```

---

## Task 1: 数据模型扩展 — entities/relations/opportunities/raw_llm_logs

**Files:**
- Modify: `storage/models.py`（新增表定义 + DAO）
- Test: `tests/storage/test_models.py`（新增测试）

- [ ] **Step 1: 写失败测试**

```python
# 追加到 tests/storage/test_models.py

def test_create_and_get_entity(db):
    from storage.models import Entity
    ent = Entity.create(name="雄安集团", entity_type="机构", aliases='["中国雄安集团"]')
    assert ent.id is not None
    fetched = Entity.get_by_id(ent.id)
    assert fetched.name == "雄安集团"
    assert fetched.entity_type == "机构"

def test_entity_find_or_create(db):
    from storage.models import Entity
    ent1 = Entity.find_or_create("张国华", "人物")
    ent2 = Entity.find_or_create("张国华", "人物")
    assert ent1.id == ent2.id  # 不重复创建

def test_create_relation(db):
    from storage.models import Entity, Relation
    org = Entity.create(name="雄安集团", entity_type="机构")
    proj = Entity.create(name="启动区建设", entity_type="项目")
    rel = Relation.create(
        from_entity_id=org.id, to_entity_id=proj.id,
        relation_type="投资", source_doc_id=1, publish_date="2026-07-10",
    )
    assert rel.id is not None

def test_create_opportunity(db):
    from storage.models import Opportunity
    opp = Opportunity.create(
        title="荣乌高速项目融资",
        source_doc_id=1,
        business_line="corporate",
        opp_type="corporate_financing",
        fin_scale="18亿",
        fin_products='["项目贷款","银团贷款"]',
        target_client="交投集团",
        insight="重大基建开工，项目贷机会",
        action_suggest="建议机构业务部牵头",
        priority="high",
        status="signal",
        publish_date="2026-07-10",
    )
    assert opp.id is not None
    fetched = Opportunity.get_by_id(opp.id)
    assert fetched.business_line == "corporate"
    assert fetched.priority == "high"

def test_opportunity_list_and_filter(db):
    from storage.models import Opportunity
    Opportunity.create(
        title="商机A", source_doc_id=1, business_line="corporate",
        opp_type="corporate_financing", priority="high", status="signal",
        publish_date="2026-07-10",
    )
    Opportunity.create(
        title="商机B", source_doc_id=2, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date="2026-07-09",
    )
    all_opps = Opportunity.list()
    assert len(all_opps) == 2
    corp_opps = Opportunity.list(business_line="corporate")
    assert len(corp_opps) == 1
    assert corp_opps[0].title == "商机A"
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/storage/test_models.py -v -k "entity or relation or opportunity"`
Expected: FAIL — `AttributeError`/`ImportError`

- [ ] **Step 3: 在 models.py 中新增表定义和 DAO**

在 `SCHEMA_SQL` 字符串中追加（在已有三表之后）：

```sql
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    aliases TEXT DEFAULT '[]',
    source_doc_ids TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_entity_id INTEGER NOT NULL,
    to_entity_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    source_doc_id INTEGER,
    confidence REAL DEFAULT 1.0,
    publish_date TEXT,
    FOREIGN KEY (from_entity_id) REFERENCES entities(id),
    FOREIGN KEY (to_entity_id) REFERENCES entities(id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_doc_id INTEGER,
    business_line TEXT NOT NULL,
    opp_type TEXT NOT NULL,
    fin_scale TEXT,
    fin_products TEXT DEFAULT '[]',
    target_client TEXT,
    buyer_dept TEXT,
    relocate_from TEXT,
    relocate_scale TEXT,
    relocate_phase TEXT,
    trigger_event TEXT,
    timing_window TEXT,
    insight TEXT,
    action_suggest TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'signal',
    publish_date TEXT,
    deadline TEXT,
    extracted_at TEXT NOT NULL,
    FOREIGN KEY (source_doc_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS raw_llm_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER,
    task_type TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt TEXT,
    response TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    duration_ms INTEGER,
    created_at TEXT NOT NULL
);
```

新增 DAO 类（追加到 models.py）：

```python
class Entity:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.name = row["name"]
        self.entity_type = row["entity_type"]
        self.aliases = row["aliases"]
        self.source_doc_ids = row["source_doc_ids"]
        self.metadata = row["metadata"]
        self.created_at = row["created_at"]

    @classmethod
    def create(cls, *, name, entity_type, aliases="[]", source_doc_ids="[]",
               metadata="{}") -> "Entity":
        import json
        conn = get_conn()
        try:
            cur = conn.execute(
                """INSERT INTO entities (name, entity_type, aliases, source_doc_ids, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, entity_type, aliases, source_doc_ids, metadata, datetime.now().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return cls.get_by_name(name)
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def find_or_create(cls, name: str, entity_type: str) -> "Entity":
        existing = cls.get_by_name(name)
        if existing:
            return existing
        return cls.create(name=name, entity_type=entity_type)

    @classmethod
    def get_by_id(cls, eid: int) -> "Entity | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (eid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def get_by_name(cls, name: str) -> "Entity | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM entities WHERE name = ?", (name,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, entity_type: str | None = None, limit: int = 200) -> list["Entity"]:
        conn = get_conn()
        if entity_type:
            rows = conn.execute(
                "SELECT * FROM entities WHERE entity_type = ? LIMIT ?", (entity_type, limit)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM entities LIMIT ?", (limit,)).fetchall()
        return [cls(r) for r in rows]

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id, "name": self.name, "entity_type": self.entity_type,
            "aliases": json.loads(self.aliases) if self.aliases else [],
        }


class Relation:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.from_entity_id = row["from_entity_id"]
        self.to_entity_id = row["to_entity_id"]
        self.relation_type = row["relation_type"]
        self.source_doc_id = row["source_doc_id"]
        self.confidence = row["confidence"]
        self.publish_date = row["publish_date"]

    @classmethod
    def create(cls, *, from_entity_id, to_entity_id, relation_type,
               source_doc_id=None, confidence=1.0, publish_date=None) -> "Relation":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO relations (from_entity_id, to_entity_id, relation_type,
               source_doc_id, confidence, publish_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (from_entity_id, to_entity_id, relation_type, source_doc_id, confidence, publish_date),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, rid: int) -> "Relation | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM relations WHERE id = ?", (rid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, limit: int = 200) -> list["Relation"]:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM relations LIMIT ?", (limit,)).fetchall()
        return [cls(r) for r in rows]


class Opportunity:
    def __init__(self, row: sqlite3.Row):
        self.id = row["id"]
        self.title = row["title"]
        self.source_doc_id = row["source_doc_id"]
        self.business_line = row["business_line"]
        self.opp_type = row["opp_type"]
        self.fin_scale = row["fin_scale"] if "fin_scale" in row.keys() else None
        self.fin_products = row["fin_products"] if "fin_products" in row.keys() else "[]"
        self.target_client = row["target_client"] if "target_client" in row.keys() else None
        self.buyer_dept = row["buyer_dept"] if "buyer_dept" in row.keys() else None
        self.relocate_from = row["relocate_from"] if "relocate_from" in row.keys() else None
        self.relocate_scale = row["relocate_scale"] if "relocate_scale" in row.keys() else None
        self.relocate_phase = row["relocate_phase"] if "relocate_phase" in row.keys() else None
        self.trigger_event = row["trigger_event"] if "trigger_event" in row.keys() else None
        self.timing_window = row["timing_window"] if "timing_window" in row.keys() else None
        self.insight = row["insight"]
        self.action_suggest = row["action_suggest"]
        self.priority = row["priority"]
        self.status = row["status"]
        self.publish_date = row["publish_date"]
        self.deadline = row["deadline"] if "deadline" in row.keys() else None
        self.extracted_at = row["extracted_at"]

    @classmethod
    def create(cls, *, title, source_doc_id=None, business_line, opp_type,
               fin_scale=None, fin_products="[]", target_client=None, buyer_dept=None,
               relocate_from=None, relocate_scale=None, relocate_phase=None,
               trigger_event=None, timing_window=None, insight=None,
               action_suggest=None, priority="medium", status="signal",
               publish_date=None, deadline=None) -> "Opportunity":
        conn = get_conn()
        cur = conn.execute(
            """INSERT INTO opportunities
               (title, source_doc_id, business_line, opp_type, fin_scale, fin_products,
                target_client, buyer_dept, relocate_from, relocate_scale, relocate_phase,
                trigger_event, timing_window, insight, action_suggest, priority, status,
                publish_date, deadline, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, source_doc_id, business_line, opp_type, fin_scale, fin_products,
             target_client, buyer_dept, relocate_from, relocate_scale, relocate_phase,
             trigger_event, timing_window, insight, action_suggest, priority, status,
             publish_date, deadline, datetime.now().isoformat()),
        )
        conn.commit()
        return cls.get_by_id(cur.lastrowid)

    @classmethod
    def get_by_id(cls, oid: int) -> "Opportunity | None":
        conn = get_conn()
        row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (oid,)).fetchone()
        return cls(row) if row else None

    @classmethod
    def list(cls, *, business_line: str | None = None, priority: str | None = None,
             status: str | None = None, limit: int = 50, offset: int = 0) -> list["Opportunity"]:
        conn = get_conn()
        conditions = []
        params = []
        if business_line:
            conditions.append("business_line = ?")
            params.append(business_line)
        if priority:
            conditions.append("priority = ?")
            params.append(priority)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM opportunities {where} ORDER BY publish_date DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [cls(r) for r in rows]

    @classmethod
    def count(cls, business_line: str | None = None) -> int:
        conn = get_conn()
        if business_line:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM opportunities WHERE business_line = ?", (business_line,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) as c FROM opportunities").fetchone()
        return row["c"]

    def to_dict(self) -> dict:
        import json
        return {
            "id": self.id, "title": self.title, "source_doc_id": self.source_doc_id,
            "business_line": self.business_line, "opp_type": self.opp_type,
            "fin_scale": self.fin_scale,
            "fin_products": json.loads(self.fin_products) if self.fin_products else [],
            "target_client": self.target_client, "buyer_dept": self.buyer_dept,
            "relocate_from": self.relocate_from, "relocate_phase": self.relocate_phase,
            "trigger_event": self.trigger_event, "timing_window": self.timing_window,
            "insight": self.insight, "action_suggest": self.action_suggest,
            "priority": self.priority, "status": self.status,
            "publish_date": self.publish_date, "deadline": self.deadline,
        }


class LLMLog:
    @staticmethod
    def log(*, doc_id=None, task_type, model, prompt, response,
            prompt_tokens=0, completion_tokens=0, duration_ms=0):
        conn = get_conn()
        conn.execute(
            """INSERT INTO raw_llm_logs
               (doc_id, task_type, model, prompt, response, prompt_tokens,
                completion_tokens, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (doc_id, task_type, model, prompt, response, prompt_tokens,
             completion_tokens, duration_ms, datetime.now().isoformat()),
        )
        conn.commit()
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/storage/test_models.py -v`
Expected: 7 passed (2 existing + 5 new)

- [ ] **Step 5: Commit**

```bash
git add storage/models.py tests/storage/test_models.py
git commit -m "feat: 数据模型扩展 — entities/relations/opportunities/raw_llm_logs 表"
```

---

## Task 2: 商机规则配置 + 提示词文件

**Files:**
- Create: `config/opp_rules.yaml`
- Create: `config/prompts/extract_entities.txt`
- Create: `config/prompts/judge_opportunity.txt`
- Create: `analyzer/rules_loader.py`
- Test: `tests/analyzer/test_rules_loader.py`

- [ ] **Step 1: 创建 opp_rules.yaml**

```yaml
# config/opp_rules.yaml
# 商机研判规则。改这里不改代码。试用后调整分类/信号词/产品映射。

business_lines:
  corporate: "对公业务"
  inclusive: "普惠金融"
  retail: "个人金融"
  partnership: "政银合作"

# 规则预筛信号词：命中任一关键词的文档才调 LLM（控制成本）
pre_filter_keywords:
  - "项目|工程|建设|开工|奠基|投资|扩建|招标"
  - "央企|国企|总部|落户|注册|入驻|搬迁|疏解|迁入"
  - "专项资金|资金监管|土地出让|发债|城投"
  - "产业链|配套|供应商|科技企业|创新园|孵化器|科创"
  - "商户|个体工商户|商业街|商贸"
  - "招聘|用工|就业|职工|代发|工资"
  - "商品房|共有产权|安置房|保障房|交房|住房"
  - "战略合作|签约|签约|框架协议|数字人民币|智慧城市|绿色|低碳"
  - "银行|授信|贷款|融资|存款|金融"

opportunity_types:
  corporate_financing:
    line: corporate
    signals: ["开工|奠基|总投资|建设|扩建"]
    products: ["项目贷款", "银团贷款", "债券承销"]
  corporate_account:
    line: corporate
    signals: ["央企|国企|总部|落户|注册"]
    products: ["对公开户", "结算", "综合授信", "投行业务"]
  deposit:
    line: corporate
    signals: ["专项资金|资金监管|土地出让金"]
    products: ["财政存款", "专户存款", "资金监管"]
  sme_supply_chain:
    line: inclusive
    signals: ["产业链|配套|供应商|上下游"]
    products: ["供应链金融", "应收账款融资", "保理"]
  sme_tech:
    line: inclusive
    signals: ["科技企业|创新园|孵化器|中关村|科创"]
    products: ["科创贷", "知识产权质押", "投贷联动"]
  sme_retail:
    line: inclusive
    signals: ["商户|个体工商户|商业街|商贸"]
    products: ["小微经营贷", "POS收单"]
  payroll:
    line: retail
    signals: ["招聘|用工|就业|职工|工人|代发"]
    products: ["代发工资", "批量开户", "借记卡"]
  mortgage:
    line: retail
    signals: ["商品房|共有产权|安置房|保障房|交房"]
    products: ["个人住房贷款", "公积金"]
  wealth:
    line: retail
    signals: ["高净值|居民收入|人才引进|落户"]
    products: ["理财", "基金", "私行"]
  partnership_deal:
    line: partnership
    signals: ["战略合作|签约|会见.*银行|框架协议"]
    products: ["战略合作", "综合金融服务"]
  partnership_policy:
    line: partnership
    signals: ["数字人民币|智慧城市|专项债|绿色|低碳"]
    products: ["数字人民币", "绿色信贷", "专项债配套"]

# 优先级判定规则
priority_rules:
  critical:
    conditions: ["fin_scale >= 10亿", "央企总部疏解"]
  high:
    conditions: ["fin_scale >= 1亿", "政策窗口", "领导会见金融机构"]
  medium:
    conditions: ["有明确业务价值"]
  low:
    conditions: ["弱信号|远期|信息不全"]

model: "glm-4-flash"
```

- [ ] **Step 2: 创建提示词文件**

`config/prompts/extract_entities.txt`:
```
你是实体抽取助手。从雄安新区政务新闻中抽取实体和关系。

抽取规则：
- 机构：政府部门、企业、平台公司、金融机构
- 人物：姓名（领导、企业家等）
- 项目：具体项目名称、工程名称

同时抽取实体间的关系（如有）：
- 会见、调研、投资、合作、隶属、招标

以 JSON 格式返回：
{"entities": [{"name": "实体名", "type": "机构|人物|项目"}],
 "relations": [{"from": "实体A", "to": "实体B", "type": "关系类型"}]}
```

`config/prompts/judge_opportunity.txt`:
```
你是银行业务商机分析师，服务对象是银行分行行长。从雄安新区政务新闻中判断是否存在金融业务机会。

业务条线（business_line）：
- corporate（对公）：重大项目融资、央企国企入驻、机构存款、债券承销
- inclusive（普惠）：产业链配套、科创企业、商贸个体
- retail（个金）：代发工资、住房贷款、财富管理
- partnership（政银）：战略合作、政策窗口

分析要求：
1. 判断是否构成商机（大部分新闻可能没有直接商机）
2. 如有商机，判断属于哪个条线、什么类型
3. 估算金融规模（如有金额信息）
4. 给出金融视角解读和建议行动
5. 判断优先级：critical（≥10亿/央企疏解）、high（≥1亿/政策窗口）、medium、low

以 JSON 格式返回：
{"is_opportunity": true/false,
 "business_line": "corporate|inclusive|retail|partnership|null",
 "opp_type": "商机类型描述",
 "fin_scale": "预估金融规模或null",
 "fin_products": ["适配的金融产品"],
 "target_client": "目标客户或null",
 "insight": "金融视角解读",
 "action_suggest": "建议行动",
 "priority": "critical|high|medium|low",
 "trigger_event": "触发事件摘要"}
```

- [ ] **Step 3: 创建 rules_loader.py**

```python
# analyzer/rules_loader.py
from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_opp_rules() -> dict:
    """加载商机研判规则。"""
    with open(CONFIG_DIR / "opp_rules.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompt(name: str) -> str:
    """加载提示词文件。name: 'extract_entities' 或 'judge_opportunity'。"""
    with open(CONFIG_DIR / "prompts" / f"{name}.txt", encoding="utf-8") as f:
        return f.read().strip()


def get_pre_filter_keywords() -> list[str]:
    """获取规则预筛关键词列表（正则模式）。"""
    rules = load_opp_rules()
    return rules.get("pre_filter_keywords", [])


def get_model_name() -> str:
    """获取配置的模型名。"""
    return load_opp_rules().get("model", "glm-4-flash")
```

- [ ] **Step 4: 写测试**

```python
# tests/analyzer/test_rules_loader.py
from analyzer.rules_loader import load_opp_rules, load_prompt, get_pre_filter_keywords, get_model_name

def test_load_opp_rules_has_business_lines():
    rules = load_opp_rules()
    assert "business_lines" in rules
    assert "corporate" in rules["business_lines"]

def test_load_opp_rules_has_opportunity_types():
    rules = load_opp_rules()
    assert "opportunity_types" in rules
    assert "corporate_financing" in rules["opportunity_types"]

def test_pre_filter_keywords_nonempty():
    keywords = get_pre_filter_keywords()
    assert len(keywords) > 0
    assert any("项目" in kw for kw in keywords)

def test_load_prompt_extract_entities():
    prompt = load_prompt("extract_entities")
    assert "实体" in prompt
    assert "JSON" in prompt

def test_load_prompt_judge_opportunity():
    prompt = load_prompt("judge_opportunity")
    assert "商机" in prompt
    assert "business_line" in prompt

def test_get_model_name():
    assert get_model_name() == "glm-4-flash"
```

创建 `tests/analyzer/__init__.py`（空）。

- [ ] **Step 5: 运行验证**

Run: `pytest tests/analyzer/test_rules_loader.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add config/opp_rules.yaml config/prompts/ analyzer/rules_loader.py tests/analyzer/
git commit -m "feat: 商机规则配置 + 提示词文件 + 规则加载器"
```

---

## Task 3: GLM 客户端封装

**Files:**
- Create: `analyzer/llm_client.py`
- Test: `tests/analyzer/test_llm_client.py`

- [ ] **Step 1: 写失败测试（mock GLM SDK）**

```python
# tests/analyzer/test_llm_client.py
import json
import pytest
from unittest.mock import patch, MagicMock
from analyzer.llm_client import LLMClient


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_client_calls_create_with_json_format(mock_zhipuai_class):
    """LLMClient 应调用 GLM create，使用 json_object 格式。"""
    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key")
    result = client.chat_json(system="你是助手", user="你好")

    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "glm-4-flash"
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["messages"][0]["role"] == "system"
    assert result == {"result": "ok"}


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_client_handles_invalid_json(mock_zhipuai_class):
    """LLM 返回非 JSON 时应返回 None 而非崩溃。"""
    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="这不是JSON"))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key")
    result = client.chat_json(system="s", user="u")
    assert result is None


@patch("analyzer.llm_client.ZhipuAI")
def test_llm_client_logs_to_db(mock_zhipuai_class, tmp_path):
    """每次调用应记录到 raw_llm_logs。"""
    from storage.models import init_db, close_db, get_conn
    init_db(str(tmp_path / "test.db"))

    mock_client = MagicMock()
    mock_zhipuai_class.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"a": 1}'))]
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mock_client.chat.completions.create.return_value = mock_response

    client = LLMClient(api_key="fake-key")
    client.chat_json(system="s", user="u", doc_id=42, task_type="test")

    rows = get_conn().execute("SELECT * FROM raw_llm_logs").fetchall()
    assert len(rows) == 1
    assert rows[0]["doc_id"] == 42
    assert rows[0]["task_type"] == "test"
    close_db()
```

创建 `analyzer/__init__.py`（空）。

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/analyzer/test_llm_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 llm_client.py**

```python
# analyzer/llm_client.py
"""智谱 GLM 客户端封装。

特性：
- chat_json()：调用 GLM 返回结构化 JSON（response_format=json_object）
- 自动解析 JSON，失败返回 None
- 每次调用记录到 raw_llm_logs（可回溯）
- 支持重试（SDK 内置 max_retries）
"""
import json
import os
import time
import logging
from pathlib import Path

from zhipuai import ZhipuAI

from analyzer.rules_loader import get_model_name
from storage.models import LLMLog

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("ZHIPUAI_API_KEY", "")
        self.model = model or get_model_name()
        self.client = ZhipuAI(api_key=self.api_key) if self.api_key else None
        if not self.client:
            logger.warning("ZHIPUAI_API_KEY not set, LLM calls will fail")

    def chat_json(self, *, system: str, user: str,
                  doc_id: int | None = None, task_type: str = "unknown") -> dict | None:
        """调用 GLM 并返回解析后的 JSON dict。失败返回 None。"""
        if not self.client:
            logger.error("LLM client not initialized (no API key)")
            return None

        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.error(f"GLM API call failed: {e}")
            LLMLog.log(doc_id=doc_id, task_type=task_type, model=self.model,
                       prompt=user, response=f"ERROR: {e}")
            return None

        duration_ms = int((time.time() - start) * 1000)
        content = response.choices[0].message.content
        prompt_tokens = getattr(response.usage, "prompt_tokens", 0) if response.usage else 0
        completion_tokens = getattr(response.usage, "completion_tokens", 0) if response.usage else 0

        # 记录日志
        LLMLog.log(
            doc_id=doc_id, task_type=task_type, model=self.model,
            prompt=user[:2000], response=content[:4000],
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            duration_ms=duration_ms,
        )

        # 解析 JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse GLM response as JSON: {content[:200]}")
            return None
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/analyzer/test_llm_client.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add analyzer/llm_client.py tests/analyzer/
git commit -m "feat: GLM 客户端封装 — JSON 结构化调用 + 日志记录 + 错误处理"
```

---

## Task 4: 规则预筛

**Files:**
- Create: `analyzer/rule_filter.py`
- Test: `tests/analyzer/test_rule_filter.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/analyzer/test_rule_filter.py
from analyzer.rule_filter import should_analyze

def test_should_analyze_project_news():
    """含项目建设关键词的新闻应分析。"""
    text = "张国华调研启动区重点项目建设工作，推进投资"
    assert should_analyze(text) is True

def test_should_analyze_relocation_news():
    """含疏解搬迁的新闻应分析。"""
    text = "央企总部落户雄安新区，搬迁工作有序推进"
    assert should_analyze(text) is True

def test_should_not_analyze_irrelevant():
    """无关新闻不应分析（省 LLM 成本）。"""
    text = "今天天气晴朗，适合户外运动，公园里花开了"
    assert should_analyze(text) is False

def test_should_not_analyze_empty():
    assert should_analyze("") is False
    assert should_analyze("   ") is False
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/analyzer/test_rule_filter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 rule_filter.py**

```python
# analyzer/rule_filter.py
"""规则预筛：用关键词快速判断文档是否值得调 LLM 分析。

大部分政务新闻（会议通知、人事任免等）不含商机信号，
跳过它们可大幅降低 LLM 调用成本。
"""
import re

from analyzer.rules_loader import get_pre_filter_keywords

# 编译正则（模块级缓存）
_patterns: list[re.Pattern] | None = None


def _get_patterns() -> list[re.Pattern]:
    global _patterns
    if _patterns is None:
        keywords = get_pre_filter_keywords()
        _patterns = [re.compile(kw) for kw in keywords]
    return _patterns


def should_analyze(text: str) -> bool:
    """判断文档是否含商机信号关键词，决定是否调 LLM。"""
    if not text or not text.strip():
        return False
    for pattern in _get_patterns():
        if pattern.search(text):
            return True
    return False
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/analyzer/test_rule_filter.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add analyzer/rule_filter.py tests/analyzer/test_rule_filter.py
git commit -m "feat: 规则预筛 — 关键词匹配过滤无信号文档，控制 LLM 成本"
```

---

## Task 5: 实体抽取 + 商机研判

**Files:**
- Create: `analyzer/entity_extractor.py`
- Create: `analyzer/opportunity_judge.py`
- Test: `tests/analyzer/test_extractor_judge.py`

- [ ] **Step 1: 写失败测试（mock LLMClient）**

```python
# tests/analyzer/test_extractor_judge.py
import pytest
from unittest.mock import patch, MagicMock
from storage.models import init_db, close_db, Document, Entity, Opportunity


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def _make_doc(text="测试正文") -> int:
    doc = Document.create(
        source="xiongan_portal", doc_type="新闻", title="测试",
        url="http://test", publish_date="2026-07-10",
        raw_html="", text=text, content_hash="h1",
    )
    return doc.id


def test_extract_entities_creates_entities():
    """实体抽取应把 LLM 返回的实体写入 entities 表。"""
    from analyzer.entity_extractor import extract_entities

    doc_id = _make_doc("张国华调研启动区")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "entities": [
            {"name": "张国华", "type": "人物"},
            {"name": "启动区", "type": "项目"},
        ],
        "relations": [
            {"from": "张国华", "to": "启动区", "type": "调研"},
        ],
    }

    extract_entities(doc_id=doc_id, text="正文", llm_client=mock_llm)

    entities = Entity.list()
    assert len(entities) == 2
    names = {e.name for e in entities}
    assert "张国华" in names
    assert "启动区" in names


def test_extract_entities_handles_empty_result():
    """LLM 返回空实体时不崩溃。"""
    from analyzer.entity_extractor import extract_entities

    doc_id = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {"entities": [], "relations": []}

    extract_entities(doc_id=doc_id, text="正文", llm_client=mock_llm)
    assert len(Entity.list()) == 0


def test_judge_opportunity_creates_opportunity():
    """商机研判应把命中商机写入 opportunities 表。"""
    from analyzer.opportunity_judge import judge_opportunity
    from storage.models import Opportunity

    doc_id = _make_doc("28家企业落地雄安")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": True,
        "business_line": "inclusive",
        "opp_type": "科创企业",
        "fin_scale": None,
        "fin_products": ["科创贷"],
        "target_client": "落地企业",
        "insight": "企业落地带来开户需求",
        "action_suggest": "联系落地企业",
        "priority": "medium",
        "trigger_event": "28家企业落地",
    }

    judge_opportunity(doc_id=doc_id, text="正文", publish_date="2026-07-10",
                      llm_client=mock_llm)

    opps = Opportunity.list()
    assert len(opps) == 1
    assert opps[0].business_line == "inclusive"
    assert opps[0].priority == "medium"


def test_judge_opportunity_skips_non_opportunity():
    """LLM 判断无商机时不创建。"""
    from analyzer.opportunity_judge import judge_opportunity
    from storage.models import Opportunity

    doc_id = _make_doc("天气预报")
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = {
        "is_opportunity": False,
        "business_line": None,
    }

    judge_opportunity(doc_id=doc_id, text="正文", publish_date="2026-07-10",
                      llm_client=mock_llm)
    assert Opportunity.count() == 0


def test_judge_opportunity_handles_llm_failure():
    """LLM 返回 None 时不崩溃。"""
    from analyzer.opportunity_judge import judge_opportunity

    doc_id = _make_doc()
    mock_llm = MagicMock()
    mock_llm.chat_json.return_value = None

    # 不应抛异常
    judge_opportunity(doc_id=doc_id, text="正文", publish_date="2026-07-10",
                      llm_client=mock_llm)
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/analyzer/test_extractor_judge.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 entity_extractor.py**

```python
# analyzer/entity_extractor.py
"""实体+关系抽取：调用 LLM 从文档中抽取实体和关系，写入数据库。"""
import json
import logging

from analyzer.rules_loader import load_prompt
from storage.models import Entity, Relation

logger = logging.getLogger(__name__)


def extract_entities(*, doc_id: int, text: str, llm_client) -> dict:
    """从文档中抽取实体和关系，写入 entities/relations 表。返回统计。"""
    system_prompt = load_prompt("extract_entities")
    user_prompt = f"请从以下新闻中抽取实体和关系：\n\n{text[:3000]}"

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        doc_id=doc_id, task_type="extract_entities",
    )
    if not result:
        return {"entities": 0, "relations": 0}

    # 创建实体
    entity_map = {}  # name → Entity
    for ent_data in result.get("entities", []):
        name = ent_data.get("name", "").strip()
        ent_type = ent_data.get("type", "其他")
        if not name:
            continue
        entity = Entity.find_or_create(name=name, entity_type=ent_type)
        entity_map[name] = entity

    # 创建关系
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
            )

    return {"entities": len(entity_map), "relations": len(result.get("relations", []))}
```

- [ ] **Step 4: 实现 opportunity_judge.py**

```python
# analyzer/opportunity_judge.py
"""商机研判：调用 LLM 判断文档是否含金融商机，写入 opportunities 表。"""
import json
import logging

from analyzer.rules_loader import load_prompt
from storage.models import Opportunity

logger = logging.getLogger(__name__)


def judge_opportunity(*, doc_id: int, text: str, publish_date: str,
                      llm_client, doc_title: str = "") -> Opportunity | None:
    """判断文档是否含商机。有则创建 Opportunity 并返回，无则返回 None。"""
    system_prompt = load_prompt("judge_opportunity")
    context = f"标题：{doc_title}\n\n正文：{text[:3000]}"
    user_prompt = f"分析以下雄安新区新闻的金融商机：\n\n{context}"

    result = llm_client.chat_json(
        system=system_prompt, user=user_prompt,
        doc_id=doc_id, task_type="judge_opportunity",
    )
    if not result:
        logger.warning(f"LLM returned None for doc {doc_id}")
        return None

    if not result.get("is_opportunity", False):
        return None

    # 构建 Opportunity
    fin_products = result.get("fin_products", [])
    title = result.get("trigger_event") or doc_title or "未命名商机"

    opp = Opportunity.create(
        title=title[:200],
        source_doc_id=doc_id,
        business_line=result.get("business_line") or "corporate",
        opp_type=result.get("opp_type", ""),
        fin_scale=result.get("fin_scale"),
        fin_products=json.dumps(fin_products, ensure_ascii=False) if fin_products else "[]",
        target_client=result.get("target_client"),
        insight=result.get("insight"),
        action_suggest=result.get("action_suggest"),
        priority=result.get("priority", "medium"),
        status="signal",
        publish_date=publish_date,
        trigger_event=result.get("trigger_event"),
    )
    logger.info(f"Created opportunity {opp.id}: {opp.title} ({opp.business_line}/{opp.priority})")
    return opp
```

- [ ] **Step 5: 运行验证通过**

Run: `pytest tests/analyzer/test_extractor_judge.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add analyzer/entity_extractor.py analyzer/opportunity_judge.py tests/analyzer/test_extractor_judge.py
git commit -m "feat: 实体抽取 + 商机研判 — LLM 驱动的结构化分析"
```

---

## Task 6: 分析 pipeline 编排

**Files:**
- Create: `analyzer/pipeline.py`
- Test: `tests/analyzer/test_pipeline.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/analyzer/test_pipeline.py
import pytest
from unittest.mock import patch, MagicMock
from storage.models import init_db, close_db, Document, Opportunity


@pytest.fixture(autouse=True)
def db(tmp_path):
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()


def test_analyze_document_skips_irrelevant():
    """无信号文档不调 LLM。"""
    from analyzer.pipeline import analyze_document

    doc = Document.create(
        source="x", doc_type="新闻", title="天气预报",
        url="http://w", publish_date="2026-07-10",
        raw_html="", text="今天天气晴朗适合户外运动",
        content_hash="h1",
    )
    mock_llm = MagicMock()
    result = analyze_document(doc, llm_client=mock_llm)
    assert result["analyzed"] is False
    mock_llm.chat_json.assert_not_called()
    assert doc.is_analyzed is True  # 标记为已分析（跳过）


def test_analyze_document_full_pipeline():
    """有信号的文档走完整 pipeline。"""
    from analyzer.pipeline import analyze_document

    doc = Document.create(
        source="x", doc_type="新闻", title="28家企业落地雄安",
        url="http://e", publish_date="2026-07-10",
        raw_html="", text="28家科技企业正式落户雄安，总投资50亿",
        content_hash="h2",
    )
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        # 第一次调用：实体抽取
        {"entities": [{"name": "雄安", "type": "机构"}], "relations": []},
        # 第二次调用：商机研判
        {
            "is_opportunity": True,
            "business_line": "inclusive",
            "opp_type": "科创企业",
            "fin_products": ["科创贷"],
            "priority": "medium",
            "trigger_event": "企业落地",
            "insight": "开户需求",
            "action_suggest": "联系企业",
        },
    ]

    result = analyze_document(doc, llm_client=mock_llm)
    assert result["analyzed"] is True
    assert result["has_opportunity"] is True
    assert mock_llm.chat_json.call_count == 2  # 实体 + 商机

    opps = Opportunity.list()
    assert len(opps) == 1
    assert opps[0].business_line == "inclusive"


def test_analyze_pending_documents():
    """批量分析未分析的文档。"""
    from analyzer.pipeline import analyze_pending

    # 3篇文档：1篇有信号，2篇无信号
    Document.create(source="x", doc_type="新闻", title="项目开工",
                    url="http://1", publish_date="2026-07-10",
                    raw_html="", text="重大项目开工投资10亿", content_hash="h1")
    Document.create(source="x", doc_type="新闻", title="天气",
                    url="http://2", publish_date="2026-07-10",
                    raw_html="", text="今天天气不错", content_hash="h2")
    Document.create(source="x", doc_type="新闻", title="花开",
                    url="http://3", publish_date="2026-07-10",
                    raw_html="", text="公园的花都开了", content_hash="h3")

    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [], "relations": []},  # 实体抽取
        {"is_opportunity": True, "business_line": "corporate",
         "opp_type": "项目融资", "priority": "high",
         "trigger_event": "项目开工", "fin_products": ["项目贷"]},  # 商机
    ]

    stats = analyze_pending(llm_client=mock_llm)
    assert stats["total"] == 3
    assert stats["analyzed"] == 1  # 只有1篇有信号
    assert stats["skipped"] == 2
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/analyzer/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 pipeline.py**

```python
# analyzer/pipeline.py
"""分析 pipeline 编排：预筛 → 实体抽取 → 商机研判 → 标记已分析。"""
import logging

from analyzer.rule_filter import should_analyze
from analyzer.entity_extractor import extract_entities
from analyzer.opportunity_judge import judge_opportunity
from storage.models import Document, get_conn

logger = logging.getLogger(__name__)


def analyze_document(doc: "Document", llm_client) -> dict:
    """分析单篇文档。返回 {"analyzed": bool, "has_opportunity": bool}。"""
    # 规则预筛
    if not should_analyze(doc.text):
        _mark_analyzed(doc.id)
        return {"analyzed": False, "has_opportunity": False, "reason": "no_signal"}

    # 实体抽取
    try:
        extract_entities(doc_id=doc.id, text=doc.text, llm_client=llm_client)
    except Exception as e:
        logger.error(f"Entity extraction failed for doc {doc.id}: {e}")

    # 商机研判
    opp = None
    try:
        opp = judge_opportunity(
            doc_id=doc.id, text=doc.text, publish_date=doc.publish_date,
            doc_title=doc.title, llm_client=llm_client,
        )
    except Exception as e:
        logger.error(f"Opportunity judging failed for doc {doc.id}: {e}")

    _mark_analyzed(doc.id)
    return {"analyzed": True, "has_opportunity": opp is not None}


def analyze_pending(*, llm_client, limit: int = 50) -> dict:
    """批量分析所有未分析的文档。返回统计。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM documents WHERE is_analyzed = 0 ORDER BY publish_date DESC LIMIT ?",
        (limit,),
    ).fetchall()

    docs = [Document(r) for r in rows]
    analyzed = 0
    skipped = 0
    opportunities = 0

    for doc in docs:
        result = analyze_document(doc, llm_client=llm_client)
        if result["analyzed"]:
            analyzed += 1
            if result["has_opportunity"]:
                opportunities += 1
        else:
            skipped += 1

    return {
        "total": len(docs),
        "analyzed": analyzed,
        "skipped": skipped,
        "opportunities": opportunities,
    }


def _mark_analyzed(doc_id: int):
    conn = get_conn()
    conn.execute("UPDATE documents SET is_analyzed = 1 WHERE id = ?", (doc_id,))
    conn.commit()
```

- [ ] **Step 4: 运行验证通过**

Run: `pytest tests/analyzer/test_pipeline.py -v`
Expected: 3 passed

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 6: Commit**

```bash
git add analyzer/pipeline.py tests/analyzer/test_pipeline.py
git commit -m "feat: 分析 pipeline 编排 — 预筛→抽取→研判→标记"
```

---

## Task 7: 商机 API + 分析触发 API

**Files:**
- Create: `web/api/opportunities.py`
- Modify: `web/api/collect.py`（新增分析触发端点）
- Modify: `web/app.py`（注册路由）
- Test: `tests/web/test_opportunities_api.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/web/test_opportunities_api.py
import pytest
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Opportunity, Document


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="原文",
        url="http://o", publish_date="2026-07-10",
        raw_html="", text="text", content_hash="h1",
    )
    Opportunity.create(
        title="荣乌高速融资", source_doc_id=1, business_line="corporate",
        opp_type="corporate_financing", fin_scale="18亿",
        fin_products='["项目贷","银团"]', priority="high", status="signal",
        publish_date="2026-07-10", insight="基建融资",
        action_suggest="机构部牵头",
    )
    Opportunity.create(
        title="科创企业入驻", source_doc_id=1, business_line="inclusive",
        opp_type="sme_tech", priority="medium", status="signal",
        publish_date="2026-07-09", insight="开户需求",
    )
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_list_opportunities(client):
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2

def test_list_opportunities_filter_by_line(client):
    resp = client.get("/api/opportunities?business_line=corporate")
    assert resp.json()["total"] == 1
    assert resp.json()["items"][0]["title"] == "荣乌高速融资"

def test_list_opportunities_filter_by_priority(client):
    resp = client.get("/api/opportunities?priority=high")
    assert resp.json()["total"] == 1

def test_get_opportunity_detail(client):
    opp = Opportunity.list()[0]
    resp = client.get(f"/api/opportunities/{opp.id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["title"] == "荣乌高速融资"
    assert detail["fin_scale"] == "18亿"
    assert "项目贷" in detail["fin_products"]
    assert detail["insight"] == "基建融资"

def test_get_opportunity_404(client):
    resp = client.get("/api/opportunities/99999")
    assert resp.status_code == 404

def test_opportunity_stats(client):
    """商机统计：按条线汇总。"""
    resp = client.get("/api/opportunities/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert "by_line" in stats
    assert stats["by_line"]["corporate"] == 1
    assert stats["by_line"]["inclusive"] == 1
    assert stats["total"] == 2
```

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/web/test_opportunities_api.py -v`
Expected: FAIL — `ModuleNotFoundError`/404

- [ ] **Step 3: 实现 web/api/opportunities.py**

```python
# web/api/opportunities.py
from fastapi import APIRouter, HTTPException, Query
from storage.models import Opportunity

router = APIRouter()


@router.get("/opportunities")
def list_opportunities(
    business_line: str | None = Query(None),
    priority: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = Opportunity.count(business_line=business_line)
    opps = Opportunity.list(
        business_line=business_line, priority=priority, status=status,
        limit=limit, offset=offset,
    )
    return {"total": total, "items": [o.to_dict() for o in opps]}


@router.get("/opportunities/stats")
def opportunity_stats():
    """商机统计：按条线汇总。"""
    from storage.models import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT business_line, COUNT(*) as c FROM opportunities GROUP BY business_line"
    ).fetchall()
    by_line = {row["business_line"]: row["c"] for row in rows}
    total = sum(by_line.values())
    return {"total": total, "by_line": by_line}


@router.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: int):
    opp = Opportunity.get_by_id(opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp.to_dict()
```

- [ ] **Step 4: 在 collect.py 新增分析触发端点**

追加到 `web/api/collect.py`：

```python
@router.post("/analyze/trigger")
def trigger_analyze(background_tasks: BackgroundTasks):
    """触发 LLM 分析（后台执行）。"""
    from analyzer.pipeline import analyze_pending
    from analyzer.llm_client import LLMClient

    def _run():
        client = LLMClient()
        analyze_pending(llm_client=client)

    background_tasks.add_task(_run)
    return {"status": "started"}
```

- [ ] **Step 5: 在 app.py 注册路由**

在 `web/app.py` 的 `create_app()` 中添加：

```python
from web.api import documents, collect, opportunities
# ...
app.include_router(opportunities.router, prefix="/api")
```

- [ ] **Step 6: 运行验证通过**

Run: `pytest tests/web/test_opportunities_api.py -v`
Expected: 6 passed

- [ ] **Step 7: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 8: Commit**

```bash
git add web/ tests/web/
git commit -m "feat: 商机 API + 分析触发 API + 统计端点"
```

---

## Task 8: 前端商机列表页

**Files:**
- Create: `web/frontend/src/views/OpportunityList.vue`
- Modify: `web/frontend/src/api/client.ts`（新增商机 API）
- Modify: `web/frontend/src/router/index.ts`（新增路由）
- Modify: `web/frontend/src/App.vue`（侧边栏新增菜单项）

- [ ] **Step 1: 在 client.ts 新增商机 API**

在 `web/frontend/src/api/client.ts` 中追加类型和方法：

```typescript
export interface OpportunityItem {
  id: number
  title: string
  source_doc_id: number | null
  business_line: string
  opp_type: string
  fin_scale: string | null
  fin_products: string[]
  target_client: string | null
  buyer_dept: string | null
  relocate_from: string | null
  relocate_phase: string | null
  trigger_event: string | null
  timing_window: string | null
  insight: string | null
  action_suggest: string | null
  priority: string
  status: string
  publish_date: string
  deadline: string | null
}

export interface OpportunityListResponse {
  total: number
  items: OpportunityItem[]
}

export interface OpportunityStats {
  total: number
  by_line: Record<string, number>
}
```

在 `apiClient` 对象中追加：

```typescript
  getOpportunities: (params: { business_line?: string; priority?: string; status?: string; limit?: number; offset?: number }) =>
    api.get<OpportunityListResponse>('/opportunities', { params }),
  getOpportunity: (id: number) => api.get<OpportunityItem>(`/opportunities/${id}`),
  getOpportunityStats: () => api.get<OpportunityStats>('/opportunities/stats'),
  triggerAnalyze: () => api.post('/analyze/trigger'),
```

- [ ] **Step 2: 创建 OpportunityList.vue**

```vue
<!-- web/frontend/src/views/OpportunityList.vue -->
<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div>
        <h2 style="margin: 0; display: inline-block;">商机列表</h2>
        <el-tag v-if="stats" style="margin-left: 12px;" type="info">
          共 {{ stats.total }} 条
        </el-tag>
      </div>
      <el-button type="warning" :icon="MagicStick" :loading="analyzing" @click="handleAnalyze">
        LLM 分析
      </el-button>
    </div>

    <!-- 条线统计卡片 -->
    <div v-if="stats" style="display: flex; gap: 12px; margin-bottom: 16px;">
      <el-card v-for="(count, line) in lineLabels" :key="line"
        shadow="hover" style="cursor: pointer; flex: 1;"
        :body-style="{ padding: '12px' }"
        @click="filterLine = line; fetchData()">
        <div style="text-align: center;">
          <div style="font-size: 24px; font-weight: bold; color: #409eff;">{{ stats.by_line[line] || 0 }}</div>
          <div style="font-size: 12px; color: #909399;">{{ count }}</div>
        </div>
      </el-card>
    </div>

    <!-- 筛选栏 -->
    <div style="display: flex; gap: 12px; margin-bottom: 16px;">
      <el-select v-model="filterLine" placeholder="全部条线" clearable style="width: 150px;" @change="fetchData">
        <el-option v-for="(label, key) in lineLabels" :key="key" :label="label" :value="key" />
      </el-select>
      <el-select v-model="filterPriority" placeholder="全部优先级" clearable style="width: 150px;" @change="fetchData">
        <el-option label="critical" value="critical" />
        <el-option label="high" value="high" />
        <el-option label="medium" value="medium" />
        <el-option label="low" value="low" />
      </el-select>
    </div>

    <!-- 商机卡片列表 -->
    <div v-loading="loading">
      <el-card v-for="opp in opportunities" :key="opp.id"
        shadow="hover" style="margin-bottom: 12px; cursor: pointer;"
        @click="openDetail(opp)">
        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
          <el-tag :type="priorityTag(opp.priority)" size="small" effect="dark">
            {{ opp.priority }}
          </el-tag>
          <el-tag size="small">{{ lineLabels[opp.business_line] || opp.business_line }}</el-tag>
          <el-tag size="small" type="info">{{ opp.opp_type }}</el-tag>
          <span style="font-size: 12px; color: #909399; margin-left: auto;">{{ opp.publish_date }}</span>
        </div>
        <h3 style="margin: 0 0 8px 0; font-size: 16px;">{{ opp.title }}</h3>
        <div v-if="opp.fin_scale" style="font-size: 13px; color: #e6a23c; margin-bottom: 4px;">
          预估规模: {{ opp.fin_scale }}
        </div>
        <div v-if="opp.fin_products?.length" style="font-size: 13px; margin-bottom: 4px;">
          适配产品:
          <el-tag v-for="p in opp.fin_products" :key="p" size="small" style="margin: 0 2px;">{{ p }}</el-tag>
        </div>
        <p v-if="opp.insight" style="font-size: 13px; color: #606266; margin: 4px 0;">
          💡 {{ opp.insight }}
        </p>
      </el-card>
      <el-empty v-if="!loading && opportunities.length === 0" description="暂无商机，点击「LLM 分析」生成" />
    </div>

    <el-pagination
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      style="margin-top: 16px; justify-content: center;"
      @current-change="fetchData"
    />

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawerVisible" :title="selected?.title || ''" size="50%">
      <div v-if="selected" style="line-height: 1.8;">
        <p><strong>业务条线：</strong>{{ lineLabels[selected.business_line] }}</p>
        <p><strong>商机类型：</strong>{{ selected.opp_type }}</p>
        <p><strong>优先级：</strong>
          <el-tag :type="priorityTag(selected.priority)" size="small" effect="dark">{{ selected.priority }}</el-tag>
        </p>
        <p v-if="selected.fin_scale"><strong>预估规模：</strong>{{ selected.fin_scale }}</p>
        <p v-if="selected.target_client"><strong>目标客户：</strong>{{ selected.target_client }}</p>
        <p v-if="selected.fin_products?.length">
          <strong>适配产品：</strong>
          <el-tag v-for="p in selected.fin_products" :key="p" size="small" style="margin: 0 2px;">{{ p }}</el-tag>
        </p>
        <el-divider />
        <p v-if="selected.trigger_event"><strong>触发事件：</strong>{{ selected.trigger_event }}</p>
        <p v-if="selected.insight"><strong>金融解读：</strong>{{ selected.insight }}</p>
        <p v-if="selected.action_suggest"><strong>建议行动：</strong>{{ selected.action_suggest }}</p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { apiClient, type OpportunityItem, type OpportunityStats } from '../api/client'

const lineLabels: Record<string, string> = {
  corporate: '对公业务',
  inclusive: '普惠金融',
  retail: '个人金融',
  partnership: '政银合作',
}

const opportunities = ref<OpportunityItem[]>([])
const total = ref(0)
const stats = ref<OpportunityStats | null>(null)
const loading = ref(false)
const analyzing = ref(false)
const page = ref(1)
const pageSize = 20
const filterLine = ref<string | undefined>(undefined)
const filterPriority = ref<string | undefined>(undefined)
const drawerVisible = ref(false)
const selected = ref<OpportunityItem | null>(null)

function priorityTag(priority: string) {
  const map: Record<string, string> = {
    critical: 'danger', high: 'danger', medium: 'warning', low: 'info'
  }
  return map[priority] || 'info'
}

async function fetchData() {
  loading.value = true
  try {
    const resp = await apiClient.getOpportunities({
      business_line: filterLine.value,
      priority: filterPriority.value,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    opportunities.value = resp.data.items
    total.value = resp.data.total
  } finally {
    loading.value = false
  }
}

async function fetchStats() {
  const resp = await apiClient.getOpportunityStats()
  stats.value = resp.data
}

async function openDetail(opp: OpportunityItem) {
  const resp = await apiClient.getOpportunity(opp.id)
  selected.value = resp.data
  drawerVisible.value = true
}

async function handleAnalyze() {
  analyzing.value = true
  try {
    await apiClient.triggerAnalyze()
    ElMessage.success('分析任务已启动')
    setTimeout(async () => {
      await fetchData()
      await fetchStats()
      analyzing.value = false
    }, 10000)
  } catch {
    analyzing.value = false
    ElMessage.error('启动分析失败')
  }
}

onMounted(async () => {
  await fetchData()
  await fetchStats()
})
</script>
```

- [ ] **Step 3: 在 router/index.ts 新增路由**

```typescript
{ path: '/opportunities', name: 'opportunities', component: () => import('../views/OpportunityList.vue') },
```

- [ ] **Step 4: 在 App.vue 侧边栏新增菜单项**

在现有菜单项中添加（在文档列表之后）：

```vue
<el-menu-item index="/opportunities">
  <el-icon><Opportunity /></el-icon>
  <span>商机列表</span>
</el-menu-item>
```

注意：Element Plus 图标库中可能没有 `Opportunity` 图标名。使用 `TrendCharts` 或 `Money` 替代。

- [ ] **Step 5: 验证前端构建**

Run: `cd web/frontend && npm run build`
Expected: 构建成功，无 TypeScript 错误

- [ ] **Step 6: Commit**

```bash
git add web/frontend/
git commit -m "feat: 商机列表页 — 卡片展示 + 条线统计 + 筛选 + 详情抽屉"
```

---

## Task 9: 端到端验证 + 真实 LLM 调用

**Files:**
- Test: `tests/e2e/test_analyzer_e2e.py`

- [ ] **Step 1: 写 mock 端到端测试**

```python
# tests/e2e/test_analyzer_e2e.py
"""分析层端到端测试：mock LLM，验证 pipeline → DB → API → 前端契约完整。"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from storage.models import init_db, close_db, Document, Opportunity


@pytest.fixture
def client(tmp_path):
    init_db(str(tmp_path / "test.db"))
    from web.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    close_db()


def test_analyze_pipeline_to_api(client):
    """完整流程：插入文档 → mock分析 → 商机API能查到。"""
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="央企落户雄安",
        url="http://t1", publish_date="2026-07-10",
        raw_html="", text="中国星网集团总部正式落户雄安新区，投资50亿",
        content_hash="e2e1",
    )

    # Mock LLM
    mock_llm = MagicMock()
    mock_llm.chat_json.side_effect = [
        {"entities": [{"name": "中国星网集团", "type": "机构"}], "relations": []},
        {
            "is_opportunity": True, "business_line": "corporate",
            "opp_type": "央企入驻", "fin_scale": "50亿",
            "fin_products": ["对公开户", "综合授信"],
            "target_client": "中国星网集团",
            "insight": "央企总部迁入带来全方位金融需求",
            "action_suggest": "机构业务部对接",
            "priority": "critical",
            "trigger_event": "央企落户",
        },
    ]

    with patch("analyzer.pipeline.LLMClient", return_value=mock_llm):
        from analyzer.pipeline import analyze_pending
        stats = analyze_pending(llm_client=mock_llm)

    assert stats["analyzed"] == 1
    assert stats["opportunities"] == 1

    # API 能查到
    resp = client.get("/api/opportunities")
    assert resp.json()["total"] == 1
    opp = resp.json()["items"][0]
    assert opp["business_line"] == "corporate"
    assert opp["priority"] == "critical"
    assert "对公开户" in opp["fin_products"]

    # 统计 API
    resp = client.get("/api/opportunities/stats")
    assert resp.json()["by_line"]["corporate"] == 1

    # 详情 API
    resp = client.get(f"/api/opportunities/{opp['id']}")
    assert resp.json()["insight"] == "央企总部迁入带来全方位金融需求"


def test_frontend_opportunity_api_contract(client):
    """验证前端商机页用到的每个 API 字段都存在。"""
    from storage.models import Opportunity
    Opportunity.create(
        title="测试商机", source_doc_id=None, business_line="inclusive",
        opp_type="sme_tech", fin_scale="5亿",
        fin_products='["科创贷"]', target_client="某科技企业",
        insight="解读", action_suggest="行动",
        priority="medium", status="signal", publish_date="2026-07-10",
    )

    # GET /api/opportunities
    resp = client.get("/api/opportunities")
    item = resp.json()["items"][0]
    for field in ["id", "title", "business_line", "opp_type", "fin_scale",
                  "fin_products", "priority", "status", "publish_date", "insight"]:
        assert field in item, f"Missing field: {field}"

    # GET /api/opportunities/stats
    resp = client.get("/api/opportunities/stats")
    assert "by_line" in resp.json()
    assert "total" in resp.json()

    # GET /api/opportunities/{id}
    resp = client.get(f"/api/opportunities/{item['id']}")
    detail = resp.json()
    for field in ["action_suggest", "target_client", "fin_products"]:
        assert field in detail
```

- [ ] **Step 2: 运行验证**

Run: `pytest tests/e2e/test_analyzer_e2e.py -v`
Expected: 2 passed

- [ ] **Step 3: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 4: 真实 LLM 端到端验证**

```bash
# 启动后端
source .venv/bin/activate
export ZHIPUAI_API_KEY=$(grep ZHIPUAI_API_KEY .env | cut -d= -f2)
uvicorn web.app:create_app --factory --port 8000 &

# 触发分析（对已抓取的50篇文档）
curl -X POST http://localhost:8000/api/analyze/trigger

# 等待分析完成（约1-2分钟，取决于命中信号的数量）
sleep 90

# 查看商机
curl http://localhost:8000/api/opportunities | python3 -m json.tool | head -30

# 查看统计
curl http://localhost:8000/api/opportunities/stats | python3 -m json.tool
```

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/test_analyzer_e2e.py
git commit -m "test: 分析层端到端测试 — pipeline→DB→API→前端契约"
```

---

## Task 10: 实施文档

**Files:**
- Create: `docs/impl/increment2-analyzer.md`

撰写实施文档，记录：
- 交付内容（分析层各模块 + API + 前端）
- GLM 调用方式与验证结果
- 商机/实体/关系数据模型
- 真实 LLM 分析结果（商机数量、典型示例）
- 成本控制效果（预筛过滤了多少文档）
- 修复记录

- [ ] **Step 1: 撰写并 Commit**

```bash
git add docs/impl/increment2-analyzer.md
git commit -m "docs: 增量2实施文档"
```

---

## 完成标准

1. ✅ `pytest tests/ -v` 全部通过
2. ✅ 前端 `npm run build` 无 TypeScript 错误
3. ✅ 前端商机列表页调用的每个 API 都有后端实现
4. ✅ 真实 LLM 分析：对50篇文档跑通，产出商机
5. ✅ 每个 Task 有 git commit
6. ✅ 实施文档已撰写（含真实分析结果）
