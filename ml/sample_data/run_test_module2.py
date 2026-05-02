"""
ml/sample_data/run_test_module2.py — интеграционный тест Модуля 2 на реальных ИНН.

Запуск из aml_system/:
    python -X utf8 ml/sample_data/run_test_module2.py
"""

from __future__ import annotations

import io
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# UTF-8 вывод на Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from module2.rusprofile_api import get_entity_by_inn
from module2.scorer import score_contractor
from module2.validator import validate_inn, get_inn_type

SEP  = "=" * 64
sep2 = "-" * 64

VERDICT_RU    = {"safe": "Безопасно", "caution": "Требует внимания", "high_risk": "Высокий риск"}
VERDICT_ICON  = {"safe": "✅", "caution": "⚠️", "high_risk": "🔴"}
ENTITY_RU     = {"ul": "Юридическое лицо", "ip": "Индивидуальный предприниматель"}


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def ok(msg: str)   -> None: print(f"  [PASS]  {msg}")
def fail(msg: str) -> None: print(f"  [FAIL]  {msg}")
def info(msg: str) -> None: print(f"          {msg}")


# ---------------------------------------------------------------------------
# Тест-кейсы
# ---------------------------------------------------------------------------

CASES = [
    {
        "inn":           "7707083893",
        "label":         "Сбербанк",
        "expect_found":  True,
        "expect_status": "active",
        "expect_verdict": "safe",
        "expect_entity": "ul",
    },
    {
        "inn":           "7710140679",
        "label":         "Тинькофф (ТКС Банк)",
        "expect_found":  True,
        "expect_status": "active",
        "expect_verdict": "safe",
        "expect_entity": "ul",
    },
    {
        "inn":           "732815880648",
        "label":         "Личный ИНН (ИП/физлицо)",
        "expect_found":  True,      # rusprofile может не найти физлицо — тест гибкий
        "expect_status": None,      # любой
        "expect_verdict": None,     # любой
        "expect_entity": "ip",
    },
    {
        "inn":           "1234567890",
        "label":         "Несуществующий ИНН",
        "expect_found":  False,     # должна быть ошибка
        "expect_status": None,
        "expect_verdict": None,
        "expect_entity": None,
    },
]

total_errors = 0

for case in CASES:
    inn    = case["inn"]
    label  = case["label"]

    section(f"ИНН {inn} — {label}")

    # --- Шаг 0: валидация ИНН ---
    is_valid = validate_inn(inn)
    if is_valid:
        inn_type = get_inn_type(inn)
        ok(f"Валидация ИНН: корректный ({ENTITY_RU.get(inn_type, inn_type)})")
    else:
        if case["expect_found"]:
            fail(f"Валидация ИНН: некорректный (контрольная сумма не совпадает)")
            total_errors += 1
        else:
            ok(f"Валидация ИНН: некорректный — ожидаемо")

    # --- Шаг 1: запрос к Rusprofile ---
    print(f"\n  Запрос к Rusprofile...")
    t0 = time.time()
    entity = None
    error_msg = None

    try:
        entity = get_entity_by_inn(inn)
        elapsed = time.time() - t0
        ok(f"Rusprofile ответил за {elapsed:.1f} сек.")
    except Exception as e:
        elapsed = time.time() - t0
        error_msg = str(e)
        if not case["expect_found"]:
            ok(f"Ожидаемая ошибка за {elapsed:.1f} сек.: {error_msg}")
        else:
            fail(f"Неожиданная ошибка: {error_msg}")
            total_errors += 1
        continue

    if not case["expect_found"]:
        fail(f"Ожидалась ошибка, но запрос вернул данные")
        total_errors += 1

    # --- Шаг 2: структура ответа ---
    required_keys = {"name", "status", "reg_date", "address", "ogrn",
                     "entity_type", "mass_address", "mass_director", "capital"}
    missing = required_keys - set(entity.keys())
    if missing:
        fail(f"Отсутствуют ключи: {missing}")
        total_errors += 1
    else:
        ok(f"Все 9 обязательных ключей присутствуют")

    # --- Шаг 3: вывод данных ---
    print(f"\n  Данные из Rusprofile:")
    print(f"  {sep2}")
    def fmt(v): return str(v) if v is not None else "—"
    print(f"  Наименование    : {fmt(entity.get('name'))}")
    print(f"  Статус          : {fmt(entity.get('status'))}")
    print(f"  Тип субъекта    : {ENTITY_RU.get(entity.get('entity_type',''), entity.get('entity_type','—'))}")
    print(f"  ОГРН            : {fmt(entity.get('ogrn'))}")
    print(f"  Дата регистрации: {fmt(entity.get('reg_date'))}")
    print(f"  Адрес           : {fmt(entity.get('address'))}")
    print(f"  Уст. капитал    : {entity['capital']:,.0f} руб.".replace(",", " ") if entity.get('capital') else "  Уст. капитал    : —")
    print(f"  Массовый адрес  : {'Да' if entity.get('mass_address') else 'Нет'}")
    print(f"  Массовый рук.   : {'Да' if entity.get('mass_director') else 'Нет'}")

    # Проверяем ожидаемый статус
    if case["expect_status"] and entity.get("status") != case["expect_status"]:
        fail(f"Статус: ожидался '{case['expect_status']}', получен '{entity.get('status')}'")
        total_errors += 1
    elif case["expect_status"]:
        ok(f"Статус совпадает с ожидаемым: '{entity.get('status')}'")

    # Проверяем тип субъекта
    if case["expect_entity"] and entity.get("entity_type") != case["expect_entity"]:
        fail(f"entity_type: ожидался '{case['expect_entity']}', получен '{entity.get('entity_type')}'")
        total_errors += 1
    elif case["expect_entity"]:
        ok(f"entity_type совпадает: '{entity.get('entity_type')}'")

    # Дата регистрации — должна быть date объектом или None
    reg = entity.get("reg_date")
    if reg is not None and not isinstance(reg, date):
        fail(f"reg_date должен быть date, получен {type(reg)}")
        total_errors += 1
    elif reg is not None:
        age_months = (date.today().year - reg.year) * 12 + (date.today().month - reg.month)
        ok(f"Дата регистрации корректна, возраст: {age_months // 12} лет {age_months % 12} мес.")

    # mass_address и mass_director — должны быть bool
    for field in ("mass_address", "mass_director"):
        v = entity.get(field)
        if not isinstance(v, bool):
            fail(f"{field} должен быть bool, получен {type(v)}")
            total_errors += 1

    # --- Шаг 4: скоринг ---
    print(f"\n  Скоринг по 5 критериям 115-ФЗ:")
    print(f"  {sep2}")
    try:
        score, verdict, triggered = score_contractor(entity)
        icon = VERDICT_ICON.get(verdict, "?")
        verdict_ru = VERDICT_RU.get(verdict, verdict)
        print(f"  Балл риска : {score} / 100")
        print(f"  Вердикт    : {icon} {verdict_ru} ({verdict})")
        if triggered:
            print(f"  Сработало  : {len(triggered)} критерия")
            for t in triggered:
                print(f"    ⚠  {t}")
        else:
            print(f"  Сработало  : нет (все критерии в норме)")

        if case["expect_verdict"] and verdict != case["expect_verdict"]:
            fail(f"Вердикт: ожидался '{case['expect_verdict']}', получен '{verdict}' (балл={score})")
            total_errors += 1
        elif case["expect_verdict"]:
            ok(f"Вердикт совпадает с ожидаемым: '{verdict}'")

        if not (0 <= score <= 100):
            fail(f"Балл вне диапазона [0, 100]: {score}")
            total_errors += 1
        else:
            ok(f"Балл в диапазоне [0, 100]")

    except Exception as e:
        fail(f"Ошибка score_contractor: {e}")
        total_errors += 1

    # --- Шаг 5: сохранение в БД ---
    print(f"\n  Сохранение в БД...")
    try:
        from datetime import timedelta
        from db.connection import SessionLocal
        from db.crud import save_contractor, get_contractor_cache

        expires = datetime.now(timezone.utc) + timedelta(hours=24)
        contractor_data = {
            **entity,
            "inn":        inn,
            "risk_score": score,
            "verdict":    verdict,
            "expires_at": expires,
            "raw_json":   entity,
        }
        session = SessionLocal()
        saved = save_contractor(session, contractor_data)
        ok(f"Сохранено в contractors: id={saved.id}, inn={saved.inn}")

        # Проверяем кэш
        cached = get_contractor_cache(session, inn)
        if cached and cached.id == saved.id:
            ok(f"Кэш работает: get_contractor_cache вернул запись id={cached.id}")
        else:
            fail(f"Кэш не работает: get_contractor_cache вернул {cached}")
            total_errors += 1

        session.close()
    except Exception as e:
        fail(f"Ошибка записи в БД: {e}")
        total_errors += 1


# ---------------------------------------------------------------------------
# Итог
# ---------------------------------------------------------------------------

section("Итоговый отчёт")
print()
print(f"  Протестировано ИНН: {len(CASES)}")
print(f"  Ошибок: {total_errors}")
print()
if total_errors == 0:
    print("  ✅  Все тест-кейсы пройдены успешно")
else:
    print(f"  ❌  Провалено проверок: {total_errors}")
print()
sys.exit(0 if total_errors == 0 else 1)
