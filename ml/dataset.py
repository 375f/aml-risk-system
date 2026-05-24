"""
ml/dataset.py — генератор синтетического датасета для обучения Random Forest.

Методология (улучшенная версия):
  Три стратегии генерации для реалистичности:

  A) Основные образцы (65%) — Beta-распределения вместо обрезанных гауссовых.
     Beta(a, b) корректно моделирует признаки в [0,1] без артефактов обрезания.
     Классы разнесены по параметрам, но с контролируемым перекрытием.

  B) Граничные случаи (20%) — признаки случайно сэмплируются у порогов ЦБ РФ,
     метки присваиваются правилом «сколько порогов нарушено»:
       0-1 нарушений → low, 2-3 → medium, 4+ → high.
     Это создаёт трудные для модели примеры, имитирующие реальные пограничные ситуации.

  C) Отраслевые профили (15%) — реальные бизнес-сценарии:
     - Розница/общепит: законно высокий cash_ratio, всё остальное в норме → low/medium
     - ИТ-компания: высокая концентрация контрагентов (2-3 подрядчика) → low
     - Строительство: много круглых сумм (сметы) → low/medium
     - Транзитная схема: поступление → списание за 1-3 дня, высокая обналичка → high
     - Схема через физлиц: высокий fl_ratio + cash + низкая налоговая → high

  Корреляция внутри каждого класса обеспечивается латентным фактором интенсивности риска.

Запуск: python ml/dataset.py  → сохраняет ml/data.csv
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

N_SAMPLES    = 10_000
RANDOM_STATE = 42
OUTPUT_PATH  = Path(__file__).parent / "data.csv"

FEATURE_NAMES: list[str] = [
    "cash_ratio",
    "tax_ratio",
    "transit_ratio",
    "okved_mismatch",
    "avg_tx_norm",
    "counterparty_concentration",
    "fl_ratio",
    "weekend_ratio",
    "round_amount_ratio",
    "tx_frequency_norm",
]

# Пороги риска (из config.py / нормативов ЦБ РФ)
THRESHOLDS: dict[str, float] = {
    "cash_ratio":                 0.30,
    "tax_ratio":                  0.009,
    "transit_ratio":              0.50,
    "okved_mismatch":             0.60,
    "avg_tx_norm":                1.00,
    "counterparty_concentration": 0.80,
    "fl_ratio":                   0.30,
    "weekend_ratio":              0.30,
    "round_amount_ratio":         0.60,
    "tx_frequency_norm":          0.50,
}

# +1 → выше порога = опаснее, -1 → ниже порога = опаснее
RISK_DIRECTION: dict[str, int] = {
    "cash_ratio":                 +1,
    "tax_ratio":                  -1,
    "transit_ratio":              +1,
    "okved_mismatch":             +1,
    "avg_tx_norm":                -1,
    "counterparty_concentration": +1,
    "fl_ratio":                   +1,
    "weekend_ratio":              +1,
    "round_amount_ratio":         +1,
    "tx_frequency_norm":          +1,
}

CLASS_SHARES = {0: 0.55, 1: 0.28, 2: 0.17}
CLASS_LABELS = {0: "low", 1: "medium", 2: "high"}

# Доли стратегий генерации
_SHARE_CORE     = 0.65   # A: основные образцы
_SHARE_EDGE     = 0.20   # B: граничные случаи
_SHARE_PROFILES = 0.15   # C: отраслевые профили

# Сила латентной корреляции внутри класса (доля от std признака)
_LATENT_STRENGTH = 0.55


# ---------------------------------------------------------------------------
# Параметры Beta-распределений per feature per class
#
# Каждый признак описывается парой (mean, std) в естественных единицах.
# Функция _beta_sample() преобразует их в параметры Beta(a, b).
#
# Ключевые отличия от предыдущей версии:
#  - Больший std → больше перекрытия между классами (реалистичнее)
#  - Средние смещены ближе к порогам (особенно для medium)
#  - tax_ratio сохраняет свой маленький диапазон [0, 0.30]
# ---------------------------------------------------------------------------

_PARAMS: dict[str, list[tuple[float, float]]] = {
    #                               class 0 (low)           class 1 (medium)        class 2 (high)
    #                               (mean,   std)           (mean,   std)            (mean,   std)
    "cash_ratio":                [(0.09,  0.07),          (0.27,  0.11),          (0.51,  0.16)],
    "tax_ratio":                 [(0.060, 0.028),         (0.016, 0.009),         (0.004, 0.003)],
    "transit_ratio":             [(0.14,  0.10),          (0.40,  0.13),          (0.73,  0.14)],
    "okved_mismatch":            [(0.11,  0.10),          (0.45,  0.15),          (0.80,  0.13)],
    "avg_tx_norm":               [(0.74,  0.18),          (0.38,  0.16),          (0.10,  0.07)],
    "counterparty_concentration":[(0.24,  0.14),          (0.59,  0.15),          (0.87,  0.09)],
    "fl_ratio":                  [(0.06,  0.05),          (0.21,  0.10),          (0.47,  0.16)],
    "weekend_ratio":             [(0.08,  0.06),          (0.22,  0.09),          (0.42,  0.12)],
    "round_amount_ratio":        [(0.22,  0.12),          (0.48,  0.14),          (0.77,  0.11)],
    "tx_frequency_norm":         [(0.11,  0.07),          (0.37,  0.14),          (0.68,  0.15)],
}

# Допустимые диапазоны значений
_CLIP: dict[str, tuple[float, float]] = {
    "cash_ratio":                 (0.0, 1.0),
    "tax_ratio":                  (0.0, 0.30),
    "transit_ratio":              (0.0, 1.0),
    "okved_mismatch":             (0.0, 1.0),
    "avg_tx_norm":                (0.0, 1.0),
    "counterparty_concentration": (0.0, 1.0),
    "fl_ratio":                   (0.0, 1.0),
    "weekend_ratio":              (0.0, 1.0),
    "round_amount_ratio":         (0.0, 1.0),
    "tx_frequency_norm":          (0.0, 1.0),
}


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def generate_dataset(
    n_samples: int = N_SAMPLES,
    random_state: int = RANDOM_STATE,
) -> pd.DataFrame:
    """
    Сгенерировать синтетический датасет из трёх стратегий.

    Returns:
        DataFrame: FEATURE_NAMES + risk_class (int) + risk_label (str)
    """
    rng = np.random.default_rng(random_state)

    n_core     = int(n_samples * _SHARE_CORE)
    n_edge     = int(n_samples * _SHARE_EDGE)
    n_profiles = n_samples - n_core - n_edge

    X_core, y_core         = _generate_core(rng, n_core)
    X_edge, y_edge         = _generate_edge_cases(rng, n_edge)
    X_profiles, y_profiles = _generate_sector_profiles(rng, n_profiles)

    X_raw = np.vstack([X_core, X_edge, X_profiles])
    y_raw = np.concatenate([y_core, y_edge, y_profiles])

    # Принудительно привести к целевому балансу классов (55/28/17).
    # Без этого стратегии B и C могут сдвинуть пропорции, и модель
    # начнёт слишком агрессивно или слишком мягко классифицировать.
    X_all, y_all = _resample_to_shares(X_raw, y_raw, CLASS_SHARES, n_samples, rng)

    perm  = rng.permutation(len(y_all))
    X_all = X_all[perm]
    y_all = y_all[perm]

    df = pd.DataFrame(X_all, columns=FEATURE_NAMES)
    df["risk_class"] = y_all.astype(int)
    df["risk_label"] = df["risk_class"].map(CLASS_LABELS)
    return df


def print_statistics(df: pd.DataFrame) -> None:
    """Вывести сводную статистику датасета в stdout."""
    n   = len(df)
    sep = "-" * 68

    print(f"\n{sep}")
    print(f"  Dataset: {n} strok x {len(FEATURE_NAMES)} priznakov + metka")
    print(sep)

    print("\n  Распределение классов:")
    for label, cnt in df["risk_label"].value_counts().sort_index().items():
        bar = "#" * int(cnt / n * 30)
        print(f"    {label:<8} {cnt:>5}  ({cnt / n:.1%})  {bar}")

    print("\n  Средние признаков по классам (порог = thresh, ^ выше опаснее, v ниже):")
    header = f"  {'Признак':<30} {'low':>8} {'medium':>8} {'high':>8}  {'thresh':>7}  dir"
    print(header)
    print("  " + "-" * 66)
    means = df.groupby("risk_label")[FEATURE_NAMES].mean()
    for feat in FEATURE_NAMES:
        lo  = means.loc["low",    feat]
        med = means.loc["medium", feat]
        hi  = means.loc["high",   feat]
        thr = THRESHOLDS[feat]
        d   = "^" if RISK_DIRECTION[feat] == +1 else "v"
        print(f"  {feat:<30} {lo:>8.4f} {med:>8.4f} {hi:>8.4f}  {thr:>7.4f}  {d}")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# Стратегия A — основные образцы из Beta-распределений
# ---------------------------------------------------------------------------

def _generate_core(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """65% датасета: Beta-распределения с латентной корреляцией внутри класса."""
    counts = _split_counts(n, CLASS_SHARES)
    parts_X, parts_y = [], []

    for class_id, cnt in counts.items():
        intensity = rng.normal(0.0, 1.0, cnt)
        columns   = []
        for feat in FEATURE_NAMES:
            mean, std  = _PARAMS[feat][class_id]
            direction  = RISK_DIRECTION[feat]
            lo, hi     = _CLIP[feat]
            col = _beta_sample(rng, mean, std, cnt, lo, hi)
            col += direction * intensity * (std * _LATENT_STRENGTH)
            col  = np.clip(col, lo, hi)
            columns.append(col)
        parts_X.append(np.column_stack(columns))
        parts_y.append(np.full(cnt, class_id))

    return np.vstack(parts_X), np.concatenate(parts_y)


# ---------------------------------------------------------------------------
# Стратегия B — граничные случаи (near-threshold)
# ---------------------------------------------------------------------------

def _generate_edge_cases(
    rng: np.random.Generator, n: int
) -> tuple[np.ndarray, np.ndarray]:
    """
    20% датасета: признаки сэмплируются у самих порогов (±ε).
    Метка определяется правилом: считаем сколько порогов нарушено.

    Это создаёт трудные примеры, имитирующие реальные пограничные ситуации:
    - ИП с cash_ratio=0.32 (чуть выше 30%) при нормальных остальных признаках
    - Транзитная схема, где только transit_ratio выбивается
    """
    rows, labels = [], []
    for _ in range(n):
        row = {}
        for feat in FEATURE_NAMES:
            lo, hi  = _CLIP[feat]
            thr     = THRESHOLDS[feat]
            direct  = RISK_DIRECTION[feat]

            # Вероятности зон: 45% «норма», 30% «у порога», 25% «риск».
            # Было [1/3, 1/3, 1/3] → при 10 признаках давало E[нарушений]=3.3,
            # P(4+ нарушений)≈44% → слишком много меток high в тренировочных данных.
            # Теперь E[нарушений]=2.5, P(5+ нарушений)≈8% → реалистичный баланс.
            zone = int(rng.choice(3, p=[0.45, 0.30, 0.25]))  # 0=safe,1=at,2=risky
            eps  = (hi - lo) * 0.08

            if direct == +1:
                if zone == 0:
                    val = rng.uniform(lo, max(lo, thr - eps))
                elif zone == 1:
                    val = rng.uniform(max(lo, thr - eps), min(hi, thr + eps))
                else:
                    val = rng.uniform(min(hi, thr + eps), hi)
            else:
                if zone == 0:
                    val = rng.uniform(min(hi, thr + eps), hi)
                elif zone == 1:
                    val = rng.uniform(max(lo, thr - eps), min(hi, thr + eps))
                else:
                    val = rng.uniform(lo, max(lo, thr - eps))

            row[feat] = float(np.clip(val, lo, hi))

        # Метка по числу нарушенных порогов.
        # Было: 4+ → high. При вероятности 1/3 это давало ~44% high в edge cases.
        # Теперь: 5+ → high. При вероятности 0.25 это даёт ~8% high в edge cases.
        violations = _count_violations(row)
        if violations <= 2:
            label = 0
        elif violations <= 4:
            label = 1
        else:
            label = 2

        rows.append([row[f] for f in FEATURE_NAMES])
        labels.append(label)

    return np.array(rows), np.array(labels)


# ---------------------------------------------------------------------------
# Стратегия C — отраслевые профили
# ---------------------------------------------------------------------------

def _generate_sector_profiles(
    rng: np.random.Generator, n: int
) -> tuple[np.ndarray, np.ndarray]:
    """
    15% датасета: реалистичные бизнес-профили, которые могут выглядеть подозрительно
    по одному-двум признакам, но в целом не являются схемами.

    Также включает явные схемы с характерными комбинациями признаков.
    """
    profiles = [
        # ──────────────────────────────────────────────────────────────────
        # ЗАКОННЫЙ БИЗНЕС — профили с высокими, но нормальными для отрасли значениями
        # ──────────────────────────────────────────────────────────────────

        # Розничный магазин / кафе: много наличных — это норма для общепита
        {
            "label": 0,
            "features": {
                "cash_ratio":                (0.38, 0.08),   # выше 30%, но норма для ритейла
                "tax_ratio":                 (0.045, 0.015),
                "transit_ratio":             (0.10, 0.07),
                "okved_mismatch":            (0.08, 0.06),
                "avg_tx_norm":               (0.55, 0.15),
                "counterparty_concentration":(0.30, 0.12),
                "fl_ratio":                  (0.08, 0.05),
                "weekend_ratio":             (0.28, 0.08),   # выходные — рабочие дни
                "round_amount_ratio":        (0.18, 0.09),
                "tx_frequency_norm":         (0.15, 0.08),
            }
        },

        # ИТ-компания: 2-3 крупных заказчика → высокая концентрация, но не схема
        {
            "label": 0,
            "features": {
                "cash_ratio":                (0.02, 0.02),
                "tax_ratio":                 (0.055, 0.020),
                "transit_ratio":             (0.09, 0.06),
                "okved_mismatch":            (0.06, 0.05),
                "avg_tx_norm":               (0.85, 0.12),
                "counterparty_concentration":(0.88, 0.06),   # выше 80%, но норма для ИТ
                "fl_ratio":                  (0.04, 0.03),
                "weekend_ratio":             (0.06, 0.04),
                "round_amount_ratio":        (0.15, 0.08),
                "tx_frequency_norm":         (0.08, 0.05),
            }
        },

        # Строительный подрядчик: крупные круглые суммы (сметы, этапы работ)
        {
            "label": 0,
            "features": {
                "cash_ratio":                (0.10, 0.06),
                "tax_ratio":                 (0.040, 0.015),
                "transit_ratio":             (0.18, 0.09),
                "okved_mismatch":            (0.12, 0.08),
                "avg_tx_norm":               (0.65, 0.18),
                "counterparty_concentration":(0.55, 0.14),
                "fl_ratio":                  (0.07, 0.05),
                "weekend_ratio":             (0.04, 0.03),
                "round_amount_ratio":        (0.68, 0.10),   # выше 60%, но сметы круглые
                "tx_frequency_norm":         (0.10, 0.06),
            }
        },

        # Транспортная/логистическая компания: быстрый оборот средств (норма)
        {
            "label": 1,
            "features": {
                "cash_ratio":                (0.08, 0.05),
                "tax_ratio":                 (0.025, 0.010),
                "transit_ratio":             (0.55, 0.10),   # транзит высокий, но это логистика
                "okved_mismatch":            (0.15, 0.09),
                "avg_tx_norm":               (0.45, 0.15),
                "counterparty_concentration":(0.40, 0.14),
                "fl_ratio":                  (0.06, 0.04),
                "weekend_ratio":             (0.12, 0.06),
                "round_amount_ratio":        (0.25, 0.10),
                "tx_frequency_norm":         (0.28, 0.12),
            }
        },

        # Недавно открывшийся ИП: мало налогов (просто не заработал ещё)
        {
            "label": 1,
            "features": {
                "cash_ratio":                (0.18, 0.09),
                "tax_ratio":                 (0.005, 0.003),  # ниже порога, но стартап
                "transit_ratio":             (0.15, 0.08),
                "okved_mismatch":            (0.22, 0.12),
                "avg_tx_norm":               (0.30, 0.14),
                "counterparty_concentration":(0.65, 0.14),
                "fl_ratio":                  (0.10, 0.07),
                "weekend_ratio":             (0.14, 0.08),
                "round_amount_ratio":        (0.30, 0.12),
                "tx_frequency_norm":         (0.20, 0.10),
            }
        },

        # ──────────────────────────────────────────────────────────────────
        # СХЕМЫ — характерные AML-паттерны с явными комбинациями признаков
        # ──────────────────────────────────────────────────────────────────

        # Обналичивание через физлиц: cash + fl_ratio + низкие налоги
        {
            "label": 2,
            "features": {
                "cash_ratio":                (0.55, 0.14),
                "tax_ratio":                 (0.003, 0.002),
                "transit_ratio":             (0.40, 0.13),
                "okved_mismatch":            (0.72, 0.12),
                "avg_tx_norm":               (0.08, 0.05),
                "counterparty_concentration":(0.75, 0.12),
                "fl_ratio":                  (0.58, 0.15),
                "weekend_ratio":             (0.38, 0.11),
                "round_amount_ratio":        (0.80, 0.09),
                "tx_frequency_norm":         (0.72, 0.14),
            }
        },

        # Транзитная схема: поступление → немедленное перечисление
        {
            "label": 2,
            "features": {
                "cash_ratio":                (0.35, 0.12),
                "tax_ratio":                 (0.004, 0.003),
                "transit_ratio":             (0.87, 0.08),
                "okved_mismatch":            (0.78, 0.11),
                "avg_tx_norm":               (0.12, 0.07),
                "counterparty_concentration":(0.91, 0.06),
                "fl_ratio":                  (0.25, 0.10),
                "weekend_ratio":             (0.44, 0.11),
                "round_amount_ratio":        (0.75, 0.11),
                "tx_frequency_norm":         (0.80, 0.12),
            }
        },

        # Структурирование (дробление платежей): round + frequency + fl
        {
            "label": 2,
            "features": {
                "cash_ratio":                (0.20, 0.09),
                "tax_ratio":                 (0.005, 0.003),
                "transit_ratio":             (0.60, 0.13),
                "okved_mismatch":            (0.65, 0.13),
                "avg_tx_norm":               (0.06, 0.04),
                "counterparty_concentration":(0.65, 0.14),
                "fl_ratio":                  (0.45, 0.15),
                "weekend_ratio":             (0.40, 0.12),
                "round_amount_ratio":        (0.88, 0.07),
                "tx_frequency_norm":         (0.85, 0.10),
            }
        },

        # Пограничный случай: ИП с несколькими признаками выше порога, но не схема
        # (высокий транзит + концентрация характерны для оптовика с 1-2 поставщиками)
        {
            "label": 1,
            "features": {
                "cash_ratio":                (0.22, 0.09),
                "tax_ratio":                 (0.022, 0.010),
                "transit_ratio":             (0.58, 0.12),
                "okved_mismatch":            (0.38, 0.14),
                "avg_tx_norm":               (0.35, 0.13),
                "counterparty_concentration":(0.84, 0.09),
                "fl_ratio":                  (0.12, 0.07),
                "weekend_ratio":             (0.10, 0.06),
                "round_amount_ratio":        (0.45, 0.13),
                "tx_frequency_norm":         (0.30, 0.12),
            }
        },
    ]

    # Равномерно распределяем n по профилям
    rows, labels = [], []
    n_per_profile = max(1, n // len(profiles))

    for profile in profiles:
        cnt  = n_per_profile
        feat = profile["features"]
        label = profile["label"]

        for _ in range(cnt):
            row = []
            for f in FEATURE_NAMES:
                mean, std = feat[f]
                lo, hi    = _CLIP[f]
                val = _beta_sample(rng, mean, std, 1, lo, hi)[0]
                row.append(float(val))
            rows.append(row)
            labels.append(label)

    # Добираем оставшиеся строки случайными профилями
    remainder = n - len(rows)
    if remainder > 0:
        idxs = rng.integers(0, len(profiles), size=remainder)
        for idx in idxs:
            profile = profiles[idx]
            row = []
            for f in FEATURE_NAMES:
                mean, std = profile["features"][f]
                lo, hi    = _CLIP[f]
                val = _beta_sample(rng, mean, std, 1, lo, hi)[0]
                row.append(float(val))
            rows.append(row)
            labels.append(profile["label"])

    return np.array(rows), np.array(labels)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _beta_sample(
    rng: np.random.Generator,
    mean: float,
    std: float,
    n: int,
    clip_lo: float = 0.0,
    clip_hi: float = 1.0,
) -> np.ndarray:
    """
    Сэмплировать из Beta-распределения, параметризованного через mean/std.

    Почему Beta, а не Gaussian:
      Гауссово распределение на [0,1] после clip() накапливает вероятность
      у краёв (артефакт). Beta(a, b) — это «родное» распределение для [0,1],
      корректно описывающее вероятности и доли.
    """
    r   = clip_hi - clip_lo
    m   = (mean - clip_lo) / r          # масштабируем mean к [0, 1]
    s   = std / r                        # масштабируем std к [0, 1]
    # Ограничиваем дисперсию, чтобы параметры a, b были положительными
    max_s = np.sqrt(m * (1.0 - m)) * 0.95
    s     = min(s, max_s)
    k = m * (1.0 - m) / (s * s) - 1.0
    a = max(m * k, 0.1)
    b = max((1.0 - m) * k, 0.1)
    return np.clip(rng.beta(a, b, n) * r + clip_lo, clip_lo, clip_hi)


def _count_violations(row: dict[str, float]) -> int:
    """Подсчитать количество нарушенных порогов в одном наблюдении."""
    count = 0
    for feat, val in row.items():
        thr = THRESHOLDS[feat]
        d   = RISK_DIRECTION[feat]
        if d == +1 and val >= thr:
            count += 1
        elif d == -1 and val < thr:
            count += 1
    return count


def _split_counts(n: int, shares: dict[int, float]) -> dict[int, int]:
    """Разбить n строк по долям классов."""
    keys   = list(shares.keys())
    counts = {k: round(n * shares[k]) for k in keys[:-1]}
    counts[keys[-1]] = n - sum(counts.values())
    return counts


def _resample_to_shares(
    X: np.ndarray,
    y: np.ndarray,
    shares: dict[int, float],
    n_total: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Привести датасет к целевому распределению классов.

    Для классов с избытком — случайный downsample.
    Для классов с недостатком — случайный oversample (с повторением).
    Гарантирует итоговую сумму ровно n_total строк с пропорциями shares.
    """
    target = _split_counts(n_total, shares)
    parts_X, parts_y = [], []
    for class_id, want in target.items():
        idx = np.where(y == class_id)[0]
        chosen = rng.choice(idx, size=want, replace=(len(idx) < want))
        parts_X.append(X[chosen])
        parts_y.append(np.full(want, class_id))
    return np.vstack(parts_X), np.concatenate(parts_y)


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    df = generate_dataset()
    df.to_csv(OUTPUT_PATH, index=False)
    print(f"\nСохранено: {OUTPUT_PATH.resolve()}\n")
    print_statistics(df)
