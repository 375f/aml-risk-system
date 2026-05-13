-- Таблица 1: история анализов выписок
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

-- Таблица 2: сработавшие факторы риска (1:N к analysis_history)
CREATE TABLE IF NOT EXISTS risk_factors (
    id            SERIAL PRIMARY KEY,
    analysis_id   INTEGER NOT NULL REFERENCES analysis_history(id) ON DELETE CASCADE,
    factor_name   VARCHAR(100) NOT NULL,
    factor_value  NUMERIC(10, 4),
    threshold     NUMERIC(10, 4),
    is_triggered  BOOLEAN DEFAULT FALSE,
    importance    NUMERIC(5, 4)
);

-- Таблица 3: кэш проверенных контрагентов (TTL 24 часа)
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

-- Индексы
CREATE INDEX IF NOT EXISTS idx_analysis_created    ON analysis_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_risk       ON analysis_history(risk_level);
CREATE INDEX IF NOT EXISTS idx_contractors_inn     ON contractors(inn);
CREATE INDEX IF NOT EXISTS idx_contractors_expires ON contractors(expires_at);
