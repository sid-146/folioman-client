"""SQLAlchemy 2.0 declarative database models.

Includes all 18 core tables spanning:
  1. Reference master dictionary (schemes, ISINs, grandfathering NAVs, meta)
  2. Securities master and market NAV time-series history
  3. Investor portfolios, folios, immutable transaction ledgers, and holdings
  4. Day-wise net-worth series, corporate actions replay, and reconciliation status
  5. Import auditing and schema versioning
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base class for all Folioman models."""

    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class TimeStampedMixin:
    """Reusable timestamps for auditability."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ============================================================================
# 1. Reference Master Dictionary (Stored in Selected Database)
# ============================================================================


class SchemeReference(Base, TimeStampedMixin):
    """National mutual fund scheme master dictionary."""

    __tablename__ = "ref_schemes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rta: Mapped[str] = mapped_column(String(32), index=True, default="")
    rta_code: Mapped[str] = mapped_column(String(64), index=True, default="")
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    isin: Mapped[str] = mapped_column(String(12), index=True, default="")
    amfi_code: Mapped[str] = mapped_column(String(16), index=True, default="")
    type: Mapped[str] = mapped_column(String(32), default="")
    amc_code: Mapped[str] = mapped_column(String(32), index=True, default="")
    sebi_category: Mapped[str] = mapped_column(String(128), default="")


class ISINReference(Base, TimeStampedMixin):
    """National equity and bond ISIN-to-symbol reference master."""

    __tablename__ = "ref_isins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    isin: Mapped[str] = mapped_column(
        String(12), unique=True, index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True, default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    exchange: Mapped[str] = mapped_column(String(16), default="")
    type: Mapped[str] = mapped_column(String(64), default="")


class GrandfatheringNAV(Base, TimeStampedMixin):
    """Fair Market Value (NAV) on 31-Jan-2018 for Section 112A LTCG tax calculations."""

    __tablename__ = "ref_grandfathering_navs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    isin: Mapped[str] = mapped_column(
        String(12), unique=True, index=True, nullable=False
    )
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6, asdecimal=True), nullable=False)


class ReferenceMeta(Base):
    """Metadata tracking versions of the reference catalog."""

    __tablename__ = "ref_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ============================================================================
# 2. Master Market Data & Securities
# ============================================================================


class AMC(Base, TimeStampedMixin):
    """Asset Management Company (mutual fund house)."""

    __tablename__ = "amcs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), default="")

    securities: Mapped[list[Security]] = relationship("Security", back_populates="amc")


class Security(Base, TimeStampedMixin):
    """Canonical security reference (mutual fund, equity, bond, etf, crypto)."""

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    security_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    isin: Mapped[str] = mapped_column(String(12), index=True, default="")
    symbol: Mapped[str] = mapped_column(String(32), index=True, default="")
    exchange: Mapped[str] = mapped_column(String(16), default="")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    amfi_code: Mapped[str] = mapped_column(String(16), index=True, default="")
    amc_id: Mapped[int | None] = mapped_column(
        ForeignKey("amcs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    nav_feed_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    corporate_actions_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    amc: Mapped[AMC | None] = relationship("AMC", back_populates="securities")
    nav_history: Mapped[list[NAVHistory]] = relationship(
        "NAVHistory", back_populates="security", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction", back_populates="security"
    )
    holdings: Mapped[list[Holding]] = relationship("Holding", back_populates="security")

    __table_args__ = (
        Index(
            "uniq_security_isin",
            "isin",
            unique=True,
            sqlite_where=(isin != ""),
            postgresql_where=(isin != ""),
        ),
        Index(
            "uniq_security_amfi_code",
            "amfi_code",
            unique=True,
            sqlite_where=(amfi_code != ""),
            postgresql_where=(amfi_code != ""),
        ),
    )


class NAVHistory(Base, TimeStampedMixin):
    """Daily closing price / Net Asset Value time-series."""

    __tablename__ = "nav_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6, asdecimal=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="")

    security: Mapped[Security] = relationship("Security", back_populates="nav_history")

    __table_args__ = (
        UniqueConstraint("security_id", "date", name="uniq_nav_security_date"),
    )


class CorporateActionReference(Base, TimeStampedMixin):
    """Cached corporate action events from exchange feeds."""

    __tablename__ = "corporate_action_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    isin: Mapped[str] = mapped_column(String(12), index=True, default="")
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), default="")
    series: Mapped[str] = mapped_column(String(8), default="")
    exchange: Mapped[str] = mapped_column(String(8), default="")
    ex_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    parsed_type: Mapped[str] = mapped_column(String(32), default="")
    unit_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    parsed_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(8), default="")


class FXRate(Base, TimeStampedMixin):
    """Daily FX conversion rate."""

    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(
        String(3), default="INR", nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 6, asdecimal=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), default="")

    __table_args__ = (
        UniqueConstraint(
            "base_currency", "quote_currency", "date", name="uniq_fxrate_pair_date"
        ),
    )


# ============================================================================
# 3. User & Portfolio Ledger Tables
# ============================================================================


class Family(Base, TimeStampedMixin):
    """Group of investors for aggregated family reporting."""

    __tablename__ = "families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    investors: Mapped[list[Investor]] = relationship(
        "Investor", back_populates="family"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uniq_family_user_name"),
    )


class Investor(Base, TimeStampedMixin):
    """An individual investor portfolio entity."""

    __tablename__ = "investors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    family_id: Mapped[int | None] = mapped_column(
        ForeignKey("families.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="")
    is_huf: Mapped[bool] = mapped_column(Boolean, default=False)
    relation: Mapped[str] = mapped_column(String(32), default="")

    # Encrypted PAN at rest and keyed HMAC hash
    pan_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pan_hash: Mapped[str] = mapped_column(String(64), index=True, default="")

    @property
    def pan_masked(self) -> str:
        """Derive masked PAN for safe display (e.g. 'XXXXXX234F')."""
        if not self.pan_encrypted:
            return ""
        try:
            from folioman_client.security.pan import decrypt_pan, mask_pan

            return mask_pan(decrypt_pan(self.pan_encrypted))
        except Exception:
            return "XXXXXXXXXX"

    @property
    def pan_plain(self) -> str:
        """Decrypt PAN into plaintext string."""
        if not self.pan_encrypted:
            return ""
        from folioman_client.security.pan import decrypt_pan

        return decrypt_pan(self.pan_encrypted)

    # Valuation recompute lifecycle state
    valuation_status: Mapped[str] = mapped_column(String(16), default="ready")
    valuation_recompute_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valuation_computed_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    valuation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    valuation_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valuation_error: Mapped[str] = mapped_column(Text, default="")

    family: Mapped[Family | None] = relationship("Family", back_populates="investors")
    folios: Mapped[list[Folio]] = relationship(
        "Folio", back_populates="investor", cascade="all, delete-orphan"
    )
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction", back_populates="investor", cascade="all, delete-orphan"
    )
    holdings: Mapped[list[Holding]] = relationship(
        "Holding", back_populates="investor", cascade="all, delete-orphan"
    )
    daily_values: Mapped[list[InvestorValue]] = relationship(
        "InvestorValue", back_populates="investor", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uniq_investor_user_pan",
            "user_id",
            "pan_hash",
            unique=True,
            sqlite_where=(pan_hash != ""),
            postgresql_where=(pan_hash != ""),
        ),
    )


class Folio(Base, TimeStampedMixin):
    """An investment account or mutual fund folio."""

    __tablename__ = "folios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folio_type: Mapped[str] = mapped_column(String(16), default="mf")  # mf, demat
    number: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    broker: Mapped[str] = mapped_column(String(64), default="")
    amc_code: Mapped[str] = mapped_column(String(32), default="")
    pan_kyc: Mapped[bool] = mapped_column(Boolean, default=False)

    investor: Mapped[Investor] = relationship("Investor", back_populates="folios")
    transactions: Mapped[list[Transaction]] = relationship(
        "Transaction", back_populates="folio"
    )
    holdings: Mapped[list[Holding]] = relationship("Holding", back_populates="folio")

    __table_args__ = (
        UniqueConstraint(
            "investor_id", "number", "amc_code", name="uniq_folio_inv_number_amc"
        ),
    )


class Transaction(Base, TimeStampedMixin):
    """An immutable financial ledger entry (input to FIFO and XIRR)."""

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    transaction_type: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False
    )
    units: Mapped[Decimal] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=False
    )
    nav_or_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=False
    )
    amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2, asdecimal=True), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    fx_rate_to_inr: Mapped[Decimal] = mapped_column(
        Numeric(18, 6, asdecimal=True), default=Decimal("1")
    )
    fees: Mapped[Decimal] = mapped_column(
        Numeric(20, 2, asdecimal=True), default=Decimal("0")
    )
    stamp_duty: Mapped[Decimal] = mapped_column(
        Numeric(20, 2, asdecimal=True), default=Decimal("0")
    )
    brokerage: Mapped[Decimal] = mapped_column(
        Numeric(20, 2, asdecimal=True), default=Decimal("0")
    )
    cost_total: Mapped[Decimal | None] = mapped_column(
        Numeric(22, 4, asdecimal=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), default="cas_pdf")
    source_ref: Mapped[str] = mapped_column(String(128), default="")
    narration: Mapped[str] = mapped_column(Text, default="")
    dedup_key: Mapped[str] = mapped_column(String(64), index=True, default="")
    cost_basis_complete: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    investor: Mapped[Investor] = relationship("Investor", back_populates="transactions")
    security: Mapped[Security] = relationship("Security", back_populates="transactions")
    folio: Mapped[Folio | None] = relationship("Folio", back_populates="transactions")

    __table_args__ = (
        Index(
            "uniq_txn_investor_dedup",
            "investor_id",
            "dedup_key",
            unique=True,
            sqlite_where=(dedup_key != ""),
            postgresql_where=(dedup_key != ""),
        ),
        Index("idx_txn_inv_sec_date", "investor_id", "security_id", "date"),
    )


class Holding(Base, TimeStampedMixin):
    """Observed snapshot of units from statements or demat holdings."""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    units: Mapped[Decimal] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=False
    )
    value_observed: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2, asdecimal=True), nullable=True
    )
    avg_cost_observed: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), default="cas_pdf")
    source_ref: Mapped[str] = mapped_column(String(128), default="")

    investor: Mapped[Investor] = relationship("Investor", back_populates="holdings")
    security: Mapped[Security] = relationship("Security", back_populates="holdings")
    folio: Mapped[Folio | None] = relationship("Folio", back_populates="holdings")

    __table_args__ = (
        UniqueConstraint(
            "investor_id",
            "security_id",
            "folio_id",
            "as_of_date",
            "source",
            name="uniq_holding_snapshot",
        ),
    )


class PartialBlock(Base, TimeStampedMixin):
    """A partial-history statement segment awaiting earlier statements to chain."""

    __tablename__ = "partial_blocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folios.id", ondelete="CASCADE"), nullable=True, index=True
    )
    opening_units: Mapped[Decimal] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=False
    )
    closing_units: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=True
    )
    statement_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "investor_id",
            "security_id",
            "folio_id",
            name="uniq_partialblock_inv_sec_folio",
        ),
    )


class InvestorValue(Base, TimeStampedMixin):
    """Contiguous daily net-worth point for an investor."""

    __tablename__ = "investor_values"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    invested_inr: Mapped[Decimal] = mapped_column(
        Numeric(20, 2, asdecimal=True), default=Decimal("0")
    )
    value_inr: Mapped[Decimal] = mapped_column(
        Numeric(20, 2, asdecimal=True), default=Decimal("0")
    )
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=False)

    investor: Mapped[Investor] = relationship("Investor", back_populates="daily_values")

    __table_args__ = (
        UniqueConstraint("investor_id", "date", name="uniq_investor_value_date"),
        Index("idx_investor_value_date", "investor_id", "date"),
    )


class AppliedCorporateAction(Base, TimeStampedMixin):
    """Corporate actions replayed over immutable trade ledger."""

    __tablename__ = "applied_corporate_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folio_id: Mapped[int | None] = mapped_column(
        ForeignKey("folios.id", ondelete="SET NULL"), nullable=True, index=True
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    counterparty_security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ex_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    unit_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    bonus_ratio_a: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bonus_ratio_b: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merger_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    units: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=True
    )
    price: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    dividend_per_share: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6, asdecimal=True), nullable=True
    )
    source_ref: Mapped[str] = mapped_column(String(128), default="")
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    security: Mapped[Security] = relationship("Security", foreign_keys=[security_id])
    counterparty_security: Mapped[Security | None] = relationship(
        "Security", foreign_keys=[counterparty_security_id]
    )

    __table_args__ = (
        Index("idx_applied_ca_inv_sec_date", "investor_id", "security_id", "ex_date"),
    )


class SecurityIntegrityStatus(Base, TimeStampedMixin):
    """Reconciliation state between raw trade ledger and statement holdings."""

    __tablename__ = "security_integrity_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    folio_id: Mapped[int] = mapped_column(
        ForeignKey("folios.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    tax_safe: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    units_from_transactions: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=True
    )
    units_from_holdings: Mapped[Decimal | None] = mapped_column(
        Numeric(24, 8, asdecimal=True), nullable=True
    )
    issues_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    ledger_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    snapshot_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    investor: Mapped[Investor] = relationship("Investor")
    security: Mapped[Security] = relationship("Security")
    folio: Mapped[Folio] = relationship("Folio")

    __table_args__ = (
        UniqueConstraint(
            "investor_id",
            "security_id",
            "folio_id",
            name="uniq_integrity_inv_sec_folio",
        ),
    )


class ImportJob(Base, TimeStampedMixin):
    """Status record of a statement import operation."""

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    source_ref: Mapped[str] = mapped_column(String(128), default="")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    quarantines: Mapped[list[ImportQuarantine]] = relationship(
        "ImportQuarantine",
        back_populates="import_job",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ImportQuarantine(Base, TimeStampedMixin):
    """Isolated invalid transaction blocks from statements set aside for audit."""

    __tablename__ = "import_quarantines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    import_job_id: Mapped[int] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    investor_id: Mapped[int] = mapped_column(
        ForeignKey("investors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), default="")
    security_name: Mapped[str] = mapped_column(String(255), default="")
    isin: Mapped[str] = mapped_column(String(20), default="")
    folio_number: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    import_job: Mapped[ImportJob] = relationship(
        "ImportJob", back_populates="quarantines"
    )


class SchemaVersion(Base):
    """Lightweight schema migration tracker."""

    __tablename__ = "_schema_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "Base",
    "SchemeReference",
    "ISINReference",
    "GrandfatheringNAV",
    "ReferenceMeta",
    "AMC",
    "Security",
    "NAVHistory",
    "CorporateActionReference",
    "FXRate",
    "Family",
    "Investor",
    "Folio",
    "Transaction",
    "Holding",
    "PartialBlock",
    "InvestorValue",
    "AppliedCorporateAction",
    "SecurityIntegrityStatus",
    "ImportJob",
    "ImportQuarantine",
    "SchemaVersion",
]
