"""
Tuning rápido para SHORT: prueba combinaciones de parámetros clave.
Ejecutar: python scripts/dev/tune_short.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import copy
from src.config import load_config
from src.data.feed import get_ohlcv_feed
from src.backtest.engine import run_backtest

config = load_config("configs/base_short.yaml")

# Rango 2021-2025 para screening rápido (~10k barras)
START, END = "2021-01-01", "2025-12-31"
config["backtest"]["start_date"] = START
config["backtest"]["end_date"] = END

print("Cargando datos...")
df = get_ohlcv_feed(symbol="BTCUSDT", timeframe="4h", start_date=START, end_date=END)
print(f"Data: {len(df)} bars, {df['open_time'].iloc[0]} to {df['open_time'].iloc[-1]}")

params_grid = [
    {"label": "BASELINE", "changes": {}},
    {"label": "trend_50", "changes": {"strategy.trend_period": 50}},
    {"label": "trend_75", "changes": {"strategy.trend_period": 75}},
    {"label": "trend_150", "changes": {"strategy.trend_period": 150}},
    {"label": "no_trend", "changes": {"strategy.trend_filter": False}},
    {"label": "chand_15", "changes": {"strategy.chandelier_lookback": 15}},
    {"label": "chand_20", "changes": {"strategy.chandelier_lookback": 20}},
    {"label": "chand_mult_1.5", "changes": {"strategy.chandelier_atr_mult": 1.5}},
    {"label": "chand_mult_2.5", "changes": {"strategy.chandelier_atr_mult": 2.5}},
    {"label": "chand_mult_3.0", "changes": {"strategy.chandelier_atr_mult": 3.0}},
    {"label": "tstop_8", "changes": {"strategy.time_stop_bars": 8}},
    {"label": "tstop_10", "changes": {"strategy.time_stop_bars": 10}},
    {"label": "tstop_20", "changes": {"strategy.time_stop_bars": 20}},
    {"label": "trail_act_0.3", "changes": {"strategy.trail_activation_r": 0.3}},
    {"label": "trail_act_0.0", "changes": {"strategy.trail_activation_r": 0.0}},
    {"label": "tp1_1.0", "changes": {"strategy.tp1_r": 1.0}},
    {"label": "tp1_2.0", "changes": {"strategy.tp1_r": 2.0}},
    {"label": "tp1_pct_0.5", "changes": {"strategy.tp1_close_pct": 0.5}},
    {"label": "sqz_min3", "changes": {"strategy.squeeze_min_bars": 3}},
    {"label": "sqz_pctile30", "changes": {"strategy.squeeze_percentile_max": 30}},
    {"label": "stop_atr_2.0", "changes": {"strategy.stop_entry_atr_mult": 2.0}},
    {"label": "min_r_0.3", "changes": {"strategy.min_r_atr_mult": 0.3}},
    {"label": "COMBO1", "changes": {
        "strategy.trend_period": 150, "strategy.chandelier_atr_mult": 2.5,
        "strategy.time_stop_bars": 10, "strategy.trail_activation_r": 0.3,
    }},
    {"label": "COMBO2", "changes": {
        "strategy.trend_period": 50, "strategy.chandelier_lookback": 20,
        "strategy.chandelier_atr_mult": 2.5, "strategy.time_stop_bars": 12,
        "strategy.trail_activation_r": 0.3, "strategy.tp1_r": 1.0,
    }},
    {"label": "COMBO3", "changes": {
        "strategy.trend_period": 150, "strategy.chandelier_lookback": 20,
        "strategy.chandelier_atr_mult": 3.0, "strategy.time_stop_bars": 20,
        "strategy.trail_activation_r": 0.5, "strategy.tp1_r": 2.0,
        "strategy.tp1_close_pct": 0.3,
    }},
    {"label": "COMBO4", "changes": {
        "strategy.trend_period": 75, "strategy.chandelier_lookback": 20,
        "strategy.chandelier_atr_mult": 2.0, "strategy.time_stop_bars": 12,
        "strategy.trail_activation_r": 0.3, "strategy.squeeze_min_bars": 3,
    }},
]

def apply_changes(cfg, changes):
    c = copy.deepcopy(cfg)
    for key, val in changes.items():
        parts = key.split(".")
        d = c
        for p in parts[:-1]:
            d = d[p]
        d[parts[-1]] = val
    return c

hdr = f"{'Label':<25} {'Ret%':>7} {'Ann%':>7} {'Trd':>5} {'PF':>6} {'DD%':>6} {'WR%':>6}"
print(f"\n{hdr}")
print("-" * 70)

results = []
for p in params_grid:
    cfg = apply_changes(config, p["changes"])
    try:
        res = run_backtest(df.copy(), cfg)
        days = max((df["open_time"].iloc[-1] - df["open_time"].iloc[0]).days, 1)
        ann = ((1 + res.total_return_pct / 100) ** (365.25 / days) - 1) * 100
        line = f"{p['label']:<25} {res.total_return_pct:>7.1f} {ann:>7.2f} {res.n_trades:>5} {res.profit_factor:>6.2f} {res.max_drawdown_pct:>6.2f} {res.win_rate:>6.1f}"
        print(line, flush=True)
        results.append((p["label"], res.total_return_pct, ann, res.n_trades, res.profit_factor, res.max_drawdown_pct, res.win_rate))
    except Exception as e:
        print(f"{p['label']:<25} ERROR: {e}", flush=True)

print("\n=== Top 5 por retorno anualizado ===")
results.sort(key=lambda x: x[2], reverse=True)
for r in results[:5]:
    print(f"  {r[0]:<25} Ann={r[2]:.2f}%  Ret={r[1]:.1f}%  PF={r[4]:.2f}  DD={r[5]:.2f}%  T={r[3]}")

print("\n=== Top 5 por PF (mín 50 trades) ===")
f = sorted([r for r in results if r[3] >= 50], key=lambda x: x[4], reverse=True)
for r in f[:5]:
    print(f"  {r[0]:<25} PF={r[4]:.2f}  Ann={r[2]:.2f}%  DD={r[5]:.2f}%  T={r[3]}")

print("\n=== Top 5 menor DD (mín 50 trades, ann>5%) ===")
f2 = sorted([r for r in results if r[3] >= 50 and r[2] > 5], key=lambda x: x[5])
for r in f2[:5]:
    print(f"  {r[0]:<25} DD={r[5]:.2f}%  Ann={r[2]:.2f}%  PF={r[4]:.2f}  T={r[3]}")

print("\nDone.")
