"""
db/models.py — ORM-классы для трёх таблиц схемы AML.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.connection import Base


class AnalysisHistory(Base):
    """История анализов банковских выписок."""

    __tablename__ = "analysis_history"
    __table_args__ = (
        Index("idx_analysis_created", "created_at"),
        Index("idx_analysis_risk",    "risk_level"),
    )

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True)
    created_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    filename:         Mapped[str | None]     = mapped_column(String(255))
    period_start:     Mapped[date | None]    = mapped_column(Date)
    period_end:       Mapped[date | None]    = mapped_column(Date)
    total_debit:      Mapped[float | None]   = mapped_column(Numeric(15, 2))
    total_credit:     Mapped[float | None]   = mapped_column(Numeric(15, 2))
    tx_count:         Mapped[int | None]     = mapped_column(Integer)
    risk_level:       Mapped[str | None]     = mapped_column(String(10))
    risk_score:       Mapped[float | None]   = mapped_column(Numeric(5, 4))
    features_json:    Mapped[dict | None]    = mapped_column(JSONB)
    importances_json: Mapped[dict | None]    = mapped_column(JSONB)

    factors: Mapped[list[RiskFactor]] = relationship(
        "RiskFactor",
        back_populates="analysis",
        cascade="all, delete-orphan",
        lazy="select",
    )


class RiskFactor(Base):
    """Сработавшие факторы риска (1:N к AnalysisHistory)."""

    __tablename__ = "risk_factors"

    id:           Mapped[int]          = mapped_column(Integer, primary_key=True)
    analysis_id:  Mapped[int]          = mapped_column(Integer, ForeignKey("analysis_history.id", ondelete="CASCADE"), nullable=False)
    factor_name:  Mapped[str]          = mapped_column(String(100), nullable=False)
    factor_value: Mapped[float | None] = mapped_column(Numeric(10, 4))
    threshold:    Mapped[float | None] = mapped_column(Numeric(10, 4))
    is_triggered: Mapped[bool | None]  = mapped_column(Boolean, default=False)
    importance:   Mapped[float | None] = mapped_column(Numeric(5, 4))

    analysis: Mapped[AnalysisHistory] = relationship(
        "AnalysisHistory",
        back_populates="factors",
    )


class Contractor(Base):
    """Кэш проверенных контрагентов (TTL задаётся через expires_at)."""

    __tablename__ = "contractors"
    __table_args__ = (
        Index("idx_contractors_inn",     "inn"),
        Index("idx_contractors_expires", "expires_at"),
    )

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True)
    inn:           Mapped[str]           = mapped_column(String(12), nullable=False, unique=True)
    name:          Mapped[str | None]    = mapped_column(String(500))
    ogrn:          Mapped[str | None]    = mapped_column(String(15))
    entity_type:   Mapped[str | None]    = mapped_column(String(10))   # 'ul' | 'ip'
    status:        Mapped[str | None]    = mapped_column(String(50))
    reg_date:      Mapped[date | None]   = mapped_column(Date)
    address:       Mapped[str | None]    = mapped_column(Text)
    mass_address:  Mapped[bool | None]   = mapped_column(Boolean, default=False)
    mass_director: Mapped[bool | None]   = mapped_column(Boolean, default=False)
    capital:       Mapped[float | None]  = mapped_column(Numeric(15, 2))
    risk_score:    Mapped[int | None]    = mapped_column(Integer)
    verdict:       Mapped[str | None]    = mapped_column(String(20))   # 'safe' | 'caution' | 'high_risk'
    checked_at:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_json:      Mapped[dict | None]   = mapped_column(JSONB)
