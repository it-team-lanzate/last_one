"""Run backtest on a slice of cached data to get results quickly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from src.config import load_config
from src.backtest.engine import run_backtest
from src.storage.models import init_db, save_run, save_trades, save_equity

def main():
    config = load_config("configs/base.yaml")
    # Load last N bars from cache (faster than full range)
    cache_path = Path("data/cache/BTCUSDT_4h_2010-01-01_2025-12-31.parquet")
    if not cache_path.exists():
        print("No cache found. Run: python cli.py fetch-data")
        return
    df = pd.read_parquet(cache_path)
    df["open_time"] = pd.to_datetime(df["open_time"])
    df = df.sort_values("open_time").reset_index(drop=True)
    # Use last 8000 bars (wider history)
    n = min(8000, len(df))
    df = df.iloc[-n:].reset_index(drop=True)
    print(f"Running backtest on {len(df)} bars ({df['open_time'].iloc[0].date()} to {df['open_time'].iloc[-1].date()})")
    result = run_backtest(df, config, run_id=None)
    print(f"Squeeze ranges: {result.n_squeeze_ranges} | Trades: {result.n_trades} | Return: {result.total_return_pct:.2f}% | PF: {result.profit_factor:.2f} | DD: {result.max_drawdown_pct:.2f}%")
    if result.n_trades > 0:
        init_db("data/trading.db")
        run_id = save_run("backtest", result.start_date, result.end_date, result.config, db_path="data/trading.db")
        save_trades(run_id, result.trades, db_path="data/trading.db")
        save_equity(run_id, result.equity_curve, db_path="data/trading.db")
        print(f"Saved run_id={run_id}. View in dashboard: streamlit run src/dashboard/app.py")
    else:
        print("No trades. Check squeeze_mode and squeeze_min_bars in configs/base.yaml")

if __name__ == "__main__":
    main()
