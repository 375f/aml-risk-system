"""
db/connection.py — SQLAlchemy engine и фабрика сессий.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import DATABASE_URL

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,   # проверяет соединение перед выдачей из пула
    pool_size=5,
    max_overflow=10,
)

# ---------------------------------------------------------------------------
# Фабрика сессий
# ---------------------------------------------------------------------------

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# ---------------------------------------------------------------------------
# Базовый класс для ORM-моделей
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass
