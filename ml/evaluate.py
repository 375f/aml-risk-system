"""
ml/evaluate.py — оценка качества модели на тест-сете.

Загружает ml/model.joblib и ml/data.csv, печатает:
  - accuracy, F1-macro, F1 по каждому классу
  - confusion matrix

Запуск: python ml/evaluate.py
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split

_DIR = Path(__file__).parent
DATA_PATH  = _DIR / "data.csv"
MODEL_PATH = _DIR / "model.joblib"

FEATURE_NAMES: list[str] = [
    "cash_ratio",
    "tax_ratio",
    "transit_ratio",
    "okved_mismatch",
    "avg_tx_norm",
    "counterparty_concentration",
    "fl_ratio",
]
LABEL_NAMES = ["low", "medium", "high"]


def evaluate(
    model_path: Path = MODEL_PATH,
    data_path: Path  = DATA_PATH,
    test_size: float = 0.20,
    random_state: int = 42,
) -> dict:
    """
    Оценить модель на отложенной тест-выборке.

    Returns:
        dict с ключами: accuracy, f1_macro, f1_per_class, confusion_matrix
    """
    model = joblib.load(model_path)

    df = pd.read_csv(data_path)
    X = df[FEATURE_NAMES].values
    y = df["risk_class"].values

    _, X_test, _, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    y_pred = model.predict(X_test)

    acc      = float(accuracy_score(y_test, y_pred))
    f1_macro = float(f1_score(y_test, y_pred, average="macro", zero_division=0))
    f1_per   = f1_score(y_test, y_pred, labels=[0, 1, 2],
                        average=None, zero_division=0).tolist()
    cm       = confusion_matrix(y_test, y_pred, labels=[0, 1, 2]).tolist()

    return {
        "accuracy":       acc,
        "f1_macro":       f1_macro,
        "f1_per_class":   dict(zip(LABEL_NAMES, f1_per)),
        "confusion_matrix": cm,
    }


def print_report(metrics: dict) -> None:
    sep = "=" * 55
    print(f"\n{sep}")
    print(f"  Evaluation report")
    print(sep)
    print(f"  Accuracy  : {metrics['accuracy']:.4f}")
    print(f"  F1-macro  : {metrics['f1_macro']:.4f}")
    print()
    print("  F1 per class:")
    for label, score in metrics["f1_per_class"].items():
        bar = "#" * int(score * 20)
        print(f"    {label:<8} {score:.4f}  {bar}")
    print()
    print("  Confusion matrix (rows=actual, cols=predicted):")
    print(f"  {'':>8} " + "  ".join(f"{n:>6}" for n in LABEL_NAMES))
    for i, row in enumerate(metrics["confusion_matrix"]):
        print(f"  {LABEL_NAMES[i]:>8} " + "  ".join(f"{v:>6}" for v in row))
    print(f"{sep}\n")


if __name__ == "__main__":
    metrics = evaluate()
    print_report(metrics)
