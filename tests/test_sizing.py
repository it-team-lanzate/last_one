"""Unit tests: R and position sizing."""
import pytest

from src.execution.paper_broker import size_position


def test_size_position_basic():
    risk_pct = 0.01
    capital = 10000.0
    entry_fill = 100.0
    stop = 98.0
    qty = size_position(risk_pct, capital, entry_fill, stop)
    risk_usd = capital * risk_pct  # 100
    r_dist = entry_fill - stop   # 2
    expected = risk_usd / r_dist  # 50
    assert abs(qty - expected) < 1e-6
    assert qty == 50.0


def test_size_position_zero_r():
    qty = size_position(0.01, 10000.0, 100.0, 100.0)
    assert qty == 0.0 or qty < 1e-9


def test_r_value():
    entry = 50000.0
    stop = 49000.0
    r_value = entry - stop
    assert r_value == 1000.0
    # +1R = entry + 1000 = 51000
    assert entry + r_value == 51000.0
