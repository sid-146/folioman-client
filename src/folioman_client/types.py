"""Reusable Pydantic Annotated types for Folioman models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

ConfiguredDecimal = Annotated[
    Decimal,
    PlainSerializer(lambda x: float(x), return_type=float, when_used="unless-none"),
]
"""Decimal type serialized to float unless None."""

ConfiguredDate = Annotated[
    date,
    PlainSerializer(lambda x: x.isoformat(), return_type=str, when_used="unless-none"),
]
"""Date type serialized to ISO-8601 string (YYYY-MM-DD) unless None."""

ConfiguredDatetime = Annotated[
    datetime,
    PlainSerializer(lambda x: x.isoformat(), return_type=str, when_used="unless-none"),
]
"""Datetime type serialized to ISO-8601 string unless None."""

__all__ = [
    "ConfiguredDecimal",
    "ConfiguredDate",
    "ConfiguredDatetime",
]
