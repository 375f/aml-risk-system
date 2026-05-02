"""
module1/classifier.py — обёртка над обученным RandomForestClassifier.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from sklearn.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

_MODEL_PATH = Path(__file__).parent.parent / "ml" / "model.joblib"

FEATURE_KEYS: list[str] = [
    "cash_ratio",
    "tax_ratio",
    "transit_ratio",
    "okved_mismatch",
    "avg_tx_norm",
    "counterparty_concentration",
    "fl_ratio",
]

_LABELS: dict[int, str] = {0: "low", 1: "medium", 2: "high"}

# ---------------------------------------------------------------------------
# Кэш модели (загружается один раз)
# ---------------------------------------------------------------------------

_model: Pipeline | None = None


def load_model(path: Path | str = _MODEL_PATH) -> None:
    """Загрузить модель из файла и сохранить в памяти."""
    global _model
    _model = joblib.load(path)


def _get_model() -> Pipeline:
    global _model
    if _model is None:
        load_model()
    return _model


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def predict(features_dict: dict) -> dict:
    """
    Классифицировать набор признаков.

    Args:
        features_dict: ключи из FEATURE_KEYS, значения float [0, 1].

    Returns:
        {
            'risk_level':  'low' | 'medium' | 'high',
            'risk_proba':  float,          # вероятность предсказанного класса
            'importances': dict[str, float] # feature_importances_ RF
        }
    """
    model = _get_model()

    X = np.array(
        [[float(features_dict.get(k, 0.0)) for k in FEATURE_KEYS]],
        dtype=np.float64,
    )

    class_id: int  = int(model.predict(X)[0])
    proba: np.ndarray = model.predict_proba(X)[0]

    rf = model.named_steps["clf"]
    importances: dict[str, float] = {
        k: float(v) for k, v in zip(FEATURE_KEYS, rf.feature_importances_)
    }

    return {
        "risk_level":  _LABELS[class_id],
        "risk_proba":  float(proba[class_id]),
        "importances": importances,
    }
