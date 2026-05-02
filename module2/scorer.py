"""
module2/scorer.py — rule-based скоринг контрагента по критериям 115-ФЗ.

Входной словарь data может содержать:
    status        (str)         — 'active' | 'liquidated' | 'liquidating' | ...
    reg_date      (date | None) — дата регистрации (используется если нет age_months)
    age_months    (int | None)  — возраст в месяцах (приоритет над reg_date)
    mass_address  (bool)        — признак массового адреса
    mass_director (bool)        — признак массового руководителя
    capital       (float | None)— уставный капитал, руб. (None = данные отсутствуют)
"""

from __future__ import annotations

from datetime import date

from config import (
    SCORE_LIQUIDATED,
    SCORE_LIQUIDATING,
    SCORE_MASS_ADDRESS,
    SCORE_MASS_DIRECTOR,
    SCORE_MIN_CAPITAL,
    SCORE_YOUNG_12M,
    SCORE_YOUNG_3M,
    SCORE_YOUNG_6M,
    VERDICT_CAUTION_MAX,
    VERDICT_SAFE_MAX,
)


def score_contractor(data: dict) -> tuple[int, str, list[str]]:
    """
    Вычислить балл риска контрагента по 5 критериям.

    Args:
        data: словарь с полями контрагента (из get_entity_by_inn() или тест-данные).

    Returns:
        Кортеж (score, verdict, triggered):
            score     — целое число 0–100
            verdict   — 'safe' | 'caution' | 'high_risk'
            triggered — список строк с описанием сработавших критериев
    """
    score = 0
    triggered: list[str] = []

    # Критерий 1: статус организации
    status = (data.get("status") or "").lower()
    if status == "liquidated":
        score += SCORE_LIQUIDATED
        triggered.append("Организация ликвидирована")
    elif status == "liquidating":
        score += SCORE_LIQUIDATING
        triggered.append("Организация в процессе ликвидации")

    # Критерий 2: срок с момента регистрации
    age = _compute_age_months(data)
    if age is not None:
        if age < 3:
            score += SCORE_YOUNG_3M
            triggered.append("Зарегистрирована менее 3 месяцев назад")
        elif age < 6:
            score += SCORE_YOUNG_6M
            triggered.append("Зарегистрирована менее 6 месяцев назад")
        elif age < 12:
            score += SCORE_YOUNG_12M
            triggered.append("Зарегистрирована менее года назад")

    # Критерий 3: массовый адрес регистрации
    if data.get("mass_address"):
        score += SCORE_MASS_ADDRESS
        triggered.append("Массовый адрес регистрации")

    # Критерий 4: массовый руководитель
    if data.get("mass_director"):
        score += SCORE_MASS_DIRECTOR
        triggered.append("Массовый руководитель")

    # Критерий 5: уставный капитал
    capital = data.get("capital")
    if capital is not None and float(capital) <= 10_000:
        score += SCORE_MIN_CAPITAL
        triggered.append("Минимальный уставный капитал (10 000 руб.)")

    score = min(score, 100)  # DB constraint: risk_score BETWEEN 0 AND 100
    return score, _verdict(score), triggered


# ---------------------------------------------------------------------------
# Внутренние функции
# ---------------------------------------------------------------------------

def _compute_age_months(data: dict) -> int | None:
    """Возраст организации в месяцах: из age_months (приоритет) или из reg_date."""
    if "age_months" in data and data["age_months"] is not None:
        return max(0, int(data["age_months"]))
    reg_date = data.get("reg_date")
    if reg_date is None:
        return None
    today = date.today()
    months = (today.year - reg_date.year) * 12 + (today.month - reg_date.month)
    return max(0, months)


def _verdict(score: int) -> str:
    if score <= VERDICT_SAFE_MAX:
        return "safe"
    if score <= VERDICT_CAUTION_MAX:
        return "caution"
    return "high_risk"
