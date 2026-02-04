"""
Fees and slippage (taker).
fee_rate_side default 0.0006 (0.06%), slippage_side default 0.0002 (0.02%).
entry_fill = entry * (1 + slippage_side), exit_fill = exit * (1 - slippage_side).
Commission on notional per side.
Stress mode: double fees and slippage from config.
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class FeeSlippageParams:
    fee_rate_side: float
    slippage_side: float

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "FeeSlippageParams":
        fees = config.get("fees", {})
        fee = fees.get("fee_rate_side", 0.0006)
        slip = fees.get("slippage_side", 0.0002)
        if fees.get("stress_mode", False):
            fee *= 2
            slip *= 2
        return cls(fee_rate_side=fee, slippage_side=slip)


def fee_slippage_params(config: dict[str, Any]) -> FeeSlippageParams:
    return FeeSlippageParams.from_config(config)


def apply_fees_slippage(
    entry_price: float,
    exit_price: float,
    qty: float,
    params: FeeSlippageParams,
) -> tuple[float, float, float, float]:
    """
    Returns (entry_fill, exit_fill, fee_entry, fee_exit).
    entry_fill = entry * (1 + slippage_side)
    exit_fill = exit * (1 - slippage_side)
    fee = notional * fee_rate_side per side.
    """
    entry_fill = entry_price * (1 + params.slippage_side)
    exit_fill = exit_price * (1 - params.slippage_side)
    notional_entry = entry_fill * qty
    notional_exit = exit_fill * qty
    fee_entry = notional_entry * params.fee_rate_side
    fee_exit = notional_exit * params.fee_rate_side
    return entry_fill, exit_fill, fee_entry, fee_exit
