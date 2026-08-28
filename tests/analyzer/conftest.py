import pytest
from storage.models import init_db, close_db


@pytest.fixture(autouse=True)
def _db(tmp_path):
    """为 analyzer 测试提供数据库（LLMClient.chat_json 每次成功调用都写 raw_llm_logs）。

    已初始化时 init_db 为 no-op，test_llm_client_logs_to_db 中显式调用不受影响。
    """
    init_db(str(tmp_path / "test.db"))
    yield
    close_db()
