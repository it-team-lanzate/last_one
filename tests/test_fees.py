"""Unit tests: fees and slippage application."""
import pytest

from src.execution.fees import (
    FeeSlippageParams,
    apply_fees_slippage,
    fee_slippage_params,
)


def test_apply_fees_slippage_entry_exit_fill():
    params = FeeSlippageParams(fee_rate_side=0.0006, slippage_side=0.0002)
    entry_price = 100.0
    exit_price = 102.0
    qty = 10.0
    entry_fill, exit_fill, fee_entry, fee_exit = apply_fees_slippage(
        entry_price, exit_price, qty, params
    )
    assert entry_fill == entry_price * (1 + params.slippage_side)
    assert entry_fill == 100.0 * 1.0002
    assert exit_fill == exit_price * (1 - params.slippage_side)
    assert exit_fill == 102.0 * 0.9998
    assert fee_entry == entry_fill * qty * params.fee_rate_side
    assert fee_exit == exit_fill * qty * params.fee_rate_side


def test_stress_mode_doubles_fees_and_slippage():
    config = {
        "fees": {
            "fee_rate_side": 0.0006,
            "slippage_side": 0.0002,
            "stress_mode": True,
        }
    }
    params = fee_slippage_params(config)
    assert params.fee_rate_side == 0.0012
    assert params.slippage_side == 0.0004
