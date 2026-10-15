"""Folioman database module: models, engine, and migrations."""

from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.errors import handle_db_errors, translate_integrity_error
from folioman_client.db.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_schema_version,
    init_schema,
)
from folioman_client.db.models import (
    AMC,
    AppliedCorporateAction,
    Base,
    CorporateActionReference,
    Family,
    Folio,
    FXRate,
    GrandfatheringNAV,
    Holding,
    ImportJob,
    ImportQuarantine,
    Investor,
    InvestorValue,
    ISINReference,
    NAVHistory,
    PartialBlock,
    ReferenceMeta,
    SchemeReference,
    SchemaVersion,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)

__all__ = [
    "Base",
    "create_folioman_engine",
    "create_sessionmaker",
    "handle_db_errors",
    "translate_integrity_error",
    "init_schema",
    "get_schema_version",
    "CURRENT_SCHEMA_VERSION",
    # Reference dictionary
    "SchemeReference",
    "ISINReference",
    "GrandfatheringNAV",
    "ReferenceMeta",
    # Securities & Market Data
    "AMC",
    "Security",
    "NAVHistory",
    "CorporateActionReference",
    "FXRate",
    # Portfolio Ledger
    "Family",
    "Investor",
    "Folio",
    "Transaction",
    "Holding",
    "PartialBlock",
    "InvestorValue",
    "AppliedCorporateAction",
    "SecurityIntegrityStatus",
    # Auditing & Versioning
    "ImportJob",
    "ImportQuarantine",
    "SchemaVersion",
]
