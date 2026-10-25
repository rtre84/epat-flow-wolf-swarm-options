"""Strict data contract for everything downstream.

An LLM cannot hand the executor anything that is not a valid TradeSpec.
Phase 4's IBridgePy executor trusts this schema and only this schema.
"""
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Strategy(str, Enum):
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    BULL_PUT_SPREAD = "bull_put_spread"
    BEAR_CALL_SPREAD = "bear_call_spread"
    BULL_CALL_SPREAD = "bull_call_spread"
    BEAR_PUT_SPREAD = "bear_put_spread"


class SpecStatus(str, Enum):
    PENDING_BACKTEST = "pending_backtest"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


class TradeSpec(BaseModel):
    trade_id: str = Field(description="date_ticker, e.g. 2026-10-25_TSLA")
    scan_date: date
    underlying: str = Field(min_length=1, max_length=8)
    strategy: Strategy = Field(description="defined-risk strategies only")
    expiry: str = Field(description="e.g. weekly, monthly, or ISO date")
    max_risk_usd: float = Field(gt=0, le=300, description="max loss per spec")
    entry_trigger: str = Field(min_length=1)
    invalidation: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=10)
    signals: list[str] = Field(min_length=1)
    backtest_gate: SpecStatus = SpecStatus.PENDING_BACKTEST

    @field_validator("trade_id")
    @classmethod
    def check_id_format(cls, v: str) -> str:
        if "_" not in v or len(v.split("_")) != 2:
            raise ValueError("trade_id must be YYYY-MM-DD_TICKER")
        return v
