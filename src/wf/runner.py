"""
Walk-forward: sliding windows (train_days, test_days, step_days).
Run backtest on each test window and collect metrics per window.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest.engine import run_backtest, BacktestResult
from src.data.feed import get_ohlcv_feed


@dataclass
class WFWindowResult:
    window_start: str
    window_end: str
    n_trades: int
    total_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    result: BacktestResult


@dataclass
class WFResult:
    run_id: int | None = None
    config: dict[str, Any] = field(default_factory=dict)
    windows: list[WFWindowResult] = field(default_factory=list)
    # Aggregated (e.g. mean) across windows for dashboard
    mean_return_pct: float = 0.0
    mean_pf: float = 0.0
    mean_dd_pct: float = 0.0
    mean_win_rate: float = 0.0


def run_walk_forward(
    config: dict[str, Any],
    run_id: int | None = None,
    cache_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    start_date_override: str | None = None,
    end_date_override: str | None = None,
) -> WFResult:
    """
    Run walk-forward: sliding windows (train_days, test_days, step_days).
    Uses test window for backtest (no train/optimize in this version).
    """
    wf = config.get("walk_forward", {})
    train_days = int(wf.get("train_days", 180))
    test_days = int(wf.get("test_days", 30))
    step_days = int(wf.get("step_days", 30))
    symbol = config.get("symbol", "BTCUSDT")
    timeframe = config.get("timeframe", "4h")
    bt = config.get("backtest", {})
    initial_capital = float(bt.get("initial_capital", 10000.0))

    # Get full date range: CLI overrides > config
    start_date = start_date_override or bt.get("start_date") or config.get("backtest", {}).get("start_date") or "2023-01-01"
    end_date = end_date_override or bt.get("end_date") or config.get("backtest", {}).get("end_date") or "2024-12-31"

    df_full = get_ohlcv_feed(
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        cache_dir=cache_dir or "data/cache",
        use_cache=True,
    )
    if df_full.empty or len(df_full) < test_days * (24 // 4):  # 4H -> 6 bars/day, test_days need at least test_days*6 bars
        return WFResult(run_id=run_id, config=config)

    df_full["open_time"] = pd.to_datetime(df_full["open_time"])
    df_full = df_full.sort_values("open_time").reset_index(drop=True)
    t_min = df_full["open_time"].min()
    t_max = df_full["open_time"].max()
    step = pd.Timedelta(days=step_days)
    test_len = pd.Timedelta(days=test_days)

    windows: list[WFWindowResult] = []
    window_start = t_min
    while window_start + test_len <= t_max:
        window_end = window_start + test_len
        mask = (df_full["open_time"] >= window_start) & (df_full["open_time"] < window_end)
        df_window = df_full.loc[mask].copy()
        if len(df_window) < 30:
            window_start += step
            continue
        # Run backtest on this window (same config, different date slice)
        window_config = dict(config)
        if "backtest" not in window_config:
            window_config["backtest"] = {}
        window_config["backtest"] = dict(window_config["backtest"], start_date=window_start.strftime("%Y-%m-%d"), end_date=(window_end - pd.Timedelta(days=1)).strftime("%Y-%m-%d"), initial_capital=initial_capital)
        res = run_backtest(df_window, window_config, run_id=None)
        wr = WFWindowResult(
            window_start=window_start.strftime("%Y-%m-%d"),
            window_end=(window_end - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            n_trades=res.n_trades,
            total_return_pct=res.total_return_pct,
            profit_factor=res.profit_factor,
            max_drawdown_pct=res.max_drawdown_pct,
            win_rate=res.win_rate,
            result=res,
        )
        windows.append(wr)
        window_start += step

    if not windows:
        return WFResult(run_id=run_id, config=config)

    mean_return = sum(w.total_return_pct for w in windows) / len(windows)
    _pf_cap = 99.0  # ventanas sin pérdidas dan PF=inf; cap para media interpretable
    mean_pf = sum(min(w.profit_factor, _pf_cap) for w in windows) / len(windows)
    mean_dd = sum(w.max_drawdown_pct for w in windows) / len(windows)
    mean_wr = sum(w.win_rate for w in windows) / len(windows)

    return WFResult(
        run_id=run_id,
        config=config,
        windows=windows,
        mean_return_pct=mean_return,
        mean_pf=mean_pf,
        mean_dd_pct=mean_dd,
        mean_win_rate=mean_wr,
    )
