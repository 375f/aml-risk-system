"""
ml/train.py — обучение RandomForestClassifier на синтетическом датасете.

Результат:
  ml/model.joblib  — сериализованная модель (sklearn Pipeline: StandardScaler + RFC)

Запуск: python ml/train.py
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Обучение
# ---------------------------------------------------------------------------

def train(
    data_path: Path = DATA_PATH,
    model_path: Path = MODEL_PATH,
    test_size: float = 0.20,
    random_state: int = 42,
) -> Pipeline:
    df = pd.read_csv(data_path)
    X = df[FEATURE_NAMES].values
    y = df["risk_class"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,
    )

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf",    RandomForestClassifier(
            class_weight="balanced",
            random_state=random_state,
        )),
    ])

    param_grid = {
        "clf__n_estimators": [50, 100, 200],
        "clf__max_depth":    [5, 10, None],
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=random_state)
    grid = GridSearchCV(
        pipe,
        param_grid,
        cv=cv,
        scoring="f1_macro",
        n_jobs=-1,
        refit=True,
    )

    n_combos = len(param_grid["clf__n_estimators"]) * len(param_grid["clf__max_depth"])
    print(f"Training on {len(X_train)} samples, GridSearchCV ({n_combos} combos x {cv.n_splits} folds)...\n")
    grid.fit(X_train, y_train)

    best: Pipeline = grid.best_estimator_
    print(f"Best params  : {grid.best_params_}")
    print(f"CV f1_macro  : {grid.best_score_:.4f}\n")

    y_pred = best.predict(X_test)
    _print_metrics(y_test, y_pred)

    joblib.dump(best, model_path)
    print(f"Model saved  : {model_path.resolve()}")

    return best


def _print_metrics(y_test: np.ndarray, y_pred: np.ndarray) -> None:
    labels      = [0, 1, 2]
    label_names = ["low", "medium", "high"]

    print("=" * 55)
    print("  Test-set classification report")
    print("=" * 55)
    print(classification_report(
        y_test, y_pred,
        labels=labels,
        target_names=label_names,
        zero_division=0,
    ))

    cm = confusion_matrix(y_test, y_pred, labels=labels)
    print("  Confusion matrix (rows=actual, cols=predicted):"  )
    print(f"  {'':>8} " + "  ".join(f"{n:>6}" for n in label_names))
    for i, row in enumerate(cm):
        print(f"  {label_names[i]:>8} " + "  ".join(f"{v:>6}" for v in row))
    print("=" * 55 + "\n")


if __name__ == "__main__":
    train()
