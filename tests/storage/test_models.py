import pytest
from storage.models import Document, init_db
from storage.database import get_db, close_db

@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    yield
    close_db()

def test_create_and_get_document(db):
    doc = Document.create(
        source="xiongan_portal",
        doc_type="新闻",
        title="测试标题",
        url="https://www.xiongan.gov.cn/test.html",
        publish_date="2026-07-10",
        raw_html="<p>raw</p>",
        text="测试正文",
        content_hash="abc123",
    )
    assert doc.id is not None
    fetched = Document.get_by_id(doc.id)
    assert fetched.title == "测试标题"
    assert fetched.source == "xiongan_portal"

def test_duplicate_content_hash_raises(db):
    Document.create(
        source="xiongan_portal", doc_type="新闻", title="A",
        url="https://example.com/a", publish_date="2026-07-10",
        raw_html="", text="same", content_hash="dup",
    )
    from storage.models import IntegrityError
    with pytest.raises(IntegrityError):
        Document.create(
            source="xiongan_portal", doc_type="新闻", title="B",
            url="https://example.com/b", publish_date="2026-07-10",
            raw_html="", text="same", content_hash="dup",
        )


def test_duplicate_url_leaves_connection_ready_for_error_logging(db):
    from storage.models import CrawlError, IntegrityError

    Document.create(
        source="anxin_gov", doc_type="新闻", title="A",
        url="https://example.com/same", publish_date="2026-10-13",
        raw_html="", text="first", content_hash="first",
    )
    with pytest.raises(IntegrityError):
        Document.create(
            source="anxin_gov", doc_type="新闻", title="B",
            url="https://example.com/same", publish_date="2026-10-13",
            raw_html="", text="updated", content_hash="updated",
        )

    CrawlError.log("anxin_gov", "https://example.com/same", "duplicate URL")
    assert get_db().execute(
        "SELECT status FROM crawl_errors WHERE source = ? AND url = ?",
        ("anxin_gov", "https://example.com/same"),
    ).fetchone()["status"] == "pending"


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
