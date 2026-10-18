"""Folioman database module: models, engine, and migrations."""

from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.errors import (
    DatabaseErrorInfo,
    analyze_db_error,
    format_database_error,
    handle_db_errors,
    report_database_error,
    translate_integrity_error,
    translate_operational_error,
)
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
    SchemaVersion,
    SchemeReference,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)

__all__ = [
    # Securities & Market Data
    "AMC",
    "CURRENT_SCHEMA_VERSION",
    "AppliedCorporateAction",
    "Base",
    "CorporateActionReference",
    "DatabaseErrorInfo",
    "FXRate",
    # Portfolio Ledger
    "Family",
    "Folio",
    "GrandfatheringNAV",
    "Holding",
    "ISINReference",
    # Auditing & Versioning
    "ImportJob",
    "ImportQuarantine",
    "Investor",
    "InvestorValue",
    "NAVHistory",
    "PartialBlock",
    "ReferenceMeta",
    "SchemaVersion",
    # Reference dictionary
    "SchemeReference",
    "Security",
    "SecurityIntegrityStatus",
    "Transaction",
    "analyze_db_error",
    "create_folioman_engine",
    "create_sessionmaker",
    "format_database_error",
    "get_schema_version",
    "handle_db_errors",
    "init_schema",
    "report_database_error",
    "translate_integrity_error",
    "translate_operational_error",
]
