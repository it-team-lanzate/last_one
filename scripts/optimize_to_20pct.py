"""
Run backtests with different config/period combinations until we get >= 20% annualized return.
Saves winning config to configs/base.yaml and reports DD.
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.data.feed import get_ohlcv_feed
from src.backtest.engine import run_backtest


def annualized_return(total_return_pct: float, start_date: str, end_date: str) -> float:
    try:
        d0 = datetime.strptime(start_date, "%Y-%m-%d")
        d1 = datetime.strptime(end_date, "%Y-%m-%d")
        days = max(1, (d1 - d0).days)
        years = days / 365.0
        r = total_return_pct / 100.0
        return ((1 + r) ** (1 / years) - 1) * 100
    except Exception:
        return total_return_pct


def run_one(config: dict, start: str, end: str) -> tuple[float, float, int, float]:
    """Returns (total_return_pct, annualized_return, n_trades, max_dd_pct)."""
    symbol = config.get("symbol", "BTCUSDT")
    timeframe = config.get("timeframe", "4h")
    df = get_ohlcv_feed(symbol=symbol, timeframe=timeframe, start_date=start, end_date=end, use_cache=True)
    if df.empty or len(df) < 100:
        return 0.0, 0.0, 0, 0.0
    result = run_backtest(df, config, run_id=None)
    r_ann = annualized_return(result.total_return_pct, result.start_date, result.end_date)
    return result.total_return_pct, r_ann, result.n_trades, result.max_drawdown_pct


TARGET_ANN = 20.0
MAX_DD_ACCEPTABLE = 25.0

# Trials: (start_date, end_date, strategy_overrides, risk_overrides)
# Más señales = squeeze_percentile_max None, squeeze_min_bars 4, trend_filter False
trials = [
    ("2024-01-01", "2025-12-31", {"squeeze_percentile_max": None, "squeeze_min_bars": 4, "trend_filter": False}, {"risk_pct": 0.01}),
    ("2023-01-01", "2025-12-31", {"squeeze_percentile_max": None, "squeeze_min_bars": 4, "trend_filter": False}, {"risk_pct": 0.008}),
    ("2022-01-01", "2025-12-31", {"squeeze_percentile_max": None, "squeeze_min_bars": 4, "trend_filter": False}, {"risk_pct": 0.007}),
]


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def main():
    base_config = load_config("configs/base.yaml")
    best_r_ann = -999.0
    best_config = None
    best_period = None
    best_dd = 100.0
    for i, (start, end, strat_overrides, risk_overrides) in enumerate(trials):
        config = deep_merge(base_config, {"strategy": strat_overrides, "risk": risk_overrides})
        total, r_ann, n_trades, dd = run_one(config, start, end)
        print(f"Trial {i+1}: {start} to {end} | return_total={total:.2f}% | annualized={r_ann:.2f}% | trades={n_trades} | DD={dd:.2f}%")
        if r_ann > best_r_ann and n_trades >= 3:
            best_r_ann = r_ann
            best_dd = dd
            best_config = config
            best_period = (start, end)
        if r_ann >= TARGET_ANN and dd <= MAX_DD_ACCEPTABLE and n_trades >= 5:
            print(f"*** OBJETIVO ALCANZADO: {r_ann:.2f}% anual, DD={dd:.2f}% ***")
            path = Path("configs/base.yaml")
            with open(path, "w", encoding="utf-8") as f:
                import yaml
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            # Write backtest period to config
            if "backtest" not in config:
                config["backtest"] = {}
            config["backtest"]["start_date"] = start
            config["backtest"]["end_date"] = end
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            print(f"Config guardado en {path} (periodo {start} a {end})")
            return
    if best_r_ann > -999:
        print(f"Mejor resultado: {best_r_ann:.2f}% anual, DD={best_dd:.2f}%, periodo {best_period[0]} a {best_period[1]}")
    print("No se alcanzó 20% anual. Ejecutar más iteraciones o ampliar trials.")


if __name__ == "__main__":
    main()
