from storage.models import Document

def content_hash(text: str) -> str:
    return Document.compute_hash(text)

def is_duplicate(text: str) -> bool:
    h = content_hash(text)
    from storage.database import get_conn
    row = get_conn().execute(
        "SELECT 1 FROM documents WHERE content_hash = ? LIMIT 1", (h,)
    ).fetchone()
    return row is not None
