"""AuthOS Evaluation Framework & Reliability Baseline Package.

Version: 1.0.0
Evaluation Dataset Version: eval-dataset-v1.0
"""
from backend.evaluation.dataset import (
    DATASET_VERSION,
    MANDATORY_CATEGORIES,
    EvaluationDataset,
    RetrievalEvalCase,
    VerificationEvalCase,
    load_default_evaluation_dataset,
)
from backend.evaluation.metrics import (
    RetrievalMetrics,
    VerificationMetrics,
    calculate_retrieval_metrics,
    calculate_verification_metrics,
)

__all__ = [
    "DATASET_VERSION",
    "MANDATORY_CATEGORIES",
    "EvaluationDataset",
    "VerificationEvalCase",
    "RetrievalEvalCase",
    "load_default_evaluation_dataset",
    "VerificationMetrics",
    "RetrievalMetrics",
    "calculate_verification_metrics",
    "calculate_retrieval_metrics",
]
