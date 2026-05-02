"""
db/crud.py — операции с базой данных.

Публичный API:
  save_analysis(session, data)         -> AnalysisHistory
  get_history(session, limit=50)       -> list[AnalysisHistory]
  save_contractor(session, data)       -> Contractor
  get_contractor_cache(session, inn)   -> Contractor | None
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import AnalysisHistory, Contractor, RiskFactor


def _json_safe(obj: Any) -> Any:
    """Рекурсивно преобразовать date/datetime в ISO-строки для хранения в JSONB."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# Модуль 1 — история анализов
# ---------------------------------------------------------------------------

def save_analysis(session: Session, data: dict) -> AnalysisHistory:
    """
    Сохранить результат анализа выписки.

    Ожидаемые ключи data:
        filename         str | None
        period_start     date | None
        period_end       date | None
        total_debit      float | None
        total_credit     float | None
        tx_count         int | None
        risk_level       'low' | 'medium' | 'high'
        risk_score       float  (вероятность предсказанного класса)
        features_json    dict   (7 признаков → float)
        importances_json dict   (7 признаков → float)
        factors          list[dict] — опционально, каждый dict:
            factor_name, factor_value, threshold, is_triggered, importance
    """
    factors_data: list[dict] = data.pop("factors", [])

    record = AnalysisHistory(
        filename         = data.get("filename"),
        period_start     = data.get("period_start"),
        period_end       = data.get("period_end"),
        total_debit      = data.get("total_debit"),
        total_credit     = data.get("total_credit"),
        tx_count         = data.get("tx_count"),
        risk_level       = data.get("risk_level"),
        risk_score       = data.get("risk_score"),
        features_json    = data.get("features_json"),
        importances_json = data.get("importances_json"),
    )
    session.add(record)
    session.flush()   # получаем record.id до commit

    for f in factors_data:
        session.add(RiskFactor(
            analysis_id  = record.id,
            factor_name  = f["factor_name"],
            factor_value = f.get("factor_value"),
            threshold    = f.get("threshold"),
            is_triggered = f.get("is_triggered", False),
            importance   = f.get("importance"),
        ))

    session.commit()
    return record


def get_history(session: Session, limit: int = 50) -> list[AnalysisHistory]:
    """Вернуть последние `limit` записей, отсортированных по убыванию даты."""
    stmt = (
        select(AnalysisHistory)
        .order_by(AnalysisHistory.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Модуль 2 — кэш контрагентов
# ---------------------------------------------------------------------------

def save_contractor(session: Session, data: dict) -> Contractor:
    """
    Сохранить (или обновить по INN) данные контрагента.

    Ожидаемые ключи data:
        inn, name, ogrn, entity_type, status, reg_date,
        address, mass_address, mass_director, capital,
        risk_score, verdict, expires_at, raw_json
    """
    inn: str = data["inn"]

    existing = session.scalar(select(Contractor).where(Contractor.inn == inn))
    if existing:
        for key, value in data.items():
            if hasattr(existing, key):
                setattr(existing, key, _json_safe(value) if key == "raw_json" else value)
        existing.checked_at = datetime.now(timezone.utc)
        session.commit()
        return existing

    record = Contractor(
        inn           = inn,
        name          = data.get("name"),
        ogrn          = data.get("ogrn"),
        entity_type   = data.get("entity_type"),
        status        = data.get("status"),
        reg_date      = data.get("reg_date"),
        address       = data.get("address"),
        mass_address  = data.get("mass_address", False),
        mass_director = data.get("mass_director", False),
        capital       = data.get("capital"),
        risk_score    = data.get("risk_score"),
        verdict       = data.get("verdict"),
        expires_at    = data.get("expires_at"),
        raw_json      = _json_safe(data.get("raw_json")),
    )
    session.add(record)
    session.commit()
    return record


def get_contractor_cache(session: Session, inn: str) -> Contractor | None:
    """
    Вернуть кэшированного контрагента, если expires_at > now().
    Возвращает None если запись не найдена или TTL истёк.
    """
    now = datetime.now(timezone.utc)
    stmt = (
        select(Contractor)
        .where(Contractor.inn == inn)
        .where(Contractor.expires_at > now)
    )
    return session.scalar(stmt)


def get_recent_contractors(session: Session, limit: int = 50) -> list[Contractor]:
    """Вернуть последние `limit` проверенных контрагентов, отсортированных по checked_at DESC."""
    stmt = (
        select(Contractor)
        .order_by(Contractor.checked_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())
