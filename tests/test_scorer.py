"""
tests/test_scorer.py — тесты module2/scorer.py.
Проверяются все 5 критериев, все граничные значения и комбинации.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from module2.scorer import _compute_age_months, _verdict, score_contractor


# ---------------------------------------------------------------------------
# Вспомогательная фабрика
# ---------------------------------------------------------------------------

def _data(
    status: str = "active",
    age_months: int | None = 24,
    mass_address: bool = False,
    mass_director: bool = False,
    capital: float | None = 1_000_000.0,
) -> dict:
    """Базовый словарь с безопасными значениями; можно переопределить любое поле."""
    return dict(
        status=status,
        age_months=age_months,
        mass_address=mass_address,
        mass_director=mass_director,
        capital=capital,
    )


# ---------------------------------------------------------------------------
# Критерий 1: Статус организации
# ---------------------------------------------------------------------------

class TestStatusCriterion:

    def test_active_no_penalty(self):
        score, verdict, triggered = score_contractor(_data(status="active"))
        assert score == 0
        assert verdict == "safe"
        assert triggered == []

    def test_liquidated_adds_50(self):
        score, _, triggered = score_contractor(_data(status="liquidated"))
        assert score == 50
        assert "Организация ликвидирована" in triggered

    def test_liquidating_adds_40(self):
        score, _, triggered = score_contractor(_data(status="liquidating"))
        assert score == 40
        assert "в процессе ликвидации" in triggered[0]

    def test_unknown_status_no_penalty(self):
        score, _, triggered = score_contractor(_data(status="unknown"))
        assert score == 0
        assert triggered == []

    def test_empty_status_no_penalty(self):
        score, _, _ = score_contractor(_data(status=""))
        assert score == 0

    def test_status_case_insensitive(self):
        score, _, _ = score_contractor(_data(status="LIQUIDATED"))
        assert score == 50


# ---------------------------------------------------------------------------
# Критерий 2: Возраст организации (граничные значения)
# ---------------------------------------------------------------------------

class TestAgeCriterion:

    def test_age_0_months(self):
        score, _, triggered = score_contractor(_data(age_months=0))
        assert score == 30
        assert "менее 3 месяцев" in triggered[0]

    def test_age_1_month(self):
        score, _, _ = score_contractor(_data(age_months=1))
        assert score == 30

    def test_age_2_months(self):
        score, _, _ = score_contractor(_data(age_months=2))
        assert score == 30

    def test_age_3_months_boundary(self):
        """3 месяца — уже не < 3, попадает в диапазон < 6."""
        score, _, triggered = score_contractor(_data(age_months=3))
        assert score == 20
        assert "менее 6 месяцев" in triggered[0]

    def test_age_5_months(self):
        score, _, _ = score_contractor(_data(age_months=5))
        assert score == 20

    def test_age_6_months_boundary(self):
        """6 месяцев — уже не < 6, попадает в диапазон < 12."""
        score, _, triggered = score_contractor(_data(age_months=6))
        assert score == 10
        assert "менее года" in triggered[0]

    def test_age_11_months(self):
        score, _, _ = score_contractor(_data(age_months=11))
        assert score == 10

    def test_age_12_months_boundary(self):
        """12 месяцев — старше года, штраф не начисляется."""
        score, _, triggered = score_contractor(_data(age_months=12))
        assert score == 0
        assert triggered == []

    def test_age_36_months(self):
        score, _, triggered = score_contractor(_data(age_months=36))
        assert score == 0
        assert triggered == []

    def test_age_none_skips_criterion(self):
        """Нет данных о дате регистрации — критерий не применяется."""
        score, _, triggered = score_contractor(_data(age_months=None))
        assert score == 0
        assert triggered == []

    def test_reg_date_computed_correctly(self):
        """Если передана reg_date, возраст вычисляется автоматически."""
        today = date.today()
        reg = date(today.year - 2, today.month, today.day)
        d = dict(status="active", reg_date=reg,
                 mass_address=False, mass_director=False, capital=1_000_000.0)
        score, _, triggered = score_contractor(d)
        assert score == 0  # 24 мес — нет штрафа
        assert triggered == []

    def test_reg_date_recent_triggers_penalty(self):
        """Регистрация 1 месяц назад → +30."""
        reg = date.today() - timedelta(days=20)
        d = dict(status="active", reg_date=reg,
                 mass_address=False, mass_director=False, capital=1_000_000.0)
        score, _, _ = score_contractor(d)
        assert score == 30

    def test_age_months_takes_priority_over_reg_date(self):
        """age_months имеет приоритет перед reg_date."""
        d = dict(
            status="active",
            age_months=24,          # безопасный
            reg_date=date.today(),  # свежая дата — без age_months дала бы +30
            mass_address=False,
            mass_director=False,
            capital=1_000_000.0,
        )
        score, _, _ = score_contractor(d)
        assert score == 0


# ---------------------------------------------------------------------------
# Критерий 3: Массовый адрес
# ---------------------------------------------------------------------------

class TestMassAddressCriterion:

    def test_mass_address_true_adds_20(self):
        score, _, triggered = score_contractor(_data(mass_address=True))
        assert score == 20
        assert "Массовый адрес регистрации" in triggered

    def test_mass_address_false_no_penalty(self):
        score, _, triggered = score_contractor(_data(mass_address=False))
        assert score == 0
        assert triggered == []


# ---------------------------------------------------------------------------
# Критерий 4: Массовый руководитель
# ---------------------------------------------------------------------------

class TestMassDirectorCriterion:

    def test_mass_director_true_adds_20(self):
        score, _, triggered = score_contractor(_data(mass_director=True))
        assert score == 20
        assert "Массовый руководитель" in triggered

    def test_mass_director_false_no_penalty(self):
        score, _, triggered = score_contractor(_data(mass_director=False))
        assert score == 0
        assert triggered == []


# ---------------------------------------------------------------------------
# Критерий 5: Уставный капитал
# ---------------------------------------------------------------------------

class TestCapitalCriterion:

    def test_capital_10000_adds_10(self):
        score, _, triggered = score_contractor(_data(capital=10_000.0))
        assert score == 10
        assert "Минимальный уставный капитал" in triggered[0]

    def test_capital_below_10000_adds_10(self):
        score, _, _ = score_contractor(_data(capital=5_000.0))
        assert score == 10

    def test_capital_10001_no_penalty(self):
        score, _, triggered = score_contractor(_data(capital=10_001.0))
        assert score == 0
        assert triggered == []

    def test_capital_large_no_penalty(self):
        score, _, _ = score_contractor(_data(capital=10_000_000.0))
        assert score == 0

    def test_capital_none_skips_criterion(self):
        """Нет данных о капитале — критерий не применяется."""
        score, _, triggered = score_contractor(_data(capital=None))
        assert score == 0
        assert triggered == []


# ---------------------------------------------------------------------------
# Вердикт: граничные значения
# ---------------------------------------------------------------------------

class TestVerdict:

    def test_score_0_is_safe(self):
        assert _verdict(0) == "safe"

    def test_score_25_is_safe(self):
        assert _verdict(25) == "safe"

    def test_score_26_is_caution(self):
        assert _verdict(26) == "caution"

    def test_score_60_is_caution(self):
        assert _verdict(60) == "caution"

    def test_score_61_is_high_risk(self):
        assert _verdict(61) == "high_risk"

    def test_score_100_is_high_risk(self):
        assert _verdict(100) == "high_risk"


# ---------------------------------------------------------------------------
# Комбинированные сценарии
# ---------------------------------------------------------------------------

class TestCombinedScenarios:

    def test_all_clean_is_safe(self):
        """Полностью чистый контрагент → safe."""
        score, verdict, triggered = score_contractor(_data())
        assert score == 0
        assert verdict == "safe"
        assert triggered == []

    def test_young_plus_min_capital_is_caution(self):
        """Менее 12 мес + мин. капитал → 10+10=20 → safe (не caution!)."""
        score, verdict, _ = score_contractor(_data(age_months=11, capital=10_000.0))
        assert score == 20
        assert verdict == "safe"

    def test_young_3m_alone_is_caution(self):
        """Менее 3 мес → 30 → caution."""
        score, verdict, _ = score_contractor(_data(age_months=1))
        assert score == 30
        assert verdict == "caution"

    def test_both_mass_flags_is_caution(self):
        """Оба массовых признака → 20+20=40 → caution."""
        score, verdict, triggered = score_contractor(
            _data(mass_address=True, mass_director=True)
        )
        assert score == 40
        assert verdict == "caution"
        assert len(triggered) == 2

    def test_liquidated_alone_is_caution(self):
        """Ликвидирована → 50 → caution (не high_risk: порог 60)."""
        score, verdict, _ = score_contractor(_data(status="liquidated"))
        assert score == 50
        assert verdict == "caution"

    def test_liquidated_plus_mass_address_is_high_risk(self):
        """Ликвидирована + массовый адрес → 50+20=70 → high_risk."""
        score, verdict, triggered = score_contractor(
            _data(status="liquidated", mass_address=True)
        )
        assert score == 70
        assert verdict == "high_risk"
        assert len(triggered) == 2

    def test_liquidating_plus_young_6m_is_caution_boundary(self):
        """Ликвидируется + 3-5 мес → 40+20=60 → caution (граница)."""
        score, verdict, _ = score_contractor(
            _data(status="liquidating", age_months=4)
        )
        assert score == 60
        assert verdict == "caution"

    def test_liquidating_plus_young_3m_is_high_risk(self):
        """Ликвидируется + < 3 мес → 40+30=70 → high_risk."""
        score, verdict, _ = score_contractor(
            _data(status="liquidating", age_months=1)
        )
        assert score == 70
        assert verdict == "high_risk"

    def test_maximum_score_capped_at_100(self):
        """Все критерии → 50+30+20+20+10=130, но cap = 100."""
        score, verdict, triggered = score_contractor(
            _data(
                status="liquidated",
                age_months=0,
                mass_address=True,
                mass_director=True,
                capital=10_000.0,
            )
        )
        assert score == 100
        assert verdict == "high_risk"
        assert len(triggered) == 5

    def test_returns_correct_tuple_types(self):
        score, verdict, triggered = score_contractor(_data())
        assert isinstance(score, int)
        assert isinstance(verdict, str)
        assert isinstance(triggered, list)


# ---------------------------------------------------------------------------
# _compute_age_months — отдельные юнит-тесты
# ---------------------------------------------------------------------------

class TestComputeAgeMonths:

    def test_explicit_age_months(self):
        from module2.scorer import _compute_age_months
        assert _compute_age_months({"age_months": 5}) == 5

    def test_negative_age_clamped_to_zero(self):
        from module2.scorer import _compute_age_months
        assert _compute_age_months({"age_months": -1}) == 0

    def test_none_reg_date_returns_none(self):
        from module2.scorer import _compute_age_months
        assert _compute_age_months({"reg_date": None}) is None

    def test_no_date_fields_returns_none(self):
        from module2.scorer import _compute_age_months
        assert _compute_age_months({}) is None
