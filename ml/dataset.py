"""
ml/dataset.py — генератор синтетического датасета для обучения Random Forest.

Методология:
  Каждый класс риска соответствует реальному профилю поведения ИП:
    0 = low    — обычная деловая активность
    1 = medium — частичное несоответствие критериям ЦБ РФ
    2 = high   — явные признаки схем по 18-МР / 19-МР ЦБ РФ

  Признаки генерируются из нормальных распределений с параметрами, подобранными
  по нормативным порогам ЦБ РФ.

  Для реалистичной корреляции признаков внутри класса используется
  латентный фактор интенсивности риска (общий шум):
    высокая интенсивность → одновременное ухудшение всех показателей.

Запуск: python ml/dataset.py  → сохраняет ml/data.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

N_SAMPLES = 5000
RANDOM_STATE = 42
OUTPUT_PATH = Path(__file__).parent / "data.csv"

# Каноническое имя признака → порог риска (из config.py / нормативов ЦБ РФ)
THRESHOLDS: dict[str, float] = {
    "cash_ratio":                0.30,   # 19-МР ЦБ РФ
    "tax_ratio":                 0.009,  # 18-МР ЦБ РФ  (риск если НИЖЕ)
    "transit_ratio":             0.50,   # 19-МР ЦБ РФ
    "okved_mismatch":            0.60,   # экспертное правило
    "avg_tx_norm":               1.00,   # 115-ФЗ, ст. 6 (риск если НИЖЕ)
    "counterparty_concentration": 0.80,  # 19-МР ЦБ РФ
    "fl_ratio":                  0.30,   # 19-МР ЦБ РФ
    "weekend_ratio":             0.30,   # экспертное правило
    "round_amount_ratio":        0.60,   # FATF Typologies (структурирование)
    "tx_frequency_norm":         0.50,   # экспертное правило (> 15 транзакций/день)
}

# Направление риска: +1 → "выше = опаснее", -1 → "ниже = опаснее"
RISK_DIRECTION: dict[str, int] = {
    "cash_ratio":                +1,
    "tax_ratio":                 -1,
    "transit_ratio":             +1,
    "okved_mismatch":            +1,
    "avg_tx_norm":               -1,
    "counterparty_concentration": +1,
    "fl_ratio":                  +1,
    "weekend_ratio":             +1,
    "round_amount_ratio":        +1,
    "tx_frequency_norm":         +1,
}

FEATURE_NAMES: list[str] = list(THRESHOLDS.keys())

# Распределение классов
CLASS_SHARES = {0: 0.60, 1: 0.25, 2: 0.15}
CLASS_LABELS = {0: "low", 1: "medium", 2: "high"}

# ---------------------------------------------------------------------------
# Параметры нормальных распределений per feature per class
#
# Формат: {feature: [(mean_low, std_low), (mean_med, std_med), (mean_high, std_high)]}
#
# Параметры подобраны так, чтобы:
#   - средние классов были разнесены относительно нормативных порогов ЦБ РФ
#   - стандартные отклонения давали разумный overlap между классами
#   - граничные значения вписывались в [0, 1]
# ---------------------------------------------------------------------------

_PARAMS: dict[str, list[tuple[float, float]]] = {
    #                               class 0 (low)         class 1 (medium)      class 2 (high)
    "cash_ratio":                [(0.08,  0.05),         (0.23,  0.08),         (0.52,  0.14)],
    "tax_ratio":                 [(0.065, 0.025),        (0.013, 0.005),        (0.003, 0.002)],
    "transit_ratio":             [(0.12,  0.08),         (0.36,  0.11),         (0.73,  0.13)],
    "okved_mismatch":            [(0.10,  0.09),         (0.43,  0.13),         (0.80,  0.12)],
    "avg_tx_norm":               [(0.77,  0.15),         (0.37,  0.13),         (0.09,  0.06)],
    "counterparty_concentration": [(0.22, 0.12),         (0.57,  0.13),         (0.88,  0.08)],
    "fl_ratio":                  [(0.05,  0.04),         (0.18,  0.07),         (0.47,  0.15)],
    # Признак 8: доля операций в выходные — у легального бизнеса мало, у схем — много
    "weekend_ratio":             [(0.07,  0.04),         (0.20,  0.07),         (0.42,  0.11)],
    # Признак 9: доля круглых сумм — у схем намеренно высокая (structuring)
    "round_amount_ratio":        [(0.20,  0.10),         (0.48,  0.12),         (0.78,  0.10)],
    # Признак 10: частота транзакций — схемы дробят на много мелких операций
    "tx_frequency_norm":         [(0.10,  0.06),         (0.35,  0.12),         (0.68,  0.14)],
}

# Жёсткие границы значений [lo, hi]
_CLIP: dict[str, tuple[float, float]] = {
    "cash_ratio":                (0.0, 1.0),
    "tax_ratio":                 (0.0, 0.30),   # >30% налогов — нереально
    "transit_ratio":             (0.0, 1.0),
    "okved_mismatch":            (0.0, 1.0),
    "avg_tx_norm":               (0.0, 1.0),
    "counterparty_concentration": (0.0, 1.0),
    "fl_ratio":                  (0.0, 1.0),
    "weekend_ratio":             (0.0, 1.0),
    "round_amount_ratio":        (0.0, 1.0),
    "tx_frequency_norm":         (0.0, 1.0),
}

# Сила корреляции через латентный фактор — доля от std каждого признака.
# 0.40 означает: latent_noise = direction * Z * (0.40 * std_feature).
# Масштабирование по std гарантирует, что мелкие признаки (tax_ratio ≈ 0.003)
# не захлёстываются шумом, а крупные (cash_ratio ≈ 0.50) получают достаточную корреляцию.
_LATENT_STRENGTH = 0.40   # доля от std конкретного признака


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def generate_dataset(
    n_samples: int = N_SAMPLES,
    random_state: int = RANDOM_STATE,
) -> pd.DataFrame:
    """
    Сгенерировать синтетический датасет.

    Args:
        n_samples:    Число строк (по умолчанию 1000)
        random_state: Зерно RNG для воспроизводимости

    Returns:
        DataFrame с колонками:
          cash_ratio, tax_ratio, transit_ratio, okved_mismatch,
          avg_tx_norm, counterparty_concentration, fl_ratio,
          risk_class (int 0/1/2), risk_label (str low/medium/high)
    """
    rng = np.random.default_rng(random_state)
    counts = _split_counts(n_samples)

    parts_X: list[np.ndarray] = []
    parts_y: list[np.ndarray] = []

    for class_id, n in counts.items():
        X = _generate_class(rng, class_id, n)
        y = np.full(n, class_id, dtype=np.int32)
        parts_X.append(X)
        parts_y.append(y)

    X_all = np.vstack(parts_X)
    y_all = np.concatenate(parts_y)

    # Перемешиваем строки
    perm = rng.permutation(len(y_all))
    X_all = X_all[perm]
    y_all = y_all[perm]

    df = pd.DataFrame(X_all, columns=FEATURE_NAMES)
    df["risk_class"] = y_all
    df["risk_label"] = df["risk_class"].map(CLASS_LABELS)

    return df


def print_statistics(df: pd.DataFrame) -> None:
    """Вывести сводную статистику датасета в stdout."""
    n = len(df)
    sep = "-" * 65

    print(sep)
    print(f"  Dataset: {n} rows x {len(FEATURE_NAMES)} features + label")
    print(sep)

    # Распределение классов
    print("\n  Class distribution:")
    for label, cnt in df["risk_label"].value_counts().sort_index().items():
        bar = "#" * int(cnt / n * 30)
        print(f"    {label:<8} {cnt:>4}  ({cnt / n:.1%})  {bar}")

    # Средние признаков по классам
    print("\n  Feature means by class (threshold shown, ^ = higher is risky, v = lower is risky):")
    header = f"  {'Feature':<30} {'low':>8} {'medium':>8} {'high':>8}  {'thresh':>7}  dir"
    print(header)
    print("  " + "-" * 63)

    means = df.groupby("risk_label")[FEATURE_NAMES].mean()
    for feat in FEATURE_NAMES:
        lo  = means.loc["low",    feat]
        med = means.loc["medium", feat]
        hi  = means.loc["high",   feat]
        thr = THRESHOLDS[feat]
        d   = "^" if RISK_DIRECTION[feat] == +1 else "v"
        print(f"  {feat:<30} {lo:>8.4f} {med:>8.4f} {hi:>8.4f}  {thr:>7.4f}  {d}")

    # Доля «сработавших» признаков по классам
    print("\n  Fraction of samples exceeding threshold (or below, for tax/avg_tx):")
    for feat in FEATURE_NAMES:
        thr = THRESHOLDS[feat]
        direction = RISK_DIRECTION[feat]
        row_parts = [f"  {feat:<30}"]
        for label in ["low", "medium", "high"]:
            sub = df[df["risk_label"] == label][feat]
            frac = (sub >= thr).mean() if direction == +1 else (sub < thr).mean()
            row_parts.append(f"{frac:>7.1%}")
        print("  ".join(row_parts))

    print(f"\n{sep}")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _split_counts(n: int) -> dict[int, int]:
    """Разбить n на классы 60/25/15%."""
    n0 = round(n * CLASS_SHARES[0])
    n1 = round(n * CLASS_SHARES[1])
    n2 = n - n0 - n1
    return {0: n0, 1: n1, 2: n2}


def _generate_class(rng: np.random.Generator, class_id: int, n: int) -> np.ndarray:
    """
    Сгенерировать матрицу признаков (n × 7) для одного класса.

    Добавляет латентный фактор интенсивности риска, создающий
    реалистичную межпризнаковую корреляцию:
      - при высокой интенсивности все «опасные» признаки смещаются в сторону риска
      - при низкой — все смещаются в безопасную сторону
    """
    # Латентный фактор: общий "уровень риска" внутри класса
    intensity = rng.normal(0.0, 1.0, n)   # Z ~ N(0,1)

    columns: list[np.ndarray] = []
    for feature in FEATURE_NAMES:
        mean, std = _PARAMS[feature][class_id]
        direction = RISK_DIRECTION[feature]
        lo, hi = _CLIP[feature]

        # Базовый нормальный шум
        col = rng.normal(loc=mean, scale=std, size=n)

        # Корреляция через латентный фактор, масштабированная по std признака.
        # Чем меньше std (как у tax_ratio), тем меньше вклад латентного шума.
        col += direction * intensity * (std * _LATENT_STRENGTH)

        col = np.clip(col, lo, hi)
        columns.append(col)

    return np.column_stack(columns)


# ---------------------------------------------------------------------------
# Точка входа: генерация и сохранение
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df = generate_dataset()
    df.to_csv(OUTPUT_PATH, index=False)

    print(f"\nSaved: {OUTPUT_PATH.resolve()}\n")
    print_statistics(df)
