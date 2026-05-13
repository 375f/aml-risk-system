"""
module1/features.py — вычисление 7 признаков риска по критериям ЦБ РФ.

Источники нормативов:
  18-МР ЦБ РФ от 21.07.2017 — методрекомендации по налоговой нагрузке
  19-МР ЦБ РФ от 21.07.2017 — методрекомендации по наличным операциям
  115-ФЗ, ст. 6 — обязательный контроль операций от 600 000 руб.
"""

import re
from typing import Any

import pandas as pd

from config import (
    AVG_TX_CONTROL_LIMIT,
    CASH_RATIO_THRESHOLD,
    CONCENTRATION_THRESHOLD,
    FL_RATIO_THRESHOLD,
    OKVED_KEYWORDS,
    OKVED_MISMATCH_THRESHOLD,
    ROUND_AMOUNT_THRESHOLD,
    TAX_RATIO_THRESHOLD,
    TRANSIT_RATIO_THRESHOLD,
    TX_FREQUENCY_CAP,
    TX_FREQUENCY_THRESHOLD,
    WEEKEND_RATIO_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Ключевые слова для признаков 1, 2, 7
# ---------------------------------------------------------------------------

_CASH_KEYWORDS = [
    "снятие наличных", "выдача наличных", "банкомат",
    "касса", "наличные", "обналичивание", "выдача нал",
]

_TAX_KEYWORDS = [
    "ндс", "налог", "ифнс", "фнс", "пфр", "взносы",
    "фсс", "ффомс", "есн", "страховые взносы", "бюджет",
]

_FL_DESC_KEYWORDS = [
    "физическое лицо", "физлицу", "физлица", "физ лицо",
    "зарплата", "заработная плата", " зп ", "аванс",
    "дивиденд", "материальная помощь", "пособие",
    "стипендия", "самозанятый", "перевод физ", "выдача физ",
]

# Маркеры юрлиц — если присутствует, counterparty НЕ является физлицом
_LEGAL_MARKERS = frozenset([
    "ооо", "оао", "зао", "пао", "нко", "фгуп", "гуп",
    "муп", "кооператив", "казенное", "банк",
    "ифнс", "фнс", "пфр", "фсс", "мвд", "мчс",
])

# ФИО-паттерн: "Иванов И.И." | "Иванов Иван Иванович" | "Иванов И."
_FIO_RE = re.compile(
    r"^[А-ЯЁ][а-яё]+\s+"
    r"(?:[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+|[А-ЯЁ]\.[А-ЯЁ]\.|[А-ЯЁ]\.)$"
)


# _OKVED_KEYWORDS импортируется из config.OKVED_KEYWORDS (полный словарь с 4-значными кодами).


# ---------------------------------------------------------------------------
# Метаданные признаков (для UI, БД и объяснения)
# ---------------------------------------------------------------------------

FEATURE_META: list[dict[str, Any]] = [
    {
        "key": "cash_ratio",
        "label": "Доля наличных операций",
        "threshold": CASH_RATIO_THRESHOLD,
        "direction": "above",   # риск если value >= threshold
        "source": "19-МР ЦБ РФ от 21.07.2017",
        "unit": "%",
        "scale": 100,
        "risk_description": "Высокая доля снятий наличных (≥30%) — признак обналичивания.",
    },
    {
        "key": "tax_ratio",
        "label": "Налоговая нагрузка",
        "threshold": TAX_RATIO_THRESHOLD,
        "direction": "below",   # риск если value < threshold
        "source": "18-МР ЦБ РФ от 21.07.2017",
        "unit": "%",
        "scale": 100,
        "risk_description": "Налоговая нагрузка ниже 0.9% от оборота — признак ухода от налогов.",
    },
    {
        "key": "transit_ratio",
        "label": "Транзитный характер операций",
        "threshold": TRANSIT_RATIO_THRESHOLD,
        "direction": "above",
        "source": "19-МР ЦБ РФ от 21.07.2017",
        "unit": "%",
        "scale": 100,
        "risk_description": "Более 50% поступлений уходит в течение 3 дней — транзитная схема.",
    },
    {
        "key": "okved_mismatch",
        "label": "Несоответствие ОКВЭД",
        "threshold": OKVED_MISMATCH_THRESHOLD,
        "direction": "above",
        "source": "Экспертное правило",
        "unit": "%",
        "scale": 100,
        "risk_description": "Более 60% платежей не соответствуют заявленному виду деятельности.",
    },
    {
        "key": "avg_tx_norm",
        "label": "Средняя сумма транзакции",
        "threshold": 1.0,
        "direction": "below",   # риск если avg_tx < 600 000 руб.
        "source": "115-ФЗ, ст. 6",
        "unit": "",
        "scale": 1,
        "risk_description": "Средняя сумма поступлений ниже порога обязательного контроля (600 000 руб.).",
    },
    {
        "key": "counterparty_concentration",
        "label": "Концентрация контрагентов",
        "threshold": CONCENTRATION_THRESHOLD,
        "direction": "above",
        "source": "19-МР ЦБ РФ от 21.07.2017",
        "unit": "%",
        "scale": 100,
        "risk_description": "Высокая концентрация (>80%) — средства идут единственному контрагенту.",
    },
    {
        "key": "fl_ratio",
        "label": "Доля переводов физлицам",
        "threshold": FL_RATIO_THRESHOLD,
        "direction": "above",
        "source": "19-МР ЦБ РФ от 21.07.2017",
        "unit": "%",
        "scale": 100,
        "risk_description": "Более 30% расходов — переводы физлицам (признак обналичивания через людей).",
    },
    {
        "key": "weekend_ratio",
        "label": "Доля операций в выходные дни",
        "threshold": WEEKEND_RATIO_THRESHOLD,
        "direction": "above",
        "source": "Экспертное правило",
        "unit": "%",
        "scale": 100,
        "risk_description": "Более 30% операций в субботу/воскресенье — нетипично для легального малого бизнеса.",
    },
    {
        "key": "round_amount_ratio",
        "label": "Доля круглых сумм (структурирование)",
        "threshold": ROUND_AMOUNT_THRESHOLD,
        "direction": "above",
        "source": "FATF Typologies (структурирование)",
        "unit": "%",
        "scale": 100,
        "risk_description": "Более 60% платежей — суммы кратные 10 000 руб. Признак намеренного дробления (structuring).",
    },
    {
        "key": "tx_frequency_norm",
        "label": "Частота транзакций",
        "threshold": TX_FREQUENCY_THRESHOLD,
        "direction": "above",
        "source": "Экспертное правило",
        "unit": "",
        "scale": 1,
        "risk_description": "Высокая частота (более 15 транзакций в день) при малых суммах — признак дробления платежей.",
    },
]

#: Строго упорядоченный список ключей — тот же порядок, что feature_vector()
FEATURE_KEYS: list[str] = [m["key"] for m in FEATURE_META]


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def compute_features(df: pd.DataFrame, okved_codes: list[str] | None = None) -> dict:
    """
    Вычислить 10 признаков риска по выписке.

    Args:
        df:          DataFrame с колонками: date, amount, type, description,
                     counterparty, inn  (выход module1.parser.parse_statement)
        okved_codes: список кодов ОКВЭД (напр. ["46", "62"]). None → okved_mismatch = 0.0

    Returns:
        dict: 10 признаков, все float в диапазоне [0, 1].
    """
    df = df.copy()
    df["description"] = df["description"].fillna("").astype(str).str.lower()
    df["counterparty"] = df["counterparty"].fillna("").astype(str)
    df["inn"]          = df["inn"].fillna("").astype(str)
    df["date"]         = pd.to_datetime(df["date"], errors="coerce")

    debits      = df[df["type"] == "debit"].copy()
    total_debit = float(debits["amount"].sum())

    return {
        "cash_ratio":                 _cash_ratio(debits, total_debit),
        "tax_ratio":                  _tax_ratio(debits, total_debit),
        "transit_ratio":              _transit_ratio(df),
        "okved_mismatch":             check_okved_compliance(df, okved_codes or [])["okved_mismatch_ratio"],
        "avg_tx_norm":                _avg_tx_norm(df),
        "counterparty_concentration": _counterparty_concentration(debits),
        "fl_ratio":                   _fl_ratio(debits, total_debit),
        "weekend_ratio":              _weekend_ratio(df),
        "round_amount_ratio":         _round_amount_ratio(debits),
        "tx_frequency_norm":          _tx_frequency_norm(df),
    }


def describe_features(features: dict) -> list[dict]:
    """
    Обогатить словарь признаков метаданными — для UI и записи в risk_factors.

    Returns:
        Список dict с полями:
          key, label, value, threshold, is_triggered, direction,
          source, unit, display_value, risk_description
    """
    result = []
    for meta in FEATURE_META:
        key       = meta["key"]
        value     = float(features.get(key, 0.0))
        threshold = meta["threshold"]
        direction = meta["direction"]

        is_triggered = (
            value >= threshold if direction == "above"
            else value < threshold
        )

        display = f"{value * meta['scale']:.1f} {meta['unit']}".strip()

        result.append({
            **meta,
            "value":        value,
            "display_value": display,
            "is_triggered": is_triggered,
        })
    return result


def feature_vector(features: dict) -> list[float]:
    """Упорядоченный вектор признаков для RandomForestClassifier.predict()."""
    return [float(features[k]) for k in FEATURE_KEYS]


def check_okved_compliance(df: pd.DataFrame, okved_codes: list[str]) -> dict:
    """
    Проверить соответствие входящих (credit) транзакций разрешённым ОКВЭДам.

    Для каждой кредитовой транзакции проверяется, содержит ли назначение платежа
    хотя бы одно ключевое слово из _OKVED_KEYWORDS для переданных кодов.
    Транзакции без совпадений считаются «подозрительными».

    Args:
        df:          DataFrame (выход parse_statement). Колонка description
                     должна быть приведена к lower-case (это делает compute_features).
        okved_codes: Список кодов ОКВЭД (напр. ["46", "62", "47.11"]).
                     Используются первые 2 цифры кода.

    Returns:
        {
            "okved_mismatch_ratio":    float,   # доля несоответствующих credit-транзакций
            "suspicious_transactions": list,    # [{date, description, amount, counterparty}]
            "total_suspicious_amount": float,   # сумма подозрительных транзакций (руб.)
        }
    """
    if not okved_codes:
        return {
            "okved_mismatch_ratio":    0.0,
            "suspicious_transactions": [],
            "total_suspicious_amount": 0.0,
        }

    allowed_keywords: list[str] = []
    for code in okved_codes:
        code_clean = str(code).strip().replace(" ", "")
        if code_clean in OKVED_KEYWORDS:
            # Точное совпадение (напр. "62.01")
            allowed_keywords.extend(OKVED_KEYWORDS[code_clean])
        else:
            # Prefix-match: "62" → все ключи "62.*" и "62"
            prefix = code_clean[:2]
            for key, kws in OKVED_KEYWORDS.items():
                if key[:2] == prefix:
                    allowed_keywords.extend(kws)
    allowed_keywords = list(set(allowed_keywords))

    credits = df[df["type"] == "credit"].copy()
    if credits.empty:
        return {
            "okved_mismatch_ratio":    0.0,
            "suspicious_transactions": [],
            "total_suspicious_amount": 0.0,
        }

    if allowed_keywords:
        match_mask = credits["description"].apply(
            lambda desc: any(kw in desc for kw in allowed_keywords)
        )
    else:
        # Коды переданы, но ни один не распознан в словаре — все подозрительны
        match_mask = pd.Series([False] * len(credits), index=credits.index)

    suspicious = credits[~match_mask]
    mismatch_ratio = float(len(suspicious) / len(credits))

    suspicious_list = [
        {
            "date":         row["date"].strftime("%d.%m.%Y") if pd.notna(row["date"]) else "—",
            "description":  str(row["description"])[:120],
            "amount":       float(row["amount"]),
            "counterparty": str(row.get("counterparty", "")).strip(),
        }
        for _, row in suspicious.iterrows()
    ]

    return {
        "okved_mismatch_ratio":    mismatch_ratio,
        "suspicious_transactions": suspicious_list,
        "total_suspicious_amount": float(suspicious["amount"].sum()),
    }


# ---------------------------------------------------------------------------
# Вычисление отдельных признаков
# ---------------------------------------------------------------------------

def _cash_ratio(debits: pd.DataFrame, total_debit: float) -> float:
    """
    Признак 1 — доля наличных операций (19-МР ЦБ РФ).

    Порог риска: cash_ratio >= 0.30
    Ключевые слова: снятие наличных, выдача наличных, банкомат, касса.
    """
    if total_debit == 0:
        return 0.0
    pattern = "|".join(_CASH_KEYWORDS)
    mask = debits["description"].str.contains(pattern, case=False, na=False, regex=True)
    return float(debits.loc[mask, "amount"].sum() / total_debit)


def _tax_ratio(debits: pd.DataFrame, total_debit: float) -> float:
    """
    Признак 2 — налоговая нагрузка (18-МР ЦБ РФ).

    Порог риска: tax_ratio < 0.009 (менее 0.9% от дебетового оборота).
    Низкое значение означает, что компания почти не перечисляет налоги.
    """
    if total_debit == 0:
        return 0.0
    pattern = "|".join(_TAX_KEYWORDS)
    mask = debits["description"].str.contains(pattern, case=False, na=False, regex=True)
    return float(debits.loc[mask, "amount"].sum() / total_debit)


def _transit_ratio(df: pd.DataFrame) -> float:
    """
    Признак 3 — транзитный характер операций.

    Алгоритм (rolling window по дате):
      Для каждого дня с кредитовыми поступлениями вычисляем,
      какая доля поступлений была списана в течение следующих 3 дней.
      transit_ratio = Σ min(credit_day, debit_window) / total_credits

    Порог риска: transit_ratio > 0.50
    """
    df = df.copy()
    df["date_day"] = df["date"].dt.normalize()

    credits = df[df["type"] == "credit"]
    debits  = df[df["type"] == "debit"]

    total_credit = float(credits["amount"].sum())
    if total_credit == 0:
        return 0.0

    daily_credit = credits.groupby("date_day")["amount"].sum()
    daily_debit  = debits.groupby("date_day")["amount"].sum()

    transit_sum = 0.0
    for credit_date, credit_amount in daily_credit.items():
        window_end = credit_date + pd.Timedelta(days=3)
        debit_in_window = float(
            daily_debit.loc[
                (daily_debit.index >= credit_date) & (daily_debit.index <= window_end)
            ].sum()
        )
        # Транзит ограничен суммой поступления того дня
        transit_sum += min(float(credit_amount), debit_in_window)

    return min(transit_sum / total_credit, 1.0)


def _okved_mismatch(debits: pd.DataFrame, okved: str | None) -> float:
    """
    Признак 4 — несоответствие ОКВЭД назначениям платежей.

    Если ОКВЭД не передан или не распознан — возвращает 0.0.
    okved_mismatch = 1 - (платежи с совпадающим назначением / все дебетовые платежи)

    Порог риска: okved_mismatch > 0.60
    """
    if not okved or debits.empty:
        return 0.0

    code_clean = str(okved).strip().replace(" ", "")
    keywords: list[str] = []
    if code_clean in OKVED_KEYWORDS:
        keywords = OKVED_KEYWORDS[code_clean]
    else:
        prefix = code_clean[:2]
        for key, kws in OKVED_KEYWORDS.items():
            if key[:2] == prefix:
                keywords.extend(kws)
    if not keywords:
        return 0.0

    def _matches_okved(desc: str) -> bool:
        return any(kw in desc for kw in keywords)

    matched = int(debits["description"].apply(_matches_okved).sum())
    return float(1.0 - matched / len(debits))


def _avg_tx_norm(df: pd.DataFrame) -> float:
    """
    Признак 5 — средняя сумма входящей транзакции, нормализованная.

    Нормировано к порогу обязательного контроля (600 000 руб., 115-ФЗ ст. 6).
    avg_tx_norm = min(avg_credit / 600 000, 1.0)

    Значение < 1.0 означает, что средняя транзакция ниже порога,
    что может указывать на дробление операций (structuring).
    """
    credits = df[df["type"] == "credit"]
    if credits.empty:
        return 0.0
    avg_tx = float(credits["amount"].mean())
    return min(avg_tx / AVG_TX_CONTROL_LIMIT, 1.0)


def _counterparty_concentration(debits: pd.DataFrame) -> float:
    """
    Признак 6 — концентрация контрагентов по дебетовым операциям.

    concentration = 1 - (уникальные контрагенты / кол-во транзакций)
    0.0 — каждая транзакция с уникальным контрагентом (норма)
    → 1.0 — все деньги уходят одному контрагенту (риск транзита)

    Порог риска: concentration > 0.80
    """
    debits_with_cp = debits[debits["counterparty"].str.strip() != ""]
    if debits_with_cp.empty:
        return 0.0
    unique_cp = int(debits_with_cp["counterparty"].nunique())
    total_tx  = len(debits_with_cp)
    return float(max(0.0, 1.0 - unique_cp / total_tx))


def _fl_ratio(debits: pd.DataFrame, total_debit: float) -> float:
    """
    Признак 7 — доля переводов физическим лицам (19-МР ЦБ РФ).

    Физлицо обнаруживается по трём критериям:
      1. ИНН из 12 цифр (ИП или физическое лицо без статуса ИП)
      2. Ключевые слова в назначении платежа (зарплата, дивиденды…)
      3. ФИО-паттерн в поле контрагента при отсутствии маркеров юрлица

    Порог риска: fl_ratio > 0.30
    """
    if total_debit == 0 or debits.empty:
        return 0.0

    fl_mask = debits.apply(_is_individual, axis=1)
    fl_amount = float(debits.loc[fl_mask, "amount"].sum())
    return fl_amount / total_debit


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _weekend_ratio(df: pd.DataFrame) -> float:
    """
    Признак 8 — доля операций в выходные дни (суббота и воскресенье).

    Высокая активность в выходные нетипична для легального малого бизнеса:
    большинство расчётов между юрлицами проводятся в рабочие дни.

    Порог риска: weekend_ratio > 0.30
    """
    valid = df.dropna(subset=["date"])
    if valid.empty:
        return 0.0
    weekend_count = int((valid["date"].dt.dayofweek >= 5).sum())
    return float(weekend_count / len(valid))


def _round_amount_ratio(debits: pd.DataFrame) -> float:
    """
    Признак 9 — доля «круглых» сумм, кратных 10 000 руб.

    Намеренное использование круглых сумм — типичный признак структурирования:
    дробления платежей для обхода порогов обязательного контроля (115-ФЗ, ст. 6).

    Порог риска: round_amount_ratio > 0.60
    """
    if debits.empty:
        return 0.0
    round_mask = debits["amount"].apply(
        lambda x: x > 0 and round(x) % 10_000 == 0
    )
    return float(round_mask.sum() / len(debits))


def _tx_frequency_norm(df: pd.DataFrame) -> float:
    """
    Признак 10 — нормализованная частота транзакций (транзакций в день).

    Вычисляется как tx_per_day / TX_FREQUENCY_CAP (30 транзакций/день = 1.0).
    Высокая частота при малых суммах — признак структурирования: сумма дробится
    на множество мелких переводов, каждый из которых ниже порога контроля.

    Порог риска: tx_frequency_norm > 0.50 (более 15 транзакций в день)
    """
    valid = df.dropna(subset=["date"])
    if valid.empty or len(valid) < 2:
        return 0.0
    date_range = (valid["date"].max() - valid["date"].min()).days
    if date_range == 0:
        return 0.0
    tx_per_day = len(valid) / date_range
    return min(tx_per_day / TX_FREQUENCY_CAP, 1.0)


def _is_individual(row: pd.Series) -> bool:
    """True если строка выписки — перевод физическому лицу."""
    desc = row["description"]   # уже lower (см. compute_features)
    cp   = str(row["counterparty"]).strip()
    inn  = str(row["inn"]).strip()

    # Критерий 1: 12-значный ИНН — физлицо или ИП
    if len(inn) == 12 and inn.isdigit():
        return True

    # Критерий 2: ключевые слова в назначении платежа
    if any(kw in desc for kw in _FL_DESC_KEYWORDS):
        return True

    # Критерий 3: ФИО в поле контрагента, нет маркеров юрлица
    if cp:
        cp_lower = cp.lower()
        if not any(m in cp_lower for m in _LEGAL_MARKERS):
            if _FIO_RE.match(cp):
                return True

    return False
