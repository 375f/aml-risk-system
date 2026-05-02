"""
tests/test_features.py — тесты модуля module1.features.

Покрываемые сценарии:
  - Каждый из 7 признаков: нормальное значение, граничное, выше/ниже порога
  - Пустой DataFrame → все признаки = 0.0
  - feature_vector(): длина, упорядоченность, типы
  - describe_features(): структура, is_triggered на граничных значениях
  - Сквозной тест на фикстуре sample_df (20 строк)
"""
import pytest
import pandas as pd

from module1.features import (
    FEATURE_KEYS,
    FEATURE_META,
    compute_features,
    describe_features,
    feature_vector,
)
from tests.conftest import make_df

# Импортируем пороги напрямую из config для независимости от magic numbers
from config import (
    AVG_TX_CONTROL_LIMIT,
    CASH_RATIO_THRESHOLD,
    CONCENTRATION_THRESHOLD,
    FL_RATIO_THRESHOLD,
    OKVED_MISMATCH_THRESHOLD,
    TAX_RATIO_THRESHOLD,
    TRANSIT_RATIO_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Признак 1: cash_ratio — доля наличных (19-МР, порог 0.30)
# ---------------------------------------------------------------------------

class TestCashRatio:

    def test_below_threshold(self, sample_df):
        """sample_df: наличные = 30k / 200k = 0.15 < 0.30."""
        f = compute_features(sample_df)
        assert f["cash_ratio"] == pytest.approx(0.15, abs=0.01)

    def test_at_threshold(self):
        """Ровно 30% наличных — is_triggered должен быть True (direction=above)."""
        df = make_df([
            ("2024-03-01", 30_000, "debit",  "Снятие наличных", "Банкомат", ""),
            ("2024-03-02", 70_000, "debit",  "Оплата товаров",  "ООО А",    ""),
            ("2024-03-03", 200_000, "credit", "Поступление",    "Клиент",   ""),
        ])
        f = compute_features(df)
        assert f["cash_ratio"] == pytest.approx(CASH_RATIO_THRESHOLD, abs=0.001)
        described = {d["key"]: d for d in describe_features(f)}
        assert described["cash_ratio"]["is_triggered"] is True

    def test_above_threshold(self):
        """50% наличных — явный риск."""
        df = make_df([
            ("2024-03-01", 50_000, "debit",  "Снятие наличных", "Банкомат", ""),
            ("2024-03-02", 50_000, "debit",  "Оплата товаров",  "ООО А",    ""),
            ("2024-03-03", 200_000, "credit", "Поступление",    "Клиент",   ""),
        ])
        f = compute_features(df)
        assert f["cash_ratio"] == pytest.approx(0.50, abs=0.001)
        assert f["cash_ratio"] >= CASH_RATIO_THRESHOLD

    def test_below_threshold_not_triggered(self):
        """10% наличных — не риск."""
        df = make_df([
            ("2024-03-01", 10_000, "debit",  "Снятие наличных", "Банкомат", ""),
            ("2024-03-02", 90_000, "debit",  "Оплата услуг",    "ООО А",    ""),
            ("2024-03-03", 200_000, "credit", "Поступление",    "Клиент",   ""),
        ])
        f = compute_features(df)
        described = {d["key"]: d for d in describe_features(f)}
        assert described["cash_ratio"]["is_triggered"] is False

    def test_all_cash_withdrawals(self):
        """100% наличных → cash_ratio = 1.0."""
        df = make_df([
            ("2024-03-01", 100_000, "debit",  "Снятие наличных",          "Банкомат", ""),
            ("2024-03-02", 200_000, "credit", "Поступление от клиента",   "ООО А",    ""),
        ])
        f = compute_features(df)
        assert f["cash_ratio"] == pytest.approx(1.0)

    def test_no_debit_returns_zero(self):
        """Только кредиты → cash_ratio = 0.0."""
        df = make_df([
            ("2024-03-01", 100_000, "credit", "Поступление", "ООО А", ""),
        ])
        f = compute_features(df)
        assert f["cash_ratio"] == 0.0

    def test_all_keywords_detected(self):
        """Все ключевые слова (банкомат, касса, выдача наличных, наличные) распознаются."""
        df = make_df([
            ("2024-03-01", 10_000, "debit", "Снятие через банкомат",      "", ""),
            ("2024-03-02", 10_000, "debit", "Выдача наличных в кассе",    "", ""),
            ("2024-03-03", 10_000, "debit", "Выдача наличных из кассы",   "", ""),
            ("2024-03-04", 10_000, "debit", "Прочие наличные расходы",    "", ""),
            ("2024-03-05", 200_000, "credit", "Поступление",              "", ""),
        ])
        f = compute_features(df)
        assert f["cash_ratio"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Признак 2: tax_ratio — налоговая нагрузка (18-МР, порог 0.009)
# ---------------------------------------------------------------------------

class TestTaxRatio:

    def test_healthy_above_threshold(self, sample_df):
        """sample_df: налоги = 20k / 200k = 0.10 >> 0.009."""
        f = compute_features(sample_df)
        assert f["tax_ratio"] == pytest.approx(0.10, abs=0.001)

    def test_at_threshold(self):
        """Ровно 0.9% — is_triggered = False (риск только при СТРОГОМ <)."""
        df = make_df([
            ("2024-03-01",   9_000, "debit", "Налог НДС",   "ИФНС",  ""),
            ("2024-03-02", 991_000, "debit", "Оплата",      "ООО А", ""),
            ("2024-03-03", 2_000_000, "credit", "Поступление", "Клиент", ""),
        ])
        f = compute_features(df)
        assert f["tax_ratio"] == pytest.approx(TAX_RATIO_THRESHOLD, abs=0.0001)
        described = {d["key"]: d for d in describe_features(f)}
        # direction="below": triggered если value < threshold; 0.009 < 0.009 = False
        assert described["tax_ratio"]["is_triggered"] is False

    def test_risky_below_threshold(self):
        """0% налогов — явный риск по 18-МР."""
        df = make_df([
            ("2024-03-01", 100_000, "debit",  "Оплата товаров",  "ООО А",  ""),
            ("2024-03-02", 200_000, "credit", "Поступление",     "Клиент", ""),
        ])
        f = compute_features(df)
        assert f["tax_ratio"] == 0.0
        described = {d["key"]: d for d in describe_features(f)}
        assert described["tax_ratio"]["is_triggered"] is True

    def test_tax_keywords_all_recognised(self):
        """ндс, ифнс, пфр, взносы, фсс — все ключевые слова работают."""
        df = make_df([
            ("2024-03-01", 5_000, "debit", "Налог НДС",               "ИФНС",  ""),
            ("2024-03-02", 5_000, "debit", "Взносы в ПФР",            "ПФР",   ""),
            ("2024-03-03", 5_000, "debit", "Страховые взносы ФСС",    "ФСС",   ""),
            ("2024-03-04", 5_000, "debit", "ИФНС налог на прибыль",   "ИФНС",  ""),
            ("2024-03-05", 80_000, "debit", "Оплата поставщику",      "ООО А", ""),
            ("2024-03-06", 300_000, "credit", "Поступление",          "Клиент",""),
        ])
        f = compute_features(df)
        # 20k налогов / 100k дебета = 0.20 >> порога
        assert f["tax_ratio"] == pytest.approx(0.20, abs=0.01)


# ---------------------------------------------------------------------------
# Признак 3: transit_ratio — транзитный характер (порог 0.50)
# ---------------------------------------------------------------------------

class TestTransitRatio:

    def test_low_transit(self, sample_df):
        """sample_df: деньги приходят, но не уходят за 3 дня (~30%)."""
        f = compute_features(sample_df)
        assert f["transit_ratio"] < TRANSIT_RATIO_THRESHOLD

    def test_at_threshold(self):
        """50% поступлений уходит за 3 дня → ровно на пороге."""
        df = make_df([
            ("2024-03-01", 100_000, "credit", "Поступление",  "ООО А", ""),
            ("2024-03-02",  50_000, "debit",  "Перевод",      "ООО Б", ""),
        ])
        f = compute_features(df)
        assert f["transit_ratio"] == pytest.approx(0.50, abs=0.001)

    def test_above_threshold(self):
        """80% поступлений уходит за 3 дня — явный транзит."""
        df = make_df([
            ("2024-03-01", 100_000, "credit", "Поступление", "ООО А", ""),
            ("2024-03-02",  80_000, "debit",  "Перевод",     "ООО Б", ""),
        ])
        f = compute_features(df)
        assert f["transit_ratio"] == pytest.approx(0.80, abs=0.001)
        assert f["transit_ratio"] >= TRANSIT_RATIO_THRESHOLD

    def test_no_credits_returns_zero(self):
        """Только расходы — transit_ratio = 0.0."""
        df = make_df([("2024-03-01", 50_000, "debit", "Расход", "ООО А", "")])
        f = compute_features(df)
        assert f["transit_ratio"] == 0.0

    def test_debit_outside_window_not_counted(self):
        """Списание через 5 дней (вне окна 3 дня) не учитывается как транзит."""
        df = make_df([
            ("2024-03-01", 100_000, "credit", "Поступление", "ООО А", ""),
            ("2024-03-06",  80_000, "debit",  "Перевод",     "ООО Б", ""),
        ])
        f = compute_features(df)
        # Расход на 5-й день, окно закрылось 4-го — транзит = 0
        assert f["transit_ratio"] == pytest.approx(0.0, abs=0.001)

    def test_capped_at_one(self):
        """transit_ratio не может превышать 1.0."""
        df = make_df([
            ("2024-03-01", 100_000, "credit", "Поступление", "ООО А", ""),
            ("2024-03-01", 200_000, "debit",  "Перевод",     "ООО Б", ""),
        ])
        f = compute_features(df)
        assert f["transit_ratio"] <= 1.0


# ---------------------------------------------------------------------------
# Признак 4: okved_mismatch — несоответствие ОКВЭД (порог 0.60)
# ---------------------------------------------------------------------------

class TestOkvedMismatch:

    def test_no_okved_returns_zero(self, sample_df):
        """Без ОКВЭД mismatch = 0.0."""
        f = compute_features(sample_df, okved=None)
        assert f["okved_mismatch"] == 0.0

    def test_empty_okved_returns_zero(self):
        df = make_df([("2024-03-01", 10_000, "debit", "Оплата", "ООО А", "")])
        f = compute_features(df, okved="")
        assert f["okved_mismatch"] == 0.0

    def test_matching_okved_low_mismatch(self):
        """Строительные платежи при ОКВЭД 41 → низкий mismatch.

        Описания подобраны так, чтобы явно содержать ключи словаря OKVED "41":
        «строительство», «монтаж», «отделка», «кровля», «стройматериал».
        """
        df = make_df([
            ("2024-03-01", 20_000, "debit", "строительство фундамента и кровля",  "ООО Строй", ""),
            ("2024-03-02", 20_000, "debit", "монтаж и отделка фасада",            "ООО Монтаж",""),
            ("2024-03-03", 20_000, "debit", "стройматериалы для объекта",         "ООО Мат",   ""),
            ("2024-03-04", 100_000, "credit", "Поступление",                      "Клиент",    ""),
        ])
        f = compute_features(df, okved="41")
        # Все 3 дебета содержат ключи ОКВЭД 41 → mismatch = 0.0 < 0.60
        assert f["okved_mismatch"] < OKVED_MISMATCH_THRESHOLD

    def test_mismatching_okved_high_mismatch(self):
        """Строительные платежи при ОКВЭД 47 (розничная торговля) → высокий mismatch."""
        df = make_df([
            ("2024-03-01", 20_000, "debit", "Строительные материалы", "ООО Строй", ""),
            ("2024-03-02", 20_000, "debit", "Монтаж и отделка",       "ООО Монтаж",""),
            ("2024-03-03", 20_000, "debit", "Ремонт кровли",          "ООО Кровля",""),
            ("2024-03-04", 100_000, "credit", "Поступление",          "Клиент",    ""),
        ])
        f = compute_features(df, okved="47")
        assert f["okved_mismatch"] >= OKVED_MISMATCH_THRESHOLD

    def test_at_threshold_exactly(self):
        """5 дебетов, 2 совпадают с ОКВЭД 46 → mismatch = 1 - 2/5 = 0.60.

        Ключи ОКВЭД 46: «торговля», «оптовая», «товар», «поставк», «продукт», «оборудован».
        Строки 1-2 содержат эти ключи, строки 3-5 — нет.
        """
        df = make_df([
            ("2024-03-01", 10_000, "debit", "торговля продуктами питания",  "ООО А", ""),  # MATCH: торговля, продукт
            ("2024-03-02", 10_000, "debit", "оптовая поставка товаров",     "ООО Б", ""),  # MATCH: оптовая, поставк, товар
            ("2024-03-03", 10_000, "debit", "транспортные расходы",         "ООО В", ""),  # NO MATCH
            ("2024-03-04", 10_000, "debit", "зарплата сотрудникам",         "ООО Г", ""),  # NO MATCH
            ("2024-03-05", 10_000, "debit", "аренда склада",                "ООО Д", ""),  # NO MATCH
            ("2024-03-06", 100_000, "credit", "Поступление",                "Клиент",""),
        ])
        f = compute_features(df, okved="46")
        # matched=2, total=5 → mismatch = 1 - 2/5 = 0.60
        assert f["okved_mismatch"] == pytest.approx(0.60, abs=0.01)

    def test_unknown_okved_prefix_returns_zero(self):
        """Неизвестный ОКВЭД → 0.0 (нет словаря для сравнения)."""
        df = make_df([("2024-03-01", 10_000, "debit", "Оплата", "ООО А", "")])
        f = compute_features(df, okved="99")
        assert f["okved_mismatch"] == 0.0


# ---------------------------------------------------------------------------
# Признак 5: avg_tx_norm — средняя сумма транзакции нормализованная (порог 1.0)
# ---------------------------------------------------------------------------

class TestAvgTxNorm:

    def test_below_threshold(self, sample_df):
        """sample_df: avg_credit = 330k/7 ≈ 47k → avg_tx_norm ≈ 0.079 < 1.0."""
        f = compute_features(sample_df)
        assert f["avg_tx_norm"] < 1.0
        assert f["avg_tx_norm"] > 0.0

    def test_at_threshold_600k(self):
        """Средняя транзакция = 600 000 → avg_tx_norm = 1.0."""
        df = make_df([
            ("2024-03-01", 600_000, "credit", "Поступление", "ООО А", ""),
            ("2024-03-02", 500_000, "debit",  "Расход",      "ООО Б", ""),
        ])
        f = compute_features(df)
        assert f["avg_tx_norm"] == pytest.approx(1.0, abs=0.001)
        described = {d["key"]: d for d in describe_features(f)}
        # direction="below": triggered если value < threshold (1.0 < 1.0 = False)
        assert described["avg_tx_norm"]["is_triggered"] is False

    def test_above_threshold_capped_at_one(self):
        """Средняя > 600k → результат зажат в 1.0."""
        df = make_df([
            ("2024-03-01", 1_200_000, "credit", "Крупный платёж", "ООО А", ""),
            ("2024-03-02", 1_000_000, "debit",  "Расход",         "ООО Б", ""),
        ])
        f = compute_features(df)
        assert f["avg_tx_norm"] == pytest.approx(1.0)

    def test_small_transactions_triggered(self):
        """Средняя транзакция 100k < 600k → риск (is_triggered = True)."""
        df = make_df([
            ("2024-03-01", 100_000, "credit", "Поступление А", "ООО А", ""),
            ("2024-03-02", 100_000, "credit", "Поступление Б", "ООО Б", ""),
            ("2024-03-03", 150_000, "debit",  "Расход",        "ООО В", ""),
        ])
        f = compute_features(df)
        described = {d["key"]: d for d in describe_features(f)}
        assert described["avg_tx_norm"]["is_triggered"] is True

    def test_no_credits_returns_zero(self):
        """Только дебеты → avg_tx_norm = 0.0."""
        df = make_df([("2024-03-01", 50_000, "debit", "Расход", "ООО А", "")])
        f = compute_features(df)
        assert f["avg_tx_norm"] == 0.0

    def test_normalization_formula(self):
        """Прямая проверка формулы: avg / 600_000."""
        df = make_df([
            ("2024-03-01", 300_000, "credit", "А", "ООО А", ""),
            ("2024-03-02", 300_000, "credit", "Б", "ООО Б", ""),
            ("2024-03-03", 500_000, "debit",  "Р", "ООО В", ""),
        ])
        f = compute_features(df)
        expected = 300_000 / AVG_TX_CONTROL_LIMIT
        assert f["avg_tx_norm"] == pytest.approx(expected, abs=0.001)


# ---------------------------------------------------------------------------
# Признак 6: counterparty_concentration — концентрация контрагентов (порог 0.80)
# ---------------------------------------------------------------------------

class TestCounterpartyConcentration:

    def test_all_unique_zero(self, sample_df):
        """sample_df: у каждого дебета свой контрагент → concentration = 0.0."""
        f = compute_features(sample_df)
        assert f["counterparty_concentration"] == pytest.approx(0.0, abs=0.001)

    def test_at_threshold(self):
        """5 дебетов, 1 уникальный контрагент → 1 - 1/5 = 0.80."""
        df = make_df([
            ("2024-03-01", 20_000, "debit",  "Перевод", "ООО Единый", ""),
            ("2024-03-02", 20_000, "debit",  "Перевод", "ООО Единый", ""),
            ("2024-03-03", 20_000, "debit",  "Перевод", "ООО Единый", ""),
            ("2024-03-04", 20_000, "debit",  "Перевод", "ООО Единый", ""),
            ("2024-03-05", 20_000, "debit",  "Перевод", "ООО Единый", ""),
            ("2024-03-06", 200_000, "credit", "Приход", "Клиент",     ""),
        ])
        f = compute_features(df)
        assert f["counterparty_concentration"] == pytest.approx(CONCENTRATION_THRESHOLD, abs=0.001)
        described = {d["key"]: d for d in describe_features(f)}
        assert described["counterparty_concentration"]["is_triggered"] is True

    def test_above_threshold(self):
        """10 дебетов к 1 контрагенту → 1 - 1/10 = 0.90 > 0.80."""
        rows = [("2024-03-01", 10_000, "debit", "Перевод", "ООО Один", "") for _ in range(10)]
        rows.append(("2024-03-15", 200_000, "credit", "Приход", "Клиент", ""))
        df = make_df(rows)
        f = compute_features(df)
        assert f["counterparty_concentration"] == pytest.approx(0.90, abs=0.001)

    def test_all_different_zero(self):
        """Каждая транзакция с новым контрагентом → 0.0."""
        df = make_df([
            ("2024-03-01", 10_000, "debit", "Оплата А", "ООО А", ""),
            ("2024-03-02", 10_000, "debit", "Оплата Б", "ООО Б", ""),
            ("2024-03-03", 10_000, "debit", "Оплата В", "ООО В", ""),
        ])
        f = compute_features(df)
        assert f["counterparty_concentration"] == 0.0

    def test_empty_counterparty_ignored(self):
        """Строки с пустым контрагентом не участвуют в расчёте."""
        df = make_df([
            ("2024-03-01", 10_000, "debit", "Оплата", "ООО А", ""),
            ("2024-03-02", 10_000, "debit", "Оплата", "",       ""),  # пропущен
            ("2024-03-03", 10_000, "debit", "Оплата", "",       ""),  # пропущен
        ])
        f = compute_features(df)
        # Только 1 строка с контрагентом "ООО А" → concentration = 1 - 1/1 = 0.0
        assert f["counterparty_concentration"] == 0.0


# ---------------------------------------------------------------------------
# Признак 7: fl_ratio — доля переводов физлицам (19-МР, порог 0.30)
# ---------------------------------------------------------------------------

class TestFlRatio:

    def test_above_threshold(self, sample_df):
        """sample_df: зарплата + дивиденды + ИП = 65k / 200k = 0.325 > 0.30."""
        f = compute_features(sample_df)
        assert f["fl_ratio"] == pytest.approx(0.325, abs=0.01)
        assert f["fl_ratio"] >= FL_RATIO_THRESHOLD

    def test_at_threshold(self):
        """Ровно 30% переводов физлицам."""
        df = make_df([
            ("2024-03-01", 30_000, "debit",  "Зарплата за март",  "Иванов И.И.", ""),
            ("2024-03-02", 70_000, "debit",  "Оплата товаров",    "ООО А",       ""),
            ("2024-03-03", 200_000, "credit", "Поступление",      "Клиент",      ""),
        ])
        f = compute_features(df)
        assert f["fl_ratio"] == pytest.approx(FL_RATIO_THRESHOLD, abs=0.001)

    def test_detected_by_12_digit_inn(self):
        """12-значный ИНН (ИП) → физлицо."""
        df = make_df([
            ("2024-03-01", 50_000, "debit", "Аренда офиса", "ИП Смирнов", "501234567890"),
            ("2024-03-02", 50_000, "debit", "Оплата ООО",   "ООО Альфа",  "7701234560"),
            ("2024-03-03", 200_000, "credit", "Приход",      "Клиент",    ""),
        ])
        f = compute_features(df)
        # 50k/100k = 0.50 > 0.30
        assert f["fl_ratio"] == pytest.approx(0.50, abs=0.001)

    def test_detected_by_description_keyword(self):
        """Ключевые слова: зарплата, дивиденды, материальная помощь."""
        df = make_df([
            ("2024-03-01", 30_000, "debit", "Дивиденды учредителю", "Петров Иван Петрович", ""),
            ("2024-03-02", 20_000, "debit", "Материальная помощь",  "Сидорова А.А.",        ""),
            ("2024-03-03", 50_000, "debit", "Оплата поставщику",    "ООО Б",                ""),
            ("2024-03-04", 200_000, "credit", "Поступление",        "Клиент",               ""),
        ])
        f = compute_features(df)
        # 50k FL из 100k дебета = 0.50
        assert f["fl_ratio"] == pytest.approx(0.50, abs=0.001)

    def test_detected_by_fio_pattern(self):
        """ФИО-паттерн в поле контрагента при отсутствии маркеров юрлица."""
        df = make_df([
            ("2024-03-01", 40_000, "debit", "Перевод сотруднику",  "Кузнецов А.Б.", ""),
            ("2024-03-02", 60_000, "debit", "Оплата поставщику",   "ООО Ромашка",   ""),
            ("2024-03-03", 200_000, "credit", "Поступление",       "Клиент",        ""),
        ])
        f = compute_features(df)
        assert f["fl_ratio"] == pytest.approx(0.40, abs=0.001)

    def test_no_fl_returns_zero(self):
        """Все платежи юрлицам → fl_ratio = 0.0."""
        df = make_df([
            ("2024-03-01", 50_000, "debit",  "Оплата",    "ООО Альфа",  "7701234560"),
            ("2024-03-02", 50_000, "debit",  "Оплата",    "ООО Бета",   "7701234561"),
            ("2024-03-03", 200_000, "credit", "Приход",   "Клиент",     ""),
        ])
        f = compute_features(df)
        assert f["fl_ratio"] == 0.0

    def test_legal_entity_marker_excludes_fio(self):
        """Имя со словом «банк» — юрлицо, не физлицо."""
        df = make_df([
            ("2024-03-01", 50_000, "debit", "Погашение кредита", "Банк ВТБ", ""),
            ("2024-03-02", 50_000, "debit", "Оплата",            "ООО Ромашка", ""),
            ("2024-03-03", 100_000, "credit", "Поступление",     "Клиент", ""),
        ])
        f = compute_features(df)
        assert f["fl_ratio"] == 0.0


# ---------------------------------------------------------------------------
# describe_features() — структура и метаданные
# ---------------------------------------------------------------------------

class TestDescribeFeatures:

    def test_returns_seven_items(self, sample_df):
        f = compute_features(sample_df)
        d = describe_features(f)
        assert len(d) == 7

    def test_all_keys_present_in_each_item(self, sample_df):
        f = compute_features(sample_df)
        required = {"key", "label", "value", "threshold", "is_triggered",
                    "direction", "source", "display_value"}
        for item in describe_features(f):
            assert required.issubset(set(item.keys())), f"Недостающие ключи в {item['key']}"

    def test_is_triggered_type_is_bool(self, sample_df):
        f = compute_features(sample_df)
        for item in describe_features(f):
            assert isinstance(item["is_triggered"], bool)

    def test_fl_ratio_triggered_in_sample(self, sample_df):
        """sample_df: fl_ratio = 0.325 > 0.30 — должен быть is_triggered = True."""
        f = compute_features(sample_df)
        described = {d["key"]: d for d in describe_features(f)}
        assert described["fl_ratio"]["is_triggered"] is True

    def test_tax_ratio_not_triggered_in_sample(self, sample_df):
        """sample_df: tax_ratio = 0.10 > 0.009 → is_triggered = False."""
        f = compute_features(sample_df)
        described = {d["key"]: d for d in describe_features(f)}
        assert described["tax_ratio"]["is_triggered"] is False

    def test_order_matches_feature_keys(self, sample_df):
        """Порядок элементов describe_features должен совпадать с FEATURE_KEYS."""
        f = compute_features(sample_df)
        keys_from_describe = [item["key"] for item in describe_features(f)]
        assert keys_from_describe == FEATURE_KEYS


# ---------------------------------------------------------------------------
# feature_vector() — вектор для ML-модели
# ---------------------------------------------------------------------------

class TestFeatureVector:

    def test_length_is_seven(self, sample_df):
        f = compute_features(sample_df)
        assert len(feature_vector(f)) == 7

    def test_all_elements_are_float(self, sample_df):
        f = compute_features(sample_df)
        for v in feature_vector(f):
            assert isinstance(v, float)

    def test_order_matches_feature_keys(self, sample_df):
        f = compute_features(sample_df)
        vec = feature_vector(f)
        for i, key in enumerate(FEATURE_KEYS):
            assert vec[i] == pytest.approx(f[key])

    def test_values_in_range_zero_to_one(self, sample_df):
        f = compute_features(sample_df)
        for v in feature_vector(f):
            assert 0.0 <= v <= 1.0, f"Значение вне [0, 1]: {v}"


# ---------------------------------------------------------------------------
# Пустой / вырожденный DataFrame
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_dataframe_all_zeros(self):
        """Пустая выписка → все признаки = 0.0."""
        df = make_df([])
        f = compute_features(df)
        for key in FEATURE_KEYS:
            assert f[key] == 0.0, f"{key} должен быть 0.0 для пустого df"

    def test_single_credit_row(self):
        """Одна кредитная транзакция — не должна ронять приложение."""
        df = make_df([("2024-03-01", 100_000, "credit", "Поступление", "ООО А", "")])
        f = compute_features(df)
        assert isinstance(f, dict)
        assert len(f) == 7

    def test_single_debit_row(self):
        """Одна дебетовая транзакция — не должна ронять приложение."""
        df = make_df([("2024-03-01", 50_000, "debit", "Снятие наличных", "Банкомат", "")])
        f = compute_features(df)
        assert f["cash_ratio"] == pytest.approx(1.0)

    def test_all_features_are_float(self, sample_df):
        """Все значения признаков — float."""
        f = compute_features(sample_df)
        for key, val in f.items():
            assert isinstance(val, float), f"{key}: ожидался float, получен {type(val)}"

    def test_feature_meta_has_seven_entries(self):
        """FEATURE_META содержит ровно 7 записей."""
        assert len(FEATURE_META) == 7

    def test_feature_keys_unique(self):
        """Все ключи в FEATURE_KEYS уникальны."""
        assert len(FEATURE_KEYS) == len(set(FEATURE_KEYS))
