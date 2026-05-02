# AML Risk System — Дипломный проект КНИТУ-КАИ

## Контекст

Дипломная работа студента 4 курса, специальность 09.03.04 «Программная инженерия».
Тема ВКР: «Разработка интеллектуальной системы раннего предупреждения рисков блокировки
банковских счетов» (115-ФЗ, ПОД/ФТ).

---

## Архитектура — ЕДИНЫЙ СЕРВИС с двумя модулями

Это **не** два отдельных приложения. Это одно Streamlit-приложение с двумя вкладками.

**Модуль 1**: ИП загружает выписку CSV/XLSX → система вычисляет 7 признаков риска
по критериям 18-МР и 19-МР ЦБ РФ → Random Forest классифицирует риск (low/medium/high)
→ светофор + объяснение через feature_importances_

**Модуль 2**: ИП вводит ИНН контрагента → запрос к API ФНС (ЕГРЮЛ/ЕГРИП) →
rule-based скоринг по 5 критериям → вердикт (safe/caution/high_risk) + детализация

---

## Технологический стек (строго, не заменять)

- Python 3.11
- Streamlit 1.35 (UI — только он, не Flask, не FastAPI)
- scikit-learn (RandomForestClassifier — только этот алгоритм)
- pandas (обработка данных)
- PostgreSQL (БД — только она, не SQLite, не MongoDB)
- SQLAlchemy 2.0 (ORM — только он)
- requests (HTTP-запросы к API ФНС)
- joblib (сериализация модели)

---

## Структура проекта

```
aml_system/
├── app.py
├── config.py
├── requirements.txt
├── .env
├── module1/
│   ├── __init__.py
│   ├── parser.py
│   ├── features.py
│   ├── classifier.py
│   └── ui.py
├── module2/
│   ├── __init__.py
│   ├── validator.py
│   ├── fns_api.py
│   ├── scorer.py
│   └── ui.py
├── ml/
│   ├── __init__.py
│   ├── dataset.py
│   ├── train.py
│   └── model.joblib
└── db/
    ├── __init__.py
    ├── connection.py
    ├── models.py
    ├── crud.py
    └── migrations/
        └── init.sql
```

---

## Этапы реализации

### Этап 1 — Подготовка окружения

Файлы: `config.py`, `requirements.txt`, `.env.example`, `app.py` (заглушка), `db/migrations/init.sql`

Задачи:
- Создать структуру папок
- Написать config.py со всеми порогами (см. раздел ниже)
- Написать requirements.txt
- Написать init.sql (три таблицы: analysis_history, risk_factors, contractors)
- Написать app.py — две пустые вкладки «Анализ выписки» и «Проверка контрагента»

### Этап 2 — Парсинг выписки и признаки риска

Файлы: `module1/parser.py`, `module1/features.py`

Задачи:
- parser.py: чтение CSV и XLSX, автомаппинг колонок по fuzzy-matching
- features.py: вычисление всех 7 признаков риска (см. раздел ниже)
- Написать тесты: tests/test_parser.py, tests/test_features.py

### Этап 3 — ML-модель

Файлы: `ml/dataset.py`, `ml/train.py`, `ml/model.joblib`, `module1/classifier.py`

Задачи:
- dataset.py: сгенерировать синтетический датасет 1000+ строк
- train.py: обучить RandomForestClassifier, GridSearchCV, сохранить model.joblib
- classifier.py: загрузить модель, predict(), объяснение через feature_importances_

### Этап 4 — База данных

Файлы: `db/connection.py`, `db/models.py`, `db/crud.py`

Задачи:
- connection.py: SQLAlchemy engine и SessionLocal
- models.py: ORM-классы для трёх таблиц
- crud.py: save_analysis(), get_history(), save_contractor(), get_contractor_cache()

### Этап 5 — Проверка контрагента

Файлы: `module2/validator.py`, `module2/fns_api.py`, `module2/scorer.py`

Задачи:
- validator.py: валидация ИНН по контрольной сумме
- fns_api.py: запрос к api.egrul.nalog.ru, обработка ответа и ошибок
- scorer.py: rule-based скоринг по 5 критериям, вычисление вердикта

### Этап 6 — UI и финальная сборка

Файлы: `module1/ui.py`, `module2/ui.py`, `app.py` (финальный)

Задачи:
- module1/ui.py: загрузка файла, таблица признаков, светофор, история анализов
- module2/ui.py: поле ввода ИНН, карточка контрагента, вердикт, список проверок
- app.py: склеить оба модуля в одно приложение

---

## Признаки риска (Модуль 1)

Реализовывать строго в `module1/features.py`:

```python
def compute_features(df: pd.DataFrame) -> dict:
    """
    df содержит колонки: date, amount, type, description, counterparty, inn
    type: 'debit' (расход) или 'credit' (приход)
    """
    total_debit = df[df['type'] == 'debit']['amount'].sum()

    # Признак 1: доля наличных (19-МР ЦБ РФ от 21.07.2017, порог 30%)
    cash_keywords = ['снятие наличных', 'выдача наличных', 'банкомат', 'касса']
    cash_mask = df['description'].str.contains('|'.join(cash_keywords), case=False, na=False)
    cash_ratio = df[cash_mask]['amount'].sum() / total_debit if total_debit > 0 else 0

    # Признак 2: налоговая нагрузка (18-МР ЦБ РФ от 21.07.2017, порог 0.9%)
    tax_keywords = ['ндс', 'налог', 'ифнс', 'фнс', 'пфр', 'взносы', 'фсс']
    tax_mask = df['description'].str.contains('|'.join(tax_keywords), case=False, na=False)
    tax_ratio = df[tax_mask]['amount'].sum() / total_debit if total_debit > 0 else 0

    # Признак 3: транзитный характер (поступления → списания за 3 дня)
    # реализовать через groupby date + rolling window

    # Признак 4: несоответствие ОКВЭД назначениям платежей

    # Признак 5: средняя сумма транзакции (нормализованная)

    # Признак 6: концентрация контрагентов

    # Признак 7: доля переводов физлицам

    return {
        'cash_ratio': cash_ratio,
        'tax_ratio': tax_ratio,
        'transit_ratio': ...,
        'okved_mismatch': ...,
        'avg_tx_norm': ...,
        'counterparty_concentration': ...,
        'fl_ratio': ...,
    }
```

---

## Скоринг контрагента (Модуль 2)

Реализовывать строго в `module2/scorer.py`:

```python
def score_contractor(data: dict) -> tuple[int, str, list[str]]:
    """
    Возвращает: (балл 0-100, вердикт, список сработавших признаков)
    """
    score = 0
    triggered = []

    if data['status'] == 'liquidated':
        score += 50
        triggered.append('Организация ликвидирована')
    elif data['status'] == 'liquidating':
        score += 40
        triggered.append('Организация в процессе ликвидации')

    age_months = data['age_months']
    if age_months < 3:
        score += 30
        triggered.append('Зарегистрирована менее 3 месяцев назад')
    elif age_months < 6:
        score += 20
        triggered.append('Зарегистрирована менее 6 месяцев назад')
    elif age_months < 12:
        score += 10
        triggered.append('Зарегистрирована менее года назад')

    if data.get('mass_address'):
        score += 20
        triggered.append('Массовый адрес регистрации')

    if data.get('mass_director'):
        score += 20
        triggered.append('Массовый руководитель')

    if data.get('capital', 0) <= 10000:
        score += 10
        triggered.append('Минимальный уставный капитал (10 000 руб.)')

    if score <= 25:
        verdict = 'safe'
    elif score <= 60:
        verdict = 'caution'
    else:
        verdict = 'high_risk'

    return score, verdict, triggered
```

---

## API ФНС

```python
# fns_api.py

FNS_URL = "https://api.egrul.nalog.ru/v1/"

def get_entity_by_inn(inn: str) -> dict:
    try:
        response = requests.get(
            f"{FNS_URL}{inn}",
            headers={"Accept": "application/json"},
            timeout=10
        )
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        raise Exception("API ФНС не отвечает (таймаут 10 сек)")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            raise Exception(f"ИНН {inn} не найден в ЕГРЮЛ/ЕГРИП")
        raise Exception(f"Ошибка API ФНС: {e.response.status_code}")
```

### Fallback при ошибке

Если API недоступен → проверить кэш PostgreSQL → если кэш пуст → показать:
`"Сервис ФНС временно недоступен. Попробуйте позже."`

---

## config.py — полная структура

```python
import os
from dotenv import load_dotenv

load_dotenv()

# База данных
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/aml_db")

# API ФНС
FNS_API_URL = "https://api.egrul.nalog.ru/v1/"
FNS_TIMEOUT = 10

# Пороги риска — Модуль 1
CASH_RATIO_THRESHOLD    = 0.30   # 19-МР ЦБ РФ
TAX_RATIO_THRESHOLD     = 0.009  # 18-МР ЦБ РФ
TRANSIT_RATIO_THRESHOLD = 0.50
OKVED_MISMATCH_THRESHOLD = 0.60
FL_RATIO_THRESHOLD      = 0.30

# Скоринг — Модуль 2
SCORE_LIQUIDATED    = 50
SCORE_LIQUIDATING   = 40
SCORE_YOUNG_3M      = 30
SCORE_YOUNG_6M      = 20
SCORE_YOUNG_12M     = 10
SCORE_MASS_ADDRESS  = 20
SCORE_MASS_DIRECTOR = 20
SCORE_MIN_CAPITAL   = 10

VERDICT_SAFE_MAX    = 25
VERDICT_CAUTION_MAX = 60

# Кэш контрагентов
CONTRACTOR_CACHE_TTL_HOURS = 24

# Модель
MODEL_PATH = "ml/model.joblib"
```

---

## Схема БД (init.sql)

```sql
CREATE TABLE IF NOT EXISTS analysis_history (
    id               SERIAL PRIMARY KEY,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    filename         VARCHAR(255),
    period_start     DATE,
    period_end       DATE,
    total_debit      NUMERIC(15, 2),
    total_credit     NUMERIC(15, 2),
    tx_count         INTEGER,
    risk_level       VARCHAR(10) CHECK (risk_level IN ('low', 'medium', 'high')),
    risk_score       NUMERIC(5, 4),
    features_json    JSONB,
    importances_json JSONB
);

CREATE TABLE IF NOT EXISTS risk_factors (
    id            SERIAL PRIMARY KEY,
    analysis_id   INTEGER NOT NULL REFERENCES analysis_history(id) ON DELETE CASCADE,
    factor_name   VARCHAR(100) NOT NULL,
    factor_value  NUMERIC(10, 4),
    threshold     NUMERIC(10, 4),
    is_triggered  BOOLEAN DEFAULT FALSE,
    importance    NUMERIC(5, 4)
);

CREATE TABLE IF NOT EXISTS contractors (
    id            SERIAL PRIMARY KEY,
    inn           VARCHAR(12) NOT NULL UNIQUE,
    name          VARCHAR(500),
    ogrn          VARCHAR(15),
    entity_type   VARCHAR(10) CHECK (entity_type IN ('ul', 'ip')),
    status        VARCHAR(50),
    reg_date      DATE,
    address       TEXT,
    mass_address  BOOLEAN DEFAULT FALSE,
    mass_director BOOLEAN DEFAULT FALSE,
    capital       NUMERIC(15, 2),
    risk_score    INTEGER CHECK (risk_score BETWEEN 0 AND 100),
    verdict       VARCHAR(20) CHECK (verdict IN ('safe', 'caution', 'high_risk')),
    checked_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMP,
    raw_json      JSONB
);

CREATE INDEX idx_analysis_created    ON analysis_history(created_at DESC);
CREATE INDEX idx_contractors_inn     ON contractors(inn);
CREATE INDEX idx_contractors_expires ON contractors(expires_at);
```

---

## Что НЕ нужно делать

- Не реализовывать аутентификацию и логин
- Не делать REST API — только Streamlit UI
- Не использовать нейросети или другие алгоритмы ML кроме Random Forest
- Не хранить файлы выписок на диске — только вычисленные признаки
- Не заменять PostgreSQL на SQLite без явного указания
- Не устанавливать лишние зависимости — только то, что в requirements.txt
