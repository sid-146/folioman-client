"""Map SQLAlchemy ORM models to framework-free core Pydantic domain models."""

from __future__ import annotations

from folioman_client.core.models.holding import Holding as CoreHolding, HoldingSource
from folioman_client.core.models.security import Security as CoreSecurity, SecurityType
from folioman_client.core.models.transaction import (
    Transaction as CoreTransaction,
    TransactionSource,
    TransactionType,
)
from folioman_client.db.models import Holding as DBHolding, Security as DBSecurity, Transaction as DBTransaction


def to_core_security(security: DBSecurity) -> CoreSecurity:
    """SQLAlchemy ``Security`` row -> core ``Security`` value object."""
    raw_type = (security.security_type or "mf").lower()
    return CoreSecurity(
        type=SecurityType(raw_type),
        name=security.name,
        isin=security.isin or "",
        symbol=security.symbol or "",
        exchange=security.exchange or "",
        currency=security.currency or "INR",
        amfi_code=security.amfi_code or "",
        metadata=dict(security.metadata_json or {}),
    )

def to_core_transaction(txn: DBTransaction) -> CoreTransaction:
    """SQLAlchemy ``Transaction`` row -> core ``Transaction`` domain model."""
    raw_type = (txn.transaction_type or "buy").lower().replace(" ", "_")
    if raw_type in ("redemption", "switch_out"):
        raw_type = "sell"
    elif raw_type in ("purchase", "sip", "switch_in"):
        raw_type = "buy"

    raw_source = (txn.source or "cas-pdf").lower().replace("_", "-")
    try:
        ts_enum = TransactionSource(raw_source)
    except ValueError:
        ts_enum = TransactionSource.CAS_PDF

    try:
        tt_enum = TransactionType(raw_type)
    except ValueError:
        tt_enum = TransactionType.BUY

    return CoreTransaction(
        security=to_core_security(txn.security),
        date=txn.date,
        type=tt_enum,
        units=txn.units,
        nav_or_price=txn.nav_or_price,
        amount=txn.amount,
        currency=txn.currency or "INR",
        fx_rate_to_inr=txn.fx_rate_to_inr,
        fees=txn.fees,
        stamp_duty=txn.stamp_duty,
        brokerage=txn.brokerage,
        cost_total=txn.cost_total,
        source=ts_enum,
        source_ref=txn.source_ref or "",
        folio_number=txn.folio.number if txn.folio else "",
        broker=txn.folio.broker if txn.folio else "",
        ledger_id=txn.id,
    )


def to_core_holding(holding: DBHolding) -> CoreHolding:
    """SQLAlchemy ``Holding`` row -> core ``Holding`` snapshot model."""
    raw_source = (holding.source or "cas-pdf").lower().replace("_", "-")
    try:
        hs_enum = HoldingSource(raw_source)
    except ValueError:
        hs_enum = HoldingSource.CAS_PDF

    return CoreHolding(
        security=to_core_security(holding.security),
        as_of_date=holding.as_of_date,
        units=holding.units,
        value_observed=holding.value_observed,
        avg_cost_observed=holding.avg_cost_observed,
        source=hs_enum,
        source_ref=holding.source_ref or "",
        folio_number=holding.folio.number if holding.folio else "",
        broker=holding.folio.broker if holding.folio else "",
    )


__all__ = [
    "to_core_security",
    "to_core_transaction",
    "to_core_holding",
]
