from fastapi import APIRouter, HTTPException, Query
from storage.models import Document

router = APIRouter()


@router.get("/documents")
def list_documents(
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total = Document.count(source=source)
    docs = Document.list(source=source, limit=limit, offset=offset)
    return {
        "total": total,
        "items": [d.to_dict() for d in docs],
    }


@router.get("/documents/{doc_id}")
def get_document(doc_id: int):
    doc = Document.get_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        **doc.to_dict(),
        "text": doc.text,
        "raw_html": doc.raw_html,
    }
