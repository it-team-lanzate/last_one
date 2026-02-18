"""
Optimiza retorno manteniendo DD <= baseline (o +5% tolerancia).
Grid search sobre tp1_r, chandelier_atr_mult, quality_filter_tr_mult.
Uso: python optimize_return_dd_constraint.py [--quick]
"""
import sys
from pathlib import Path
from datetime import datetime
from itertools import product

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def run_one(config: dict, start: str, end: str) -> tuple[float, float, int, float, float]:
    """Returns (total_return_pct, r_ann, n_trades, max_dd_pct, final_equity)."""
    symbol = config.get("symbol", "BTCUSDT")
    timeframe = config.get("timeframe", "4h")
    df = get_ohlcv_feed(symbol=symbol, timeframe=timeframe, start_date=start, end_date=end, use_cache=True)
    if df.empty or len(df) < 100:
        return 0.0, 0.0, 0, 0.0, 0.0
    result = run_backtest(df, config, run_id=None)
    r_ann = annualized_return(result.total_return_pct, result.start_date, result.end_date)
    return result.total_return_pct, r_ann, result.n_trades, result.max_drawdown_pct, result.final_equity


# LONG: grid reducido - parámetros que suben retorno sin subir DD
LONG_GRID = {
    "tp1_r": [1.75, 2.0],
    "chandelier_atr_mult": [2.2, 2.5],
    "quality_filter_tr_mult": [1.1, 1.15],
}

# SHORT
SHORT_GRID = {
    "tp1_r": [2.25, 2.5],
    "chandelier_atr_mult": [2.2, 2.5],
    "quality_filter_tr_mult": [1.1, 1.15],
}


LOG_FILE = None  # set in main to capture output


def _log(s: str) -> None:
    print(s)
    if LOG_FILE:
        LOG_FILE.write(s + "\n")
        LOG_FILE.flush()


def optimize_strategy(config_path: str, label: str, start: str, end: str, dd_tolerance_pct: float = 5.0, quick: bool = False) -> dict | None:
    config = load_config(config_path)
    strat = config.get("strategy", {})

    # Baseline
    _log(f"\n=== {label} | baseline ===")
    base_total, base_ann, base_trades, base_dd, base_eq = run_one(config, start, end)
    _log(f"  return={base_total:.2f}% | ann={base_ann:.2f}% | trades={base_trades} | DD={base_dd:.2f}% | eq={base_eq:,.0f}")
    dd_max = base_dd * (1 + dd_tolerance_pct / 100) if base_dd > 0 else 5.0

    grid = LONG_GRID if "direction" not in strat or strat.get("direction") != "short" else SHORT_GRID
    if quick:
        combos = [
            {"tp1_r": grid["tp1_r"][0], "chandelier_atr_mult": grid["chandelier_atr_mult"][0], "quality_filter_tr_mult": 1.1},
            {"tp1_r": grid["tp1_r"][-1], "chandelier_atr_mult": grid["chandelier_atr_mult"][-1], "quality_filter_tr_mult": 1.1},
        ]
    else:
        keys = list(grid.keys())
        values = list(grid.values())
        combos = [dict(zip(keys, c)) for c in product(*values)]

    best = None
    best_ann = base_ann
    results = []

    for overrides in combos:
        cfg = deep_merge(config, {"strategy": dict(strat, **overrides)})
        total, r_ann, n_trades, dd, eq = run_one(cfg, start, end)

        if dd <= dd_max and n_trades >= 10:
            results.append((r_ann, total, dd, n_trades, eq, overrides))
            if r_ann > best_ann:
                best_ann = r_ann
                best = (r_ann, total, dd, n_trades, eq, overrides)

    results.sort(key=lambda x: -x[0])

    _log(f"\n--- Top 10 (DD <= {dd_max:.2f}%) ---")
    for i, (r_ann, total, dd, n_trades, eq, overrides) in enumerate(results[:10], 1):
        delta = r_ann - base_ann
        _log(f"  #{i} ann={r_ann:.2f}% ({delta:+.2f}) | return={total:.2f}% | DD={dd:.2f}% | trades={n_trades} | {overrides}")

    if best:
        _log(f"\n*** Mejor: ann={best[0]:.2f}% (+{best[0]-base_ann:.2f} vs baseline) | DD={best[2]:.2f}% ***")
        _log(f"    Overrides: {best[5]}")
        return best
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Solo 2 combos por estrategia (rápido)")
    args = ap.parse_args()

    start, end = "2020-01-01", "2025-12-31"
    out_path = Path("data/optimize_results.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        global LOG_FILE
        LOG_FILE = f
        best_long = optimize_strategy("configs/base.yaml", "LONG", start, end, quick=args.quick)
        best_short = optimize_strategy("configs/base_short.yaml", "SHORT", start, end, quick=args.quick)

        _log("\n" + "=" * 60)
        _log("RESUMEN OPTIMIZACIÓN")
        if best_long:
            _log(f"LONG mejor:  ann={best_long[0]:.2f}% | DD={best_long[2]:.2f}% | {best_long[5]}")
        if best_short:
            _log(f"SHORT mejor: ann={best_short[0]:.2f}% | DD={best_short[2]:.2f}% | {best_short[5]}")

    print(f"Resultados en {out_path}")


if __name__ == "__main__":
    main()
