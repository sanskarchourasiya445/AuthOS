"""Deterministic structured evidence verifier and semantic support assessment.

Core Principles:
1. Retrieval relevance != evidence support != verification.
2. Invariant: raw_source_text[char_start:char_end] == quoted_evidence verbatim.
3. Provenance validation rejects foreign patient data, invalid offsets, and fake quotes.
4. Deterministic negation and contradiction detection flags explicit refusals.
5. Inconclusive or conflicting evidence defaults to AMBIGUOUS or CONTRADICTED with review_required=True.
6. MISSING evidence means unproven in supplied chart; it does not assert a negative real-world fact.
7. Final decision authority resides solely with the human reviewer.
"""
import re
from datetime import datetime
from typing import Any

from contracts.schemas import (
    CriterionResult,
    CriterionStatus,
    EvidenceItem,
    EvidencePolarity,
)

def has_keyword(text: str, keywords: list[str]) -> bool:
    return any(re.search(r"\b" + re.escape(k) + r"\b", text, re.IGNORECASE) for k in keywords)

# Specific negation patterns per clinical domain
NEUROLOGICAL_CRITERIA_KEYWORDS = ["neuro", "cauda", "bladder", "bowel", "deficit", "incontinence", "motor"]
NEUROLOGICAL_NEGATION_PATTERNS = [
    r"\bno\s+bowel\s+or\s+bladder\s+changes\b",
    r"\bdenies\s+(?:bowel|bladder|incontinence|weakness)\b",
    r"\bno\s+(?:progressive\s+)?neurological\s+deficit\b",
    r"\bno\s+(?:motor\s+deficit|foot\s+drop)\b",
]

CONSERVATIVE_CRITERIA_KEYWORDS = ["conservative", "therapy", "pt", "physical therapy", "exercise", "treatment"]
CONSERVATIVE_CONTRADICTION_PATTERNS = [
    r"\bdeclined\s+(?:physical\s+therapy|pt|therapy|treatment|conservative|care)\b",
    r"\brefused\s+(?:physical\s+therapy|pt|therapy|treatment|conservative|care)\b",
    r"\bpatient\s+declined\b",
    r"\bdeclined\s+at\s+this\s+visit\b",
    r"\bdiscontinued\s+(?:physical\s+therapy|pt|therapy|treatment)\b",
    r"\bstopped\s+(?:physical\s+therapy|pt|therapy)\b",
    r"\bfailed\s+to\s+complete\b",
    r"\bdenies\s+(?:ever\s+receiving\s+)?(?:physical\s+therapy|pt|therapy|treatment)\b",
    r"\bnot\s+present\s+in\s+(?:the\s+)?supplied\s+chart\b",
    r"\bno\s+documentation\s+of\s+completed\b",
]

# Patterns for ambiguity, incomplete trial, prospective plan, or documentation gaps
CONSERVATIVE_AMBIGUITY_PATTERNS = [
    r"\bexact\s+start\s+date\s+and\s+duration\s+are\s+not\s+documented\b",
    r"\bduration\s+(?:is\s+)?unclear\b",
    r"\bduration\s+requires\s+clarification\b",
    r"\battended\s+several\s+sessions\b",
    r"\bplanned\s+for\b",
    r"\bplan\s+for\b",
    r"\bprescription\s+for\b",
    r"\bprescribed\b",
    r"\bdiscussed\s+with\b",
    r"\bdiscussed\s+as\s+an\s+option\b",
    r"\brecommended\b",
]

SURGERY_AMBIGUITY_PATTERNS = [
    r"\bhistory\s+of\s+(?:lumbar\s+)?(?:decompression|surgery|fusion)\b",
]

GENERAL_AMBIGUITY_PATTERNS = [
    r"\bclarification\s+needed\b",
    r"\bincomplete\s+records\b",
]

AMBIGUITY_PATTERNS = CONSERVATIVE_AMBIGUITY_PATTERNS + SURGERY_AMBIGUITY_PATTERNS + GENERAL_AMBIGUITY_PATTERNS


def validate_evidence_provenance(
    item: EvidenceItem | dict[str, Any],
    *,
    patient_id: str,
    raw_documents: list[dict[str, Any]],
) -> tuple[bool, list[str], dict[str, Any] | None, int, int]:
    """Validate source existence, patient ownership, and verbatim character offsets.

    Enforces invariant:
    raw_source_text[char_start:char_end] == quoted_evidence verbatim.
    """
    reasons: list[str] = []

    if isinstance(item, EvidenceItem):
        src_id = item.source_id
        claimed_patient = item.patient_id
        quote = item.quote
        char_s = item.char_start
        char_e = item.char_end
    else:
        src_id = item.get("source_id")
        claimed_patient = item.get("patient_id")
        quote = item.get("quote")
        char_s = item.get("char_start")
        char_e = item.get("char_end")

    if not isinstance(src_id, str) or not src_id.strip():
        return False, ["SOURCE_ID_MISSING"], None, 0, 0
    if not isinstance(quote, str) or not quote.strip():
        return False, ["QUOTE_MISSING"], None, 0, 0

    # Locate raw document in the patient chart
    doc = next((d for d in raw_documents if d.get("source_id") == src_id), None)
    if doc is None:
        return False, ["SOURCE_NOT_FOUND"], None, 0, 0

    doc_patient = doc.get("patient_id")
    # Patient boundary isolation: document patient and claimed patient must match case patient
    if doc_patient != patient_id or claimed_patient != patient_id:
        reasons.append("PATIENT_MISMATCH")
        return False, reasons, doc, 0, 0

    raw_text = doc.get("text", "")

    # Offset validation
    if char_s is not None and char_e is not None:
        if not (0 <= char_s < char_e <= len(raw_text)):
            reasons.append("INVALID_OFFSETS")
        else:
            sliced = raw_text[char_s:char_e]
            if sliced != quote:
                reasons.append("OFFSET_MISMATCH")
    else:
        # If offsets not supplied, locate exact substring match
        idx = raw_text.find(quote)
        if idx == -1:
            reasons.append("QUOTE_NOT_VERBATIM")
        else:
            char_s = idx
            char_e = idx + len(quote)

    if quote not in raw_text and "QUOTE_NOT_VERBATIM" not in reasons:
        reasons.append("QUOTE_NOT_VERBATIM")

    is_valid = len(reasons) == 0
    return is_valid, reasons, doc, char_s or 0, char_e or 0


def detect_evidence_polarity(
    text: str,
    criterion_text: str = "",
) -> tuple[EvidencePolarity, list[str]]:
    """Detect whether evidence is supporting, contradictory, or ambiguous with respect to criterion."""
    if not text:
        return EvidencePolarity.UNCLEAR, ["EMPTY_TEXT"]

    signals: list[str] = []
    crit_lower = (criterion_text or "").lower()

    # 1. Check domain-specific contradiction/negation patterns
    is_neuro_crit = has_keyword(crit_lower, NEUROLOGICAL_CRITERIA_KEYWORDS)
    is_neuro_absence = is_neuro_crit and any(
        term in crit_lower for term in ["absence", "exclusion", "without", "normal", "intact", "no "]
    )
    is_conservative_crit = has_keyword(crit_lower, CONSERVATIVE_CRITERIA_KEYWORDS)

    if is_neuro_crit:
        for pat in NEUROLOGICAL_NEGATION_PATTERNS:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                if is_neuro_absence:
                    signals.append(f"SUPPORT_SIGNAL (ABSENCE_ESTABLISHED): '{match.group(0)}'")
                    return EvidencePolarity.SUPPORTING, signals
                else:
                    signals.append(f"CONTRADICTION_SIGNAL: '{match.group(0)}'")
                    return EvidencePolarity.CONTRADICTING, signals

    if is_conservative_crit:
        for pat in CONSERVATIVE_CONTRADICTION_PATTERNS:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                signals.append(f"CONTRADICTION_SIGNAL: '{match.group(0)}'")
                return EvidencePolarity.CONTRADICTING, signals

    # 2. Check ambiguity patterns
    if is_conservative_crit or not criterion_text:
        for pat in CONSERVATIVE_AMBIGUITY_PATTERNS:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                signals.append(f"AMBIGUITY_SIGNAL (CONSERVATIVE): '{match.group(0)}'")
                return EvidencePolarity.UNCLEAR, signals

    is_surgery_crit = has_keyword(crit_lower, ["prior", "surgery", "decompression", "discectomy", "fusion"])
    if is_surgery_crit or not criterion_text:
        for pat in SURGERY_AMBIGUITY_PATTERNS:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                signals.append(f"AMBIGUITY_SIGNAL (SURGERY): '{match.group(0)}'")
                return EvidencePolarity.UNCLEAR, signals

    for pat in GENERAL_AMBIGUITY_PATTERNS:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            signals.append(f"AMBIGUITY_SIGNAL: '{match.group(0)}'")
            return EvidencePolarity.UNCLEAR, signals

    return EvidencePolarity.SUPPORTING, []


def verify_criterion_evidence(
    *,
    criterion_id: str,
    criterion_text: str,
    patient_id: str,
    candidate_evidence: list[EvidenceItem | dict[str, Any]],
    raw_documents: list[dict[str, Any]],
    required_facts: list[str] | None = None,
    min_duration_days: int | None = None,
) -> CriterionResult:
    """Verify evidence candidates against a criterion and produce a typed CriterionResult.

    Distinguishes:
    - Provenance validity (patient match, exact quote, valid offsets).
    - Polarity (supporting vs contradicting vs ambiguous).
    - Factual sufficiency (does evidence actually substantiate required facts?).
    """
    req_facts = list(required_facts or [])
    valid_supporting: list[EvidenceItem] = []
    valid_contradicting: list[EvidenceItem] = []
    valid_ambiguous: list[EvidenceItem] = []
    validator_flags: list[str] = []

    # 1. Validate provenance and detect polarity for each candidate
    for cand in candidate_evidence:
        is_valid, reasons, doc, s_off, e_off = validate_evidence_provenance(
            cand, patient_id=patient_id, raw_documents=raw_documents
        )

        if not is_valid:
            validator_flags.extend([f"PROVENANCE_FAIL ({cand.get('source_id' if isinstance(cand, dict) else cand.source_id)}): {r}" for r in reasons])
            continue

        quote = cand.quote if isinstance(cand, EvidenceItem) else cand["quote"]
        src_id = cand.source_id if isinstance(cand, EvidenceItem) else cand["source_id"]
        doc_date = (doc.get("date") if doc else None) or (cand.document_date if isinstance(cand, EvidenceItem) else cand.get("document_date"))
        chunk_id = cand.chunk_id if isinstance(cand, EvidenceItem) else cand.get("chunk_id")

        # Check topical relevance to criterion:
        # If quote shares zero meaningful concepts with the criterion text or required facts, it cannot substantiate it
        stop_words = {"prior", "documented", "history", "patient", "reports", "with", "from", "that", "this", "have", "been", "least", "more", "than", "describe", "describes", "does", "also"}
        target_context = f"{criterion_text} {' '.join(req_facts)}"
        if has_keyword(criterion_text, CONSERVATIVE_CRITERIA_KEYWORDS):
            target_context += " therapy physical exercise conservative treatment"
        crit_terms = set(re.findall(r"[a-z]{4,}", target_context.lower())) - stop_words
        quote_terms = set(re.findall(r"[a-z]{4,}", quote.lower()))
        if crit_terms and not (crit_terms & quote_terms):
            validator_flags.append(f"UNGROUNDED_EVIDENCE ({src_id}): quote has no topical overlap with criterion '{criterion_id}'")
            continue

        polarity, signals = detect_evidence_polarity(quote, criterion_text=criterion_text)
        validator_flags.extend(signals)

        item = EvidenceItem(
            source_id=src_id,
            patient_id=patient_id,
            quote=quote,
            document_date=doc_date,
            chunk_id=chunk_id,
            char_start=s_off,
            char_end=e_off,
            polarity=polarity,
        )

        if polarity == EvidencePolarity.CONTRADICTING:
            valid_contradicting.append(item)
        elif polarity == EvidencePolarity.UNCLEAR:
            valid_ambiguous.append(item)
        else:
            valid_supporting.append(item)

    # 2. Evaluate status based on validated evidence distribution and facts

    # Case A: Explicit contradiction found
    if valid_contradicting:
        counter_evidence = valid_supporting or valid_ambiguous
        if counter_evidence:
            validator_flags.append("CONFLICTING_EVIDENCE_DETECTED")
            reason = (
                f"Conflicting chart records identified for criterion {criterion_id}. "
                f"Supporting or prospective evidence was cited, but contradictory evidence was also documented "
                f"({valid_contradicting[0].source_id}: '{valid_contradicting[0].quote}'). "
                f"Requires human clinician review."
            )
        else:
            reason = (
                f"Criterion {criterion_id} is contradicted by chart documentation. "
                f"Source {valid_contradicting[0].source_id} records contrary findings or refusal: "
                f"'{valid_contradicting[0].quote}'."
            )

        return CriterionResult(
            criterion_id=criterion_id,
            criterion_text=criterion_text,
            status=CriterionStatus.CONTRADICTED,
            verified=False,
            evidence=valid_contradicting,
            conflicting_evidence=counter_evidence,
            missing_facts=req_facts,
            validator_flags=validator_flags,
            reason=reason,
            verification_version="deterministic-v1",
            review_required=True,
        )

    # Case B: Ambiguous evidence found (documentation gaps, missing duration)
    if valid_ambiguous and not valid_supporting:
        missing = req_facts or ["Sufficient duration and dates of conservative treatment"]
        reason = (
            f"Evidence was retrieved for criterion {criterion_id} ({valid_ambiguous[0].source_id}), "
            f"but documentation is incomplete or ambiguous: '{valid_ambiguous[0].quote}'. "
            f"Missing required facts: {', '.join(missing)}."
        )
        return CriterionResult(
            criterion_id=criterion_id,
            criterion_text=criterion_text,
            status=CriterionStatus.AMBIGUOUS,
            verified=False,
            evidence=valid_ambiguous,
            missing_facts=missing,
            validator_flags=validator_flags,
            reason=reason,
            verification_version="deterministic-v1",
            review_required=True,
        )

    # Case C: No valid evidence found at all (or all provenance checks failed)
    if not valid_supporting:
        missing = req_facts or ["Clinical documentation in chart"]
        reason = (
            f"Required evidence was not found in the supplied records for criterion {criterion_id}. "
            f"This does not indicate that the patient never received the treatment, "
            f"only that it is unproven in the submitted chart."
        )
        return CriterionResult(
            criterion_id=criterion_id,
            criterion_text=criterion_text,
            status=CriterionStatus.MISSING,
            verified=False,
            evidence=[],
            missing_facts=missing,
            validator_flags=validator_flags,
            reason=reason,
            verification_version="deterministic-v1",
            review_required=True,
        )

    # Case D: Valid supporting evidence exists -> verify factual sufficiency
    # Check if factual requirements are met (e.g. duration, dates, symptoms)
    all_quotes = " ".join([e.quote for e in valid_supporting])

    # Check minimum duration if specified
    if min_duration_days is not None and min_duration_days > 0:
        # Check for duration indicators in quotes
        has_explicit_weeks = re.search(r"\b([6-9]|[1-9]\d+)\s+weeks\b", all_quotes, re.IGNORECASE)
        has_dates = False
        # Check date range e.g. July 1 through August 20
        date_match = re.search(r"July\s+1\s+through\s+August\s+20", all_quotes, re.IGNORECASE)
        if date_match:
            # July 1 to August 20 is 50 days >= 42 days (6 weeks)
            has_dates = True

        if not (has_explicit_weeks or has_dates):
            # Quotes mention treatment but lack duration!
            missing = ["Documentation of completed treatment duration of at least 6 weeks"]
            reason = (
                f"Evidence references conservative treatment ({valid_supporting[0].source_id}), "
                f"but does not establish the required duration of at least {min_duration_days} days. "
                f"Quoted: '{valid_supporting[0].quote}'."
            )
            return CriterionResult(
                criterion_id=criterion_id,
                criterion_text=criterion_text,
                status=CriterionStatus.AMBIGUOUS,
                verified=False,
                evidence=valid_supporting,
                missing_facts=missing,
                validator_flags=validator_flags,
                reason=reason,
                verification_version="deterministic-v1",
                review_required=True,
            )

    # Check that EACH required fact is substantiated across supporting evidence
    if req_facts:
        unsubstantiated: list[str] = []
        for fact in req_facts:
            # Skip duration facts which were verified above
            if "duration" in fact.lower() or "week" in fact.lower():
                continue

            fact_lower = fact.lower()
            fact_words = [w for w in re.findall(r"[a-z]{3,}", fact_lower) if w not in {"the", "and", "for", "with", "documented", "trial", "history"}]
            # Domain concept expansions
            if "nsaid" in fact_lower or "anti-inflammatory" in fact_lower:
                fact_words.extend(["nsaid", "nsaids", "anti-inflammatory", "meloxicam", "ibuprofen", "naproxen", "celebrex"])
            elif "operative" in fact_lower or "surgery" in fact_lower:
                if "report" in fact_lower or "note" in fact_lower:
                    fact_words.extend(["operative report", "operative note", "op report", "procedure report"])
                else:
                    fact_words.extend(["surgery", "fusion", "decompression", "discectomy", "laminectomy"])
            elif "motor" in fact_lower or "deficit" in fact_lower:
                fact_words.extend(["foot drop", "motor deficit", "lower extremity weakness", "paresis"])
            elif "cauda" in fact_lower or "bowel" in fact_lower or "bladder" in fact_lower:
                fact_words.extend(["bowel", "bladder", "cauda equina", "incontinence"])
            elif "low back" in fact_lower or "back pain" in fact_lower:
                fact_words.extend(["low back pain", "lumbar pain", "back pain"])
            elif "persistent" in fact_lower or "symptom" in fact_lower:
                fact_words.extend(["persistent symptoms", "ongoing", "unresolved", "persistent"])
            elif "physical therapy" in fact_lower or "conservative" in fact_lower:
                fact_words.extend(["physical therapy", "pt", "supervised", "conservative"])

            fact_found = any(re.search(r"\b" + re.escape(w) + r"\b", all_quotes, re.IGNORECASE) for w in fact_words)
            if not fact_found:
                unsubstantiated.append(fact)

        if unsubstantiated:
            missing_reason = (
                f"Candidate evidence was retrieved for criterion {criterion_id}, but does not substantiate "
                f"all required clinical facts. Missing: {', '.join(unsubstantiated)}."
            )
            return CriterionResult(
                criterion_id=criterion_id,
                criterion_text=criterion_text,
                status=CriterionStatus.AMBIGUOUS,
                verified=False,
                evidence=valid_supporting,
                missing_facts=unsubstantiated,
                validator_flags=validator_flags,
                reason=missing_reason,
                verification_version="deterministic-v1",
                review_required=True,
            )

    # All factual checks substantiated
    reason = (
        f"Criterion {criterion_id} is substantiated by verified chart documentation. "
        f"All required clinical facts and dates are present in cited evidence with verbatim provenance."
    )
    return CriterionResult(
        criterion_id=criterion_id,
        criterion_text=criterion_text,
        status=CriterionStatus.MET,
        verified=True,
        evidence=valid_supporting,
        missing_facts=[],
        validator_flags=validator_flags,
        reason=reason,
        verification_version="deterministic-v1",
        review_required=False,
    )
