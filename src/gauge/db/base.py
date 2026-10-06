"""Declarative base, constraint naming and portable column types."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, MetaData, Numeric, String
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator, TypeEngine

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DecimalValue(TypeDecorator):
    """Exact decimals on every backend.

    PostgreSQL gets NUMERIC(38, 12). SQLite has no exact decimal type and SQLAlchemy would
    round-trip NUMERIC through float, so SQLite stores the canonical decimal text instead.
    """

    impl = Numeric
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(64))
        return dialect.type_descriptor(Numeric(38, 12))

    def process_bind_param(self, value, dialect: Dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("DecimalValue refuses float; pass Decimal or str")
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
        return format(dec, "f") if dialect.name == "sqlite" else dec

    def process_result_value(self, value, dialect: Dialect):
        return None if value is None else Decimal(str(value))


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes; SQLite drops tzinfo, so it is restored on read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect: Dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime refused: pass a timezone-aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect: Dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def in_values(
    column: str, values: Iterable[str], name: str, nullable: bool = False
) -> CheckConstraint:
    """CHECK (column IN (...)); portable replacement for ENUM types."""
    listed = ", ".join(f"'{v}'" for v in values)
    expr = f"{column} IN ({listed})"
    if nullable:
        expr = f"{column} IS NULL OR {expr}"
    return CheckConstraint(expr, name=name)
