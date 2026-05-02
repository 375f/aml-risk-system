"""
db/init_db.py — создание всех таблиц и индексов в PostgreSQL.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from db.connection import Base, engine
import db.models  # noqa: F401 — регистрирует все ORM-классы в Base.metadata

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_analysis_created    ON analysis_history(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_risk       ON analysis_history(risk_level)",
    "CREATE INDEX IF NOT EXISTS idx_contractors_inn     ON contractors(inn)",
    "CREATE INDEX IF NOT EXISTS idx_contractors_expires ON contractors(expires_at)",
]


def init_db() -> None:
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            for stmt in _INDEXES:
                conn.execute(text(stmt))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)

    tables = sorted(Base.metadata.tables.keys())
    for t in tables:
        print(f"  + {t}")
    print(f"\nOK: all tables created ({len(tables)})")


if __name__ == "__main__":
    init_db()
