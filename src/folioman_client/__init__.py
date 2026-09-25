"""Folioman API Client Package.

Official typed asynchronous Python SDK for the Folioman REST API.
"""

from __future__ import annotations

from folioman_client.auth import EXP_SKEW_SECONDS, JWTAuthManager
from folioman_client.client import (
    CapitalGainsResource,
    FoliomanClient,
    HoldingsResource,
    InvestorsResource,
    PortfolioResource,
    TransactionsResource,
    ValuationsResource,
)
from folioman_client.config import FoliomanSettings, settings
from folioman_client.errors import (
    FoliomanAPIError,
    FoliomanAuthError,
    FoliomanError,
    FoliomanNotFoundError,
)
from folioman_client.models import (
    AccessToken,
    AllocationBucket,
    AssetMixRow,
    CapitalGainRow,
    CapitalGainsFyPoint,
    CapitalGainsReport,
    ConfiguredDate,
    ConfiguredDatetime,
    ConfiguredDecimal,
    FolioBalance,
    FoliomanBaseModel,
    Holding,
    Investor,
    InvestorDetail,
    NavPoint,
    PeriodReturn,
    PortfolioSummary,
    SchemeDetail,
    SchemeRef,
    TokenPair,
    Transaction,
    ValuationStatus,
    ValueSeries,
    ValueSeriesPoint,
)

__version__ = "0.1.0"

__all__ = [
    # Client & Resources
    "FoliomanClient",
    "InvestorsResource",
    "PortfolioResource",
    "HoldingsResource",
    "TransactionsResource",
    "ValuationsResource",
    "CapitalGainsResource",
    # Auth & Config
    "JWTAuthManager",
    "EXP_SKEW_SECONDS",
    "FoliomanSettings",
    "settings",
    # Errors
    "FoliomanError",
    "FoliomanAuthError",
    "FoliomanNotFoundError",
    "FoliomanAPIError",
    # Models
    "FoliomanBaseModel",
    "TokenPair",
    "AccessToken",
    "Investor",
    "InvestorDetail",
    "Holding",
    "SchemeRef",
    "NavPoint",
    "FolioBalance",
    "Transaction",
    "SchemeDetail",
    "AssetMixRow",
    "AllocationBucket",
    "PeriodReturn",
    "PortfolioSummary",
    "ValueSeriesPoint",
    "ValueSeries",
    "ValuationStatus",
    "CapitalGainRow",
    "CapitalGainsReport",
    "CapitalGainsFyPoint",
    # Types
    "ConfiguredDecimal",
    "ConfiguredDate",
    "ConfiguredDatetime",
]
