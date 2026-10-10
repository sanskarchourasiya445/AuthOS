"""Document ingestion module for AuthOS."""
from backend.ingest.service import ingest_document_safe, validate_document_payload

__all__ = ["ingest_document_safe", "validate_document_payload"]
