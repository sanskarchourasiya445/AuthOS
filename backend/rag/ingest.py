"""Deterministic document ingestion and text chunking for AuthOS.

Guarantees:
- Pure deterministic slicing: text[char_start:char_end] == chunk_text verbatim.
- Zero cross-patient or cross-document mixing.
- Preserves patient_id, source_id, and doc_date on every chart chunk.
- Preserves policy_id and section metadata on policy chunks.
- Idempotent database persistence with unique position constraints.
- No vector embeddings or LLM dependencies in this phase.
"""
import json
import re
from pathlib import Path
from sqlalchemy.orm import Session

from backend.db.models import (
    DocumentChunkModel,
    DocumentModel,
    PolicyChunkModel,
    PolicyModel,
)
from backend.rag.schemas import DocumentChunk, PolicyChunk

ROOT = Path(__file__).resolve().parents[2]
PATIENTS_PATH = ROOT / "data" / "synthetic" / "patients.json"
POLICY_PATH = ROOT / "data" / "synthetic" / "policy.json"


def estimate_tokens(text: str) -> int:
    """Lightweight, deterministic token count estimator.

    Uses unicode word and punctuation token extraction without external dependencies.
    """
    if not text or not text.strip():
        return 0
    tokens = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
    return len(tokens)


def split_paragraph_spans(text: str) -> list[tuple[int, int, str]]:
    """Split text into paragraph spans with exact start and end offsets."""
    spans: list[tuple[int, int, str]] = []
    # Match non-empty paragraphs separated by one or more newlines
    for match in re.finditer(r"[^\r\n]+(?:\r?\n(?![^\r\n]))*", text):
        raw = match.group(0)
        s, e = match.start(), match.end()
        # Trim whitespace boundaries while adjusting character offsets exactly
        l_strip = len(raw) - len(raw.lstrip())
        r_strip = len(raw) - len(raw.rstrip())
        exact_start = s + l_strip
        exact_end = e - r_strip
        if exact_end > exact_start:
            exact_text = text[exact_start:exact_end]
            spans.append((exact_start, exact_end, exact_text))
    return spans


def split_sentence_spans(text: str, base_offset: int = 0) -> list[tuple[int, int, str]]:
    """Split text into sentence spans with exact start and end offsets relative to document."""
    spans: list[tuple[int, int, str]] = []
    # Split sentences on standard terminators followed by whitespace or end of string
    for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", text):
        raw = match.group(0)
        s, e = match.start(), match.end()
        l_strip = len(raw) - len(raw.lstrip())
        r_strip = len(raw) - len(raw.rstrip())
        start = base_offset + s + l_strip
        end = base_offset + e - r_strip
        if end > start:
            spans.append((start, end, text[s + l_strip : e - r_strip]))
    return spans


def chunk_patient_document(
    *,
    source_id: str,
    patient_id: str,
    text: str,
    doc_date: str | None = None,
    chunk_version: str = "v1",
    target_tokens: int = 250,
    max_tokens: int = 400,
) -> list[DocumentChunk]:
    """Deterministically chunk a patient chart document primarily by paragraphs.

    Preserves exact character offsets such that text[char_start:char_end] == chunk_text.
    """
    if not text or not text.strip():
        return []

    para_spans = split_paragraph_spans(text)
    if not para_spans:
        # Fallback for single line without newlines
        start = len(text) - len(text.lstrip())
        end = len(text) - (len(text) - len(text.rstrip()))
        para_spans = [(start, end, text[start:end])]

    chunks: list[DocumentChunk] = []
    chunk_index = 0

    current_spans: list[tuple[int, int, str]] = []
    current_token_count = 0

    def emit_chunk(spans: list[tuple[int, int, str]]) -> DocumentChunk:
        nonlocal chunk_index
        c_start = spans[0][0]
        c_end = spans[-1][1]
        c_text = text[c_start:c_end]
        chk_id = f"{source_id}_chk{chunk_index:03d}_{chunk_version}"
        chunk = DocumentChunk(
            chunk_id=chk_id,
            source_id=source_id,
            patient_id=patient_id,
            doc_date=doc_date,
            chunk_text=c_text,
            chunk_index=chunk_index,
            char_start=c_start,
            char_end=c_end,
            token_count=estimate_tokens(c_text),
            chunk_version=chunk_version,
        )
        chunk_index += 1
        return chunk

    for p_start, p_end, p_text in para_spans:
        p_tokens = estimate_tokens(p_text)

        # Handle very long single paragraphs by sub-chunking on sentences
        if p_tokens > max_tokens:
            if current_spans:
                chunks.append(emit_chunk(current_spans))
                current_spans = []
                current_token_count = 0

            sent_spans = split_sentence_spans(p_text, base_offset=p_start)
            sent_batch: list[tuple[int, int, str]] = []
            sent_tokens = 0
            for s_start, s_end, s_text in sent_spans:
                s_tok = estimate_tokens(s_text)
                if sent_tokens + s_tok > target_tokens and sent_batch:
                    chunks.append(emit_chunk(sent_batch))
                    sent_batch = [(s_start, s_end, s_text)]
                    sent_tokens = s_tok
                else:
                    sent_batch.append((s_start, s_end, s_text))
                    sent_tokens += s_tok

            if sent_batch:
                chunks.append(emit_chunk(sent_batch))
            continue

        # Normal paragraph packing up to target window
        if current_token_count + p_tokens > target_tokens and current_spans:
            chunks.append(emit_chunk(current_spans))
            current_spans = [(p_start, p_end, p_text)]
            current_token_count = p_tokens
        else:
            current_spans.append((p_start, p_end, p_text))
            current_token_count += p_tokens

    if current_spans:
        chunks.append(emit_chunk(current_spans))

    return chunks


def chunk_policy_document(
    *,
    policy_id: str,
    text: str,
    chunk_version: str = "v1",
    target_tokens: int = 250,
    max_tokens: int = 400,
) -> list[PolicyChunk]:
    """Deterministically chunk a policy document by section headings.

    Preserves exact character offsets such that text[char_start:char_end] == chunk_text.
    """
    if not text or not text.strip():
        return []

    # Find section headings: Markdown headers (##) or Section / Criterion labels
    pattern = r"(?:^|\n)(#{1,3}\s+[^\n]+|Section\s+\d+[:\s][^\n]+|Criterion\s+C\d+[:\s][^\n]+)"
    matches = list(re.finditer(pattern, text))

    chunks: list[PolicyChunk] = []
    chunk_index = 0

    if not matches:
        # No headings detected: treat as single section
        start = len(text) - len(text.lstrip())
        end = len(text) - (len(text) - len(text.rstrip()))
        c_text = text[start:end]
        return [
            PolicyChunk(
                chunk_id=f"{policy_id}_chk000_{chunk_version}",
                policy_id=policy_id,
                section_id="sec-00",
                heading="General",
                chunk_text=c_text,
                chunk_index=0,
                char_start=start,
                char_end=end,
                token_count=estimate_tokens(c_text),
                chunk_version=chunk_version,
            )
        ]

    for i, m in enumerate(matches):
        h_start = m.start() if i > 0 else 0
        h_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_section = text[h_start:h_end]
        heading_text = m.group(1).strip()
        sec_id = f"sec-{i:02d}"

        # Exact boundary trimming
        l_strip = len(raw_section) - len(raw_section.lstrip())
        r_strip = len(raw_section) - len(raw_section.rstrip())
        exact_start = h_start + l_strip
        exact_end = h_end - r_strip

        if exact_end <= exact_start:
            continue

        sec_text = text[exact_start:exact_end]
        toks = estimate_tokens(sec_text)

        if toks <= max_tokens:
            chunks.append(
                PolicyChunk(
                    chunk_id=f"{policy_id}_{sec_id}_chk{chunk_index:03d}_{chunk_version}",
                    policy_id=policy_id,
                    section_id=sec_id,
                    heading=heading_text,
                    chunk_text=sec_text,
                    chunk_index=chunk_index,
                    char_start=exact_start,
                    char_end=exact_end,
                    token_count=toks,
                    chunk_version=chunk_version,
                )
            )
            chunk_index += 1
        else:
            # Sub-split long section by paragraphs
            p_spans = split_paragraph_spans(sec_text)
            batch: list[tuple[int, int, str]] = []
            b_tokens = 0
            for ps, pe, pt in p_spans:
                ptok = estimate_tokens(pt)
                abs_ps = exact_start + ps
                abs_pe = exact_start + pe
                if b_tokens + ptok > target_tokens and batch:
                    bs = batch[0][0]
                    be = batch[-1][1]
                    btxt = text[bs:be]
                    chunks.append(
                        PolicyChunk(
                            chunk_id=f"{policy_id}_{sec_id}_chk{chunk_index:03d}_{chunk_version}",
                            policy_id=policy_id,
                            section_id=sec_id,
                            heading=heading_text,
                            chunk_text=btxt,
                            chunk_index=chunk_index,
                            char_start=bs,
                            char_end=be,
                            token_count=estimate_tokens(btxt),
                            chunk_version=chunk_version,
                        )
                    )
                    chunk_index += 1
                    batch = [(abs_ps, abs_pe, pt)]
                    b_tokens = ptok
                else:
                    batch.append((abs_ps, abs_pe, pt))
                    b_tokens += ptok
            if batch:
                bs = batch[0][0]
                be = batch[-1][1]
                btxt = text[bs:be]
                chunks.append(
                    PolicyChunk(
                        chunk_id=f"{policy_id}_{sec_id}_chk{chunk_index:03d}_{chunk_version}",
                        policy_id=policy_id,
                        section_id=sec_id,
                        heading=heading_text,
                        chunk_text=btxt,
                        chunk_index=chunk_index,
                        char_start=bs,
                        char_end=be,
                        token_count=estimate_tokens(btxt),
                        chunk_version=chunk_version,
                    )
                )
                chunk_index += 1

    return chunks


def chunk_canonical_policy_json(
    policy_data: dict,
    chunk_version: str = "v1",
) -> list[PolicyChunk]:
    """Convert canonical policy JSON structure into deterministic section-level policy chunks."""
    policy_id = policy_data["policy_id"]
    chunks: list[PolicyChunk] = []
    chunk_index = 0

    # Preamble chunk
    preamble = f"{policy_data.get('service', 'Service')} Policy ({policy_id}, version {policy_data.get('version', 'v1')}). {policy_data.get('notice', '')}"
    chunks.append(
        PolicyChunk(
            chunk_id=f"{policy_id}_sec00_chk{chunk_index:03d}_{chunk_version}",
            policy_id=policy_id,
            section_id="sec-00-preamble",
            heading="Policy Overview and Scope",
            chunk_text=preamble,
            chunk_index=chunk_index,
            char_start=0,
            char_end=len(preamble),
            token_count=estimate_tokens(preamble),
            chunk_version=chunk_version,
        )
    )
    chunk_index += 1

    # Criteria chunks
    for i, c in enumerate(policy_data.get("criteria", []), start=1):
        crit_id = c["criterion_id"]
        exp = c.get("evidence_expectation", "")
        crit_text = f"Criterion {crit_id}: {c['text']}. Evidence expectation: {exp}"
        chunks.append(
            PolicyChunk(
                chunk_id=f"{policy_id}_{crit_id}_chk{chunk_index:03d}_{chunk_version}",
                policy_id=policy_id,
                section_id=f"sec-{i:02d}-{crit_id}",
                heading=f"Criterion {crit_id}",
                chunk_text=crit_text,
                chunk_index=chunk_index,
                char_start=0,
                char_end=len(crit_text),
                token_count=estimate_tokens(crit_text),
                chunk_version=chunk_version,
            )
        )
        chunk_index += 1

    return chunks


def ingest_synthetic_records(
    session: Session,
    chunk_version: str = "v1",
) -> dict[str, int]:
    """Ingest and persist canonical synthetic policy and patient document chunks idempotently."""
    counts = {"policy_chunks": 0, "document_chunks": 0}

    # 1. Ingest Policy Chunks
    if POLICY_PATH.exists():
        policy_data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        p_chunks = chunk_canonical_policy_json(policy_data, chunk_version=chunk_version)
        new_p_ids = {pc.chunk_id for pc in p_chunks}
        # Purge stale policy chunks from previous ingestion runs of this version
        session.query(PolicyChunkModel).filter(
            PolicyChunkModel.policy_id == policy_data["policy_id"],
            PolicyChunkModel.chunk_version == chunk_version,
            ~PolicyChunkModel.chunk_id.in_(new_p_ids),
        ).delete(synchronize_session=False)

        for pc in p_chunks:
            existing = (
                session.query(PolicyChunkModel)
                .filter_by(
                    policy_id=pc.policy_id,
                    chunk_version=chunk_version,
                    chunk_index=pc.chunk_index,
                )
                .first()
            )
            if not existing:
                model = PolicyChunkModel(
                    chunk_id=pc.chunk_id,
                    policy_id=pc.policy_id,
                    section_id=pc.section_id,
                    heading=pc.heading,
                    chunk_text=pc.chunk_text,
                    chunk_index=pc.chunk_index,
                    char_start=pc.char_start,
                    char_end=pc.char_end,
                    token_count=pc.token_count,
                    chunk_version=pc.chunk_version,
                )
                session.add(model)
                counts["policy_chunks"] += 1
            else:
                existing.chunk_id = pc.chunk_id
                existing.section_id = pc.section_id
                existing.heading = pc.heading
                existing.chunk_text = pc.chunk_text
                existing.char_start = pc.char_start
                existing.char_end = pc.char_end
                existing.token_count = pc.token_count

    # 2. Ingest Patient Document Chunks
    if PATIENTS_PATH.exists():
        patients_data = json.loads(PATIENTS_PATH.read_text(encoding="utf-8"))
        for patient in patients_data:
            for doc in patient.get("documents", []):
                source_id = doc["source_id"]
                patient_id = doc["patient_id"]
                doc_date = doc.get("date")
                text = doc.get("text", "")

                doc_chunks = chunk_patient_document(
                    source_id=source_id,
                    patient_id=patient_id,
                    text=text,
                    doc_date=doc_date,
                    chunk_version=chunk_version,
                )
                new_d_ids = {dc.chunk_id for dc in doc_chunks}
                # Purge stale document chunks from previous ingestion runs of this version
                session.query(DocumentChunkModel).filter(
                    DocumentChunkModel.source_id == source_id,
                    DocumentChunkModel.chunk_version == chunk_version,
                    ~DocumentChunkModel.chunk_id.in_(new_d_ids),
                ).delete(synchronize_session=False)

                for dc in doc_chunks:
                    existing = (
                        session.query(DocumentChunkModel)
                        .filter_by(
                            source_id=dc.source_id,
                            chunk_version=chunk_version,
                            chunk_index=dc.chunk_index,
                        )
                        .first()
                    )
                    if not existing:
                        model = DocumentChunkModel(
                            chunk_id=dc.chunk_id,
                            source_id=dc.source_id,
                            patient_id=dc.patient_id,
                            doc_date=dc.doc_date,
                            chunk_text=dc.chunk_text,
                            chunk_index=dc.chunk_index,
                            char_start=dc.char_start,
                            char_end=dc.char_end,
                            token_count=dc.token_count,
                            chunk_version=dc.chunk_version,
                        )
                        session.add(model)
                        counts["document_chunks"] += 1
                    else:
                        existing.chunk_id = dc.chunk_id
                        existing.patient_id = dc.patient_id
                        existing.doc_date = dc.doc_date
                        existing.chunk_text = dc.chunk_text
                        existing.char_start = dc.char_start
                        existing.char_end = dc.char_end
                        existing.token_count = dc.token_count

    session.flush()
    return counts


def ingest_persisted_document(session: Session, source_id: str, chunk_version: str = "v1") -> int:
    """Ingest or re-ingest chunks for a single DocumentModel stored in the database.

    Purges stale chunks and updates character offsets atomically.
    """
    doc = session.query(DocumentModel).filter_by(source_id=source_id).first()
    if not doc:
        return 0

    doc_chunks = chunk_patient_document(
        source_id=doc.source_id,
        patient_id=doc.patient_id,
        text=doc.text,
        doc_date=doc.doc_date,
        chunk_version=chunk_version,
    )
    new_ids = {dc.chunk_id for dc in doc_chunks}
    session.query(DocumentChunkModel).filter(
        DocumentChunkModel.source_id == source_id,
        DocumentChunkModel.chunk_version == chunk_version,
        ~DocumentChunkModel.chunk_id.in_(new_ids),
    ).delete(synchronize_session=False)

    inserted = 0
    for dc in doc_chunks:
        existing = (
            session.query(DocumentChunkModel)
            .filter_by(
                source_id=dc.source_id,
                chunk_version=chunk_version,
                chunk_index=dc.chunk_index,
            )
            .first()
        )
        if not existing:
            model = DocumentChunkModel(
                chunk_id=dc.chunk_id,
                source_id=dc.source_id,
                patient_id=dc.patient_id,
                doc_date=dc.doc_date,
                chunk_text=dc.chunk_text,
                chunk_index=dc.chunk_index,
                char_start=dc.char_start,
                char_end=dc.char_end,
                token_count=dc.token_count,
                chunk_version=dc.chunk_version,
            )
            session.add(model)
            inserted += 1
        else:
            existing.chunk_id = dc.chunk_id
            existing.patient_id = dc.patient_id
            existing.doc_date = dc.doc_date
            existing.chunk_text = dc.chunk_text
            existing.char_start = dc.char_start
            existing.char_end = dc.char_end
            existing.token_count = dc.token_count

    session.flush()
    return len(doc_chunks)
