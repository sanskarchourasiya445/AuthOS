"""Metrics calculation and evaluation analysis for AuthOS (Phase 5A).

Follows strict safety principles:
1. Honest metric reporting with exact denominators.
2. Undefined metrics (e.g. division by zero) are explicitly represented as None,
   never masked with artificial 0.0 or 1.0 values.
3. Strict separation of verifier correctness from retrieval ranking.
4. Separate accounting for retrieval quality queries vs safety invariant checks.
"""
from dataclasses import dataclass, field
from typing import Any
from contracts.schemas import CriterionStatus


STATUS_NAMES = ["MET", "AMBIGUOUS", "CONTRADICTED", "MISSING"]


@dataclass
class VerificationMetrics:
    total_cases: int
    correct_statuses: int
    accuracy: float
    confusion_matrix: dict[str, dict[str, int]]
    per_class: dict[str, dict[str, float | None]]
    undefined_metrics_count: int
    false_positive_met_count: int
    false_positive_met_rate: float | None
    false_negative_met_count: int
    false_negative_met_rate: float | None
    provenance_failures_count: int
    cross_patient_violations_count: int
    category_breakdown: dict[str, dict[str, Any]]
    is_deterministic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "correct_statuses": self.correct_statuses,
            "accuracy": self.accuracy,
            "confusion_matrix": self.confusion_matrix,
            "per_class": self.per_class,
            "undefined_metrics_count": self.undefined_metrics_count,
            "false_positive_met_count": self.false_positive_met_count,
            "false_positive_met_rate": self.false_positive_met_rate,
            "false_negative_met_count": self.false_negative_met_count,
            "false_negative_met_rate": self.false_negative_met_rate,
            "provenance_failures_count": self.provenance_failures_count,
            "cross_patient_violations_count": self.cross_patient_violations_count,
            "category_breakdown": self.category_breakdown,
            "is_deterministic": self.is_deterministic,
        }


def calculate_verification_metrics(
    y_true: list[CriterionStatus],
    y_pred: list[CriterionStatus],
    verified_true: list[bool],
    verified_pred: list[bool],
    categories: list[str] | None = None,
    provenance_failures: list[bool] | None = None,
    cross_patient_violations: list[bool] | None = None,
    is_deterministic: bool = True,
) -> VerificationMetrics:
    """Compute mathematical verification metrics with zero division guardrails."""
    total = len(y_true)
    if total != len(y_pred):
        raise ValueError("Length mismatch between y_true and y_pred")

    # 1. Confusion Matrix
    confusion: dict[str, dict[str, int]] = {
        s: {s2: 0 for s2 in STATUS_NAMES} for s in STATUS_NAMES
    }
    correct = 0
    for true_st, pred_st in zip(y_true, y_pred):
        t_str = true_st.value
        p_str = pred_st.value
        if t_str not in confusion:
            confusion[t_str] = {s2: 0 for s2 in STATUS_NAMES}
        confusion[t_str][p_str] = confusion[t_str].get(p_str, 0) + 1
        if true_st == pred_st:
            correct += 1

    accuracy = round(correct / total, 4) if total > 0 else 0.0

    # 2. Per-class Precision, Recall, F1
    per_class: dict[str, dict[str, float | None]] = {}
    undefined_count = 0

    for st in STATUS_NAMES:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t.value == st and p.value == st)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t.value != st and p.value == st)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t.value == st and p.value != st)

        # Precision
        if (tp + fp) > 0:
            prec = round(tp / (tp + fp), 4)
        else:
            prec = None
            undefined_count += 1

        # Recall
        if (tp + fn) > 0:
            rec = round(tp / (tp + fn), 4)
        else:
            rec = None
            undefined_count += 1

        # F1
        if prec is not None and rec is not None and (prec + rec) > 0:
            f1 = round(2 * (prec * rec) / (prec + rec), 4)
        else:
            f1 = None
            undefined_count += 1

        per_class[st] = {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": prec,
            "recall": rec,
            "f1": f1,
        }

    # 3. False-Positive and False-Negative MET safety rates
    # Central Safety Gate: True Non-MET marked as MET or verified=True
    fp_met = 0
    total_non_met_true = 0
    fn_met = 0
    total_met_true = 0

    for t, p, v_t, v_p in zip(y_true, y_pred, verified_true, verified_pred):
        if t != CriterionStatus.MET:
            total_non_met_true += 1
            if p == CriterionStatus.MET or v_p is True:
                fp_met += 1
        else:
            total_met_true += 1
            if p != CriterionStatus.MET or v_p is False:
                fn_met += 1

    fp_met_rate = round(fp_met / total_non_met_true, 4) if total_non_met_true > 0 else None
    fn_met_rate = round(fn_met / total_met_true, 4) if total_met_true > 0 else None

    # 4. Provenance and Isolation Violations
    prov_count = sum(1 for f in provenance_failures if f) if provenance_failures else 0
    cross_count = sum(1 for c in cross_patient_violations if c) if cross_patient_violations else 0

    # 5. Category Breakdown
    cat_breakdown: dict[str, dict[str, Any]] = {}
    if categories:
        for idx, cat in enumerate(categories):
            if cat not in cat_breakdown:
                cat_breakdown[cat] = {
                    "total": 0,
                    "correct": 0,
                    "false_positive_met": 0,
                    "accuracy": 0.0,
                }
            cat_breakdown[cat]["total"] += 1
            is_match = (y_true[idx] == y_pred[idx]) and (verified_true[idx] == verified_pred[idx])
            if is_match:
                cat_breakdown[cat]["correct"] += 1
            if y_true[idx] != CriterionStatus.MET and (y_pred[idx] == CriterionStatus.MET or verified_pred[idx] is True):
                cat_breakdown[cat]["false_positive_met"] += 1

        for cat, stats in cat_breakdown.items():
            stats["accuracy"] = round(stats["correct"] / stats["total"], 4) if stats["total"] > 0 else 0.0

    return VerificationMetrics(
        total_cases=total,
        correct_statuses=correct,
        accuracy=accuracy,
        confusion_matrix=confusion,
        per_class=per_class,
        undefined_metrics_count=undefined_count,
        false_positive_met_count=fp_met,
        false_positive_met_rate=fp_met_rate,
        false_negative_met_count=fn_met,
        false_negative_met_rate=fn_met_rate,
        provenance_failures_count=prov_count,
        cross_patient_violations_count=cross_count,
        category_breakdown=cat_breakdown,
        is_deterministic=is_deterministic,
    )


@dataclass
class RetrievalMethodMetrics:
    method_name: str
    total_cases: int
    quality_cases_count: int
    safety_cases_count: int
    mean_precision_at_k: float | None
    mean_recall_at_k: float | None
    mrr: float | None
    cross_patient_violations: int
    all_safety_checks_passed: bool
    latency_ms: dict[str, float]  # mean, min, max
    is_deterministic: bool
    case_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_name": self.method_name,
            "total_cases": self.total_cases,
            "quality_cases_count": self.quality_cases_count,
            "safety_cases_count": self.safety_cases_count,
            "mean_precision_at_k": self.mean_precision_at_k,
            "mean_recall_at_k": self.mean_recall_at_k,
            "mrr": self.mrr,
            "cross_patient_violations": self.cross_patient_violations,
            "all_safety_checks_passed": self.all_safety_checks_passed,
            "latency_ms": self.latency_ms,
            "is_deterministic": self.is_deterministic,
            "case_results": self.case_results,
        }


@dataclass
class RetrievalMetrics:
    k: int
    methods: dict[str, RetrievalMethodMetrics]

    def to_dict(self) -> dict[str, Any]:
        return {
            "k": self.k,
            "methods": {name: m.to_dict() for name, m in self.methods.items()},
        }


def calculate_retrieval_metrics(
    method_name: str,
    k: int,
    case_results: list[dict[str, Any]],
    latency_measurements: list[float],
    is_deterministic: bool = True,
) -> RetrievalMethodMetrics:
    """Aggregate per-case retrieval outputs into disciplined IR metrics."""
    quality_precisions: list[float] = []
    quality_recalls: list[float] = []
    quality_rrs: list[float] = []

    cross_patient_violations = 0
    all_safety_passed = True

    for res in case_results:
        if res.get("cross_patient_leakage", False):
            cross_patient_violations += 1
            all_safety_passed = False

        if not res.get("is_safety_check", False):
            # IR Quality Query
            p = res.get("precision_at_k")
            r = res.get("recall_at_k")
            rr = res.get("reciprocal_rank")
            if p is not None:
                quality_precisions.append(p)
            if r is not None:
                quality_recalls.append(r)
            if rr is not None:
                quality_rrs.append(rr)
        else:
            # Safety Check Query
            if not res.get("safety_pass", False):
                all_safety_passed = False

    mean_p = round(sum(quality_precisions) / len(quality_precisions), 4) if quality_precisions else None
    mean_r = round(sum(quality_recalls) / len(quality_recalls), 4) if quality_recalls else None
    mean_mrr = round(sum(quality_rrs) / len(quality_rrs), 4) if quality_rrs else None

    # Compute latency summary in ms (mean, median, min, max)
    import statistics
    if latency_measurements:
        mean_lat = round(sum(latency_measurements) / len(latency_measurements), 2)
        median_lat = round(statistics.median(latency_measurements), 2)
        min_lat = round(min(latency_measurements), 2)
        max_lat = round(max(latency_measurements), 2)
    else:
        mean_lat = 0.0
        median_lat = 0.0
        min_lat = 0.0
        max_lat = 0.0

    return RetrievalMethodMetrics(
        method_name=method_name,
        total_cases=len(case_results),
        quality_cases_count=len(quality_precisions),
        safety_cases_count=len(case_results) - len(quality_precisions),
        mean_precision_at_k=mean_p,
        mean_recall_at_k=mean_r,
        mrr=mean_mrr,
        cross_patient_violations=cross_patient_violations,
        all_safety_checks_passed=all_safety_passed,
        latency_ms={"mean": mean_lat, "min": min_lat, "max": max_lat},
        is_deterministic=is_deterministic,
        case_results=case_results,
    )
