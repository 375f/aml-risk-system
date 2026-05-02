"""
ml/sample_data/run_test.py — интеграционный тест Модуля 1 на реальных данных.

Запуск из aml_system/:
    python ml/sample_data/run_test.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

# Принудительно UTF-8 вывод на Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Добавляем корень aml_system в путь
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from datetime import date, timezone, datetime

import pandas as pd

# ---------------------------------------------------------------------------

CSV_PATH = Path(__file__).parent / "test_statement.csv"
OKVED    = "46"   # оптовая торговля

SEP  = "=" * 62
sep2 = "-" * 62


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def ok(msg: str) -> None:
    print(f"  [PASS]  {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL]  {msg}")


def info(msg: str) -> None:
    print(f"          {msg}")


# ---------------------------------------------------------------------------
# Шаг 1 — Парсинг выписки
# ---------------------------------------------------------------------------

section("Шаг 1 — Парсинг CSV-выписки")

from module1.parser import parse_statement, ParseError, ColumnMappingError

errors = 0
try:
    with open(CSV_PATH, "rb") as f:
        # Имитируем Streamlit UploadedFile — добавляем атрибут name
        class _FakeFile:
            name = CSV_PATH.name
            def read(self): return f.read()

        df, date_from, date_to = parse_statement(_FakeFile())
except (ParseError, ColumnMappingError) as e:
    fail(f"Ошибка парсинга: {e}")
    sys.exit(1)
except Exception as e:
    fail(f"Неожиданная ошибка: {e}")
    sys.exit(1)

# Проверки структуры
expected_cols = {"date", "amount", "type", "description", "counterparty", "inn"}
missing_cols = expected_cols - set(df.columns)
if missing_cols:
    fail(f"Отсутствуют колонки: {missing_cols}")
    errors += 1
else:
    ok(f"Все 6 канонических колонок присутствуют")

total_rows = len(df)
if total_rows == 50:
    ok(f"Строк в DataFrame: {total_rows} (ожидалось 50)")
else:
    fail(f"Строк в DataFrame: {total_rows} (ожидалось 50)")
    errors += 1

debit_rows  = (df["type"] == "debit").sum()
credit_rows = (df["type"] == "credit").sum()
ok(f"Дебетовых операций: {debit_rows}")
ok(f"Кредитовых операций: {credit_rows}")

if set(df["type"].unique()) == {"debit", "credit"}:
    ok("Поле type содержит только 'debit' / 'credit'")
else:
    fail(f"Неожиданные значения type: {df['type'].unique()}")
    errors += 1

null_amounts = df["amount"].isna().sum()
zero_amounts = (df["amount"] == 0).sum()
if null_amounts == 0 and zero_amounts == 0:
    ok(f"Нет нулевых/пустых сумм")
else:
    fail(f"Нулевые/пустые суммы: null={null_amounts}, zero={zero_amounts}")
    errors += 1

null_dates = df["date"].isna().sum()
if null_dates == 0:
    ok(f"Все даты распознаны")
else:
    fail(f"Нераспознанных дат: {null_dates}")
    errors += 1

if date_from and date_to:
    ok(f"Период выписки: {date_from} — {date_to}")
else:
    fail("Период выписки не определён")
    errors += 1

debit_total  = float(df[df["type"] == "debit"]["amount"].sum())
credit_total = float(df[df["type"] == "credit"]["amount"].sum())
info(f"Дебет всего:   {debit_total:>14,.0f} руб.")
info(f"Кредит всего:  {credit_total:>14,.0f} руб.")

# Проверка ожидаемых сумм (вычислены заранее)
EXPECTED_DEBIT  = 6_493_500.0
EXPECTED_CREDIT = 9_940_000.0
tol = 1.0  # рублей

if abs(debit_total - EXPECTED_DEBIT) <= tol:
    ok(f"Сумма дебета совпадает с ожидаемой ({EXPECTED_DEBIT:,.0f} руб.)")
else:
    fail(f"Сумма дебета {debit_total:,.0f} ≠ ожидаемой {EXPECTED_DEBIT:,.0f}")
    errors += 1

if abs(credit_total - EXPECTED_CREDIT) <= tol:
    ok(f"Сумма кредита совпадает с ожидаемой ({EXPECTED_CREDIT:,.0f} руб.)")
else:
    fail(f"Сумма кредита {credit_total:,.0f} ≠ ожидаемой {EXPECTED_CREDIT:,.0f}")
    errors += 1


# ---------------------------------------------------------------------------
# Шаг 2 — Вычисление признаков риска
# ---------------------------------------------------------------------------

section("Шаг 2 — Вычисление 7 признаков риска (ОКЭД 46)")

from module1.features import compute_features, describe_features, FEATURE_META

try:
    features  = compute_features(df, okved=OKVED)
    described = describe_features(features)
except Exception as e:
    fail(f"Ошибка compute_features: {e}")
    sys.exit(1)

if len(features) == 7:
    ok(f"Вычислено признаков: {len(features)}")
else:
    fail(f"Ожидалось 7 признаков, получено {len(features)}")
    errors += 1

all_float = all(isinstance(v, float) for v in features.values())
all_in_range = all(0.0 <= v <= 1.0 for v in features.values())
if all_float and all_in_range:
    ok(f"Все значения — float в диапазоне [0, 1]")
else:
    fail(f"Есть значения вне [0, 1]: {features}")
    errors += 1

# Ожидаемые диапазоны (с допуском ±0.05 на вариации расчётов)
EXPECTED = {
    "cash_ratio":                (0.020, 0.060, False),  # ~0.033, НЕ сработает
    "tax_ratio":                 (0.010, 0.025, False),  # ~0.018, НЕ сработает
    "transit_ratio":             (0.50,  0.70,  True),   # ~0.58, СРАБОТАЕТ
    "okved_mismatch":            (0.55,  0.75,  True),   # ~0.64, СРАБОТАЕТ
    "avg_tx_norm":               (0.65,  0.85,  True),   # ~0.75, СРАБОТАЕТ (< 1.0)
    "counterparty_concentration":(0.45,  0.70,  False),  # ~0.59, НЕ сработает
    "fl_ratio":                  (0.01,  0.06,  False),  # ~0.026, НЕ сработает
}

print()
print(f"  {'Признак':<35} {'Значение':>10}  {'Норма':>8}  Статус")
print(f"  {sep2}")
for d in described:
    key  = d["key"]
    val  = d["value"]
    trig = d["is_triggered"]
    disp = d["display_value"]
    thr_disp = f"{d['threshold'] * d['scale']:.1f} {d['unit']}".strip()
    status = "⚠ РИСК" if trig else "✓ норма"

    lo, hi, exp_trig = EXPECTED.get(key, (0.0, 1.0, None))
    in_range = lo <= val <= hi
    exp_str = "СРАБ." if exp_trig else "норм."

    range_ok = "✓" if in_range else "?"

    print(f"  {d['label']:<35} {disp:>10}  {thr_disp:>8}  {status}  (ожид: {exp_str}) {range_ok}")

    if exp_trig is not None and trig != exp_trig:
        fail(f"  {key}: ожидалось is_triggered={exp_trig}, получено {trig}")
        errors += 1

triggered_count = sum(1 for d in described if d["is_triggered"])
info(f"Сработавших признаков: {triggered_count} из 7")


# ---------------------------------------------------------------------------
# Шаг 3 — Классификация рисков
# ---------------------------------------------------------------------------

section("Шаг 3 — Классификация риска (RandomForest)")

from module1.classifier import predict

try:
    result = predict(features)
except Exception as e:
    fail(f"Ошибка predict: {e}")
    sys.exit(1)

RISK_LABEL = {"low": "Низкий", "medium": "Средний", "high": "Высокий"}
level = result["risk_level"]
proba = result["risk_proba"]
imps  = result["importances"]

ok(f"Уровень риска: {RISK_LABEL.get(level, level)} ({level})")
ok(f"Уверенность модели: {proba * 100:.1f}%")

if level not in ("low", "medium", "high"):
    fail(f"Недопустимое значение risk_level: {level}")
    errors += 1

if not (0.0 <= proba <= 1.0):
    fail(f"risk_proba вне [0, 1]: {proba}")
    errors += 1

if len(imps) == 7:
    ok(f"Feature importances: {len(imps)} ключей")
else:
    fail(f"Ожидалось 7 importances, получено {len(imps)}")
    errors += 1

print()
print(f"  {'Признак':<35} {'Важность':>10}")
print(f"  {sep2}")
for key, imp in sorted(imps.items(), key=lambda x: -x[1]):
    bar = "#" * int(imp * 30)
    meta = next((m for m in FEATURE_META if m["key"] == key), {})
    label = meta.get("label", key)
    print(f"  {label:<35} {imp:>10.4f}  {bar}")


# ---------------------------------------------------------------------------
# Шаг 4 — Сохранение в БД
# ---------------------------------------------------------------------------

section("Шаг 4 — Сохранение в PostgreSQL")

from db.connection import SessionLocal
from db.crud import save_analysis, get_history
from db.models import AnalysisHistory, RiskFactor

factors_data = [
    {
        "factor_name":  d["key"],
        "factor_value": d["value"],
        "threshold":    d["threshold"],
        "is_triggered": d["is_triggered"],
        "importance":   result["importances"].get(d["key"], 0.0),
    }
    for d in described
]

session = None
saved_id = None
try:
    session = SessionLocal()
    record = save_analysis(session, {
        "filename":         CSV_PATH.name,
        "period_start":     date_from,
        "period_end":       date_to,
        "total_debit":      debit_total,
        "total_credit":     credit_total,
        "tx_count":         len(df),
        "risk_level":       level,
        "risk_score":       proba,
        "features_json":    features,
        "importances_json": imps,
        "factors":          factors_data,
    })
    saved_id = record.id
    ok(f"Запись сохранена. ID = {saved_id}")
except Exception as e:
    fail(f"Ошибка сохранения в БД: {e}")
    errors += 1

# Верификация — читаем обратно из БД
if session and saved_id:
    try:
        from sqlalchemy import select

        # Проверяем AnalysisHistory
        ah = session.get(AnalysisHistory, saved_id)
        if ah is None:
            fail("Запись не найдена в analysis_history")
            errors += 1
        else:
            ok(f"analysis_history: id={ah.id}, filename='{ah.filename}'")
            ok(f"  risk_level={ah.risk_level}, risk_score={ah.risk_score:.4f}")
            ok(f"  tx_count={ah.tx_count}, period={ah.period_start}—{ah.period_end}")
            ok(f"  total_debit={ah.total_debit:,.0f}, total_credit={ah.total_credit:,.0f}")

            # Проверяем поля
            checks = [
                (ah.filename == CSV_PATH.name, f"filename = '{ah.filename}'"),
                (ah.tx_count == 50,             f"tx_count = {ah.tx_count}"),
                (ah.risk_level in ("low","medium","high"), f"risk_level = '{ah.risk_level}'"),
                (abs(float(ah.total_debit)  - EXPECTED_DEBIT)  <= 1, f"total_debit ok"),
                (abs(float(ah.total_credit) - EXPECTED_CREDIT) <= 1, f"total_credit ok"),
                (ah.features_json is not None,    "features_json not null"),
                (ah.importances_json is not None, "importances_json not null"),
            ]
            for passed, label in checks:
                if passed:
                    ok(f"  ✓ {label}")
                else:
                    fail(f"  ✗ {label}")
                    errors += 1

        # Проверяем risk_factors
        from sqlalchemy import select as sa_select
        rf_rows = list(session.scalars(
            sa_select(RiskFactor).where(RiskFactor.analysis_id == saved_id)
        ))
        if len(rf_rows) == 7:
            ok(f"risk_factors: {len(rf_rows)} строк (ожидалось 7)")
        else:
            fail(f"risk_factors: {len(rf_rows)} строк (ожидалось 7)")
            errors += 1

        triggered_in_db = sum(1 for r in rf_rows if r.is_triggered)
        ok(f"  Сработавших в БД: {triggered_in_db} из 7")

        # Проверяем корректность хранения факторов
        factor_ok = True
        for rf in rf_rows:
            expected_val = features.get(rf.factor_name)
            if expected_val is not None:
                db_val = float(rf.factor_value) if rf.factor_value is not None else None
                # NUMERIC(10,4) хранит 4 знака — сравниваем с такой же точностью
                if db_val is not None and round(db_val, 4) != round(expected_val, 4):
                    fail(f"  factor {rf.factor_name}: в БД {db_val:.4f} ≠ {expected_val:.4f}")
                    errors += 1
                    factor_ok = False
        if factor_ok:
            ok("  Значения factor_value совпадают с вычисленными (точность 4 знака)")

        # Проверяем get_history
        history = get_history(session, limit=1)
        if history and history[0].id == saved_id:
            ok(f"get_history() возвращает последнюю запись корректно")
        else:
            fail(f"get_history() не вернул последнюю запись")
            errors += 1

    except Exception as e:
        fail(f"Ошибка верификации БД: {e}")
        errors += 1
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Итог
# ---------------------------------------------------------------------------

section("Итог")

if errors == 0:
    print(f"\n  ✅  Все проверки пройдены успешно.")
    print(f"      CSV: {CSV_PATH.name}")
    print(f"      Строк: 50  |  Дебет: {debit_total:,.0f} руб.  |  Кредит: {credit_total:,.0f} руб.")
    print(f"      Риск: {RISK_LABEL.get(level, level)} ({proba*100:.1f}%)  |  Сработало: {triggered_count}/7")
    print(f"      Запись в БД: ID={saved_id}")
else:
    print(f"\n  ❌  Провалено проверок: {errors}")

print()
sys.exit(0 if errors == 0 else 1)
