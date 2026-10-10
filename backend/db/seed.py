"""Deterministic, idempotent synthetic data seeding for PostgreSQL."""
import json
from pathlib import Path
from sqlalchemy.orm import Session

from backend.db.models import (
    CaseModel,
    CriterionResultModel,
    DocumentModel,
    PolicyCriterionModel,
    PolicyModel,
)
from backend.db.session import get_db_session

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "data" / "synthetic" / "policy.json"
PATIENTS_PATH = ROOT / "data" / "synthetic" / "patients.json"
FIXTURES_PATH = ROOT / "contracts" / "mock_response.json"


def seed_synthetic_data(session: Session) -> dict[str, int]:
    """Seed policies, documents, cases, and baseline criteria results idempotently."""
    counts = {"policies": 0, "criteria": 0, "documents": 0, "cases": 0, "results": 0}

    # 1. Seed canonical policy and criteria
    if POLICY_PATH.exists():
        policy_data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        policy_id = policy_data["policy_id"]
        policy = session.query(PolicyModel).filter_by(policy_id=policy_id).first()
        if not policy:
            policy = PolicyModel(
                policy_id=policy_id,
                service=policy_data.get("service", "Lumbar MRI"),
                version=policy_data.get("version", "demo-1"),
                notice=policy_data.get("notice", "Illustrative synthetic policy"),
            )
            session.add(policy)
            session.flush()
            counts["policies"] += 1

        for crit in policy_data.get("criteria", []):
            existing_crit = (
                session.query(PolicyCriterionModel)
                .filter_by(policy_id=policy_id, criterion_id=crit["criterion_id"])
                .first()
            )
            if not existing_crit:
                pc = PolicyCriterionModel(
                    policy_id=policy_id,
                    criterion_id=crit["criterion_id"],
                    text=crit["text"],
                    evidence_expectation=crit.get("evidence_expectation"),
                )
                session.add(pc)
                counts["criteria"] += 1

    # 2. Seed canonical chart documents
    if PATIENTS_PATH.exists():
        patients_data = json.loads(PATIENTS_PATH.read_text(encoding="utf-8"))
        for patient in patients_data:
            for doc in patient.get("documents", []):
                source_id = doc["source_id"]
                existing_doc = session.query(DocumentModel).filter_by(source_id=source_id).first()
                if not existing_doc:
                    d = DocumentModel(
                        source_id=source_id,
                        patient_id=doc["patient_id"],
                        doc_date=doc.get("date"),
                        text=doc["text"],
                    )
                    session.add(d)
                    counts["documents"] += 1

    # 3. Seed demo cases and initial criterion results
    if FIXTURES_PATH.exists():
        fixtures_data = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        for c in fixtures_data.get("cases", []):
            case_id = c["case_id"]
            existing_case = session.query(CaseModel).filter_by(case_id=case_id).first()
            if not existing_case:
                case_obj = CaseModel(
                    case_id=case_id,
                    patient_id=c["patient_id"],
                    service=c["service"],
                    policy_id=c["policy_id"],
                    status=c.get("status", "RESULTS_READY"),
                    scenario=c.get("scenario", "unknown"),
                )
                session.add(case_obj)
                session.flush()
                counts["cases"] += 1

        for case_id, res_payload in fixtures_data.get("results_by_case", {}).items():
            for cr in res_payload.get("criteria_results", []):
                crit_id = cr["criterion_id"]
                evidence_list = []
                for ev in cr.get("evidence", []):
                    ev_copy = dict(ev)
                    if (ev_copy.get("char_start") is None or ev_copy.get("char_end") is None) and ev_copy.get("quote") and ev_copy.get("source_id"):
                        doc = session.query(DocumentModel).filter_by(source_id=ev_copy["source_id"]).first()
                        if doc and ev_copy["quote"] in doc.text:
                            ev_copy["char_start"] = doc.text.find(ev_copy["quote"])
                            ev_copy["char_end"] = ev_copy["char_start"] + len(ev_copy["quote"])
                    evidence_list.append(ev_copy)

                existing_res = (
                    session.query(CriterionResultModel)
                    .filter_by(case_id=case_id, criterion_id=crit_id)
                    .first()
                )
                if not existing_res:
                    res_obj = CriterionResultModel(
                        case_id=case_id,
                        criterion_id=crit_id,
                        status=cr["status"],
                        verified=cr["verified"],
                        reason=cr.get("reason"),
                        evidence=evidence_list,
                        missing_facts=cr.get("missing_facts", []),
                        retry_log=cr.get("retry_log", []),
                        validator_flags=cr.get("validator_flags", []),
                    )
                    session.add(res_obj)
                    counts["results"] += 1
                else:
                    if any(e.get("char_start") is None for e in existing_res.evidence or []):
                        existing_res.evidence = evidence_list

    session.flush()
    return counts


if __name__ == "__main__":
    from backend.rag.ingest import ingest_synthetic_records
    with get_db_session() as s:
        seeded = seed_synthetic_data(s)
        chunks = ingest_synthetic_records(s)
        print("Seeding complete:", seeded)
        print("Chunk ingestion complete:", chunks)
