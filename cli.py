"""
CLI: fetch-data, backtest, walkforward, paper-live.
Config by YAML + .env for credentials.
"""
import argparse
import logging
from pathlib import Path

from src.config import load_config
from src.logging_config import setup_logging
from src.data.feed import get_ohlcv_feed
from src.backtest.engine import run_backtest
from src.wf.runner import run_walk_forward
from src.storage.models import init_db, save_run, save_trades, save_equity, save_wf_window

log = logging.getLogger(__name__)

DEFAULT_CONFIG = Path("configs/base.yaml")
DEFAULT_DB = Path("data/trading.db")


def _resolve_end_date(end: str) -> str:
    """If end is 'today' or 'now', return today's date (YYYY-MM-DD)."""
    if (end or "").lower() in ("today", "now", ""):
        from datetime import datetime
        return datetime.utcnow().strftime("%Y-%m-%d")
    return end


def cmd_fetch_data(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = config.get("symbol", "BTCUSDT")
    timeframe = config.get("timeframe", "4h")
    bt = config.get("backtest", config)
    start = getattr(args, "start_date", None) or bt.get("start_date") or config.get("backtest", {}).get("start_date") or "2020-01-01"
    end_raw = getattr(args, "end_date", None) or bt.get("end_date") or config.get("backtest", {}).get("end_date") or "2025-12-31"
    end = _resolve_end_date(end_raw)
    cache_dir = getattr(args, "cache_dir", None) or "data/cache"
    df = get_ohlcv_feed(symbol=symbol, timeframe=timeframe, start_date=start, end_date=end, cache_dir=cache_dir, use_cache=False)
    log.info("Fetched %d rows for %s %s (%s to %s)", len(df), symbol, timeframe, start, end)


def cmd_backtest(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = config.get("symbol", "BTCUSDT")
    timeframe = config.get("timeframe", "4h")
    bt = config.get("backtest", config)
    start = getattr(args, "start_date", None) or bt.get("start_date") or "2023-01-01"
    end = getattr(args, "end_date", None) or bt.get("end_date") or "2024-12-31"
    cache_dir = getattr(args, "cache_dir", None) or "data/cache"
    df = get_ohlcv_feed(symbol=symbol, timeframe=timeframe, start_date=start, end_date=end, cache_dir=cache_dir, use_cache=True)
    if df.empty:
        log.error("No data for backtest")
        return
    result = run_backtest(df, config, run_id=None)
    db_path = getattr(args, "db", None) or DEFAULT_DB
    init_db(db_path)
    run_id = save_run("backtest", result.start_date, result.end_date, result.config, db_path=db_path)
    save_trades(run_id, result.trades, db_path=db_path)
    save_equity(run_id, result.equity_curve, db_path=db_path)
    log.info("Backtest run_id=%s | return=%.2f%% (total) | trades=%s | PF=%.2f | DD=%.2f%%",
             run_id, result.total_return_pct, result.n_trades, result.profit_factor, result.max_drawdown_pct)
    if result.n_trades and result.n_trades <= 20:
        for k, t in enumerate(result.trades):
            log.info("  trade %s: pnl_net=%.2f R=%.2f reason=%s", k + 1, t.pnl_net, getattr(t, "r_realized", 0), getattr(t, "exit_reason", ""))
    if result.start_date and result.end_date:
        try:
            from datetime import datetime
            d0 = datetime.strptime(result.start_date, "%Y-%m-%d")
            d1 = datetime.strptime(result.end_date, "%Y-%m-%d")
            days = max(1, (d1 - d0).days)
            years = days / 365.0
            r_total = result.total_return_pct / 100.0
            r_ann = ((1 + r_total) ** (1 / years) - 1) * 100 if years > 0 else result.total_return_pct
            log.info("Period %s to %s (%.1f days) | annualized return ~%.2f%%", result.start_date, result.end_date, days, r_ann)
        except Exception:
            pass
    if result.n_trades == 0:
        cfg = getattr(result, "config", {}) or {}
        smb = cfg.get("strategy", {}).get("squeeze_min_bars", "?")
        log.info("No trades: data has %s bars, %s squeeze ranges (squeeze_min_bars=%s). "
                 "Try squeeze_mode: width and/or lower squeeze_min_bars in config.",
                 getattr(result, "n_bars", "?"), getattr(result, "n_squeeze_ranges", "?"), smb)


def cmd_walkforward(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    cache_dir = getattr(args, "cache_dir", None) or "data/cache"
    db_path = getattr(args, "db", None) or DEFAULT_DB
    start_date = getattr(args, "start_date", None)
    end_date = getattr(args, "end_date", None)
    wf_result = run_walk_forward(
        config, run_id=None, cache_dir=cache_dir, db_path=db_path,
        start_date_override=start_date, end_date_override=end_date,
    )
    if not wf_result.windows:
        log.warning("No WF windows produced")
        return
    init_db(db_path)
    bt = config.get("backtest", {})
    start = wf_result.windows[0].window_start
    end = wf_result.windows[-1].window_end
    run_id = save_run("walk_forward", start, end, config, db_path=db_path)
    for w in wf_result.windows:
        save_wf_window(
            run_id, w.window_start, w.window_end,
            w.n_trades, w.total_return_pct, w.profit_factor, w.max_drawdown_pct, w.win_rate,
            db_path=db_path,
        )
    log.info("Walk-forward run_id=%s | windows=%s | mean_return=%.2f%% | mean_PF=%.2f",
             run_id, len(wf_result.windows), wf_result.mean_return_pct, wf_result.mean_pf)


def cmd_weekly_report(args: argparse.Namespace) -> None:
    """Envía por Telegram el resumen semanal (últimos 7 días) desde paper_live_state.json."""
    from pathlib import Path
    from src.paper_live.runner import send_weekly_report_manual
    config = load_config(args.config)
    symbol = config.get("symbol", "BTCUSDT")
    state_path = Path(args.state) if getattr(args, "state", None) else None
    ok = send_weekly_report_manual(state_path=state_path, symbol=symbol)
    if ok:
        log.info("Resumen semanal enviado por Telegram")
    else:
        log.warning("No se pudo enviar (revisa TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env)")


def cmd_paper_live(args: argparse.Namespace) -> None:
    """Paper-trade: con --execute coloca órdenes reales en Binance Testnet; sin él, backtest hasta hoy."""
    if getattr(args, "execute", False):
        from src.paper_live.runner import run_live_loop
        config = load_config(args.config)
        pl = config.get("paper_live", {})
        poll = int(pl.get("poll_interval_seconds", 60))
        run_live_loop(args.config, poll_interval_seconds=poll)
        return
    config = load_config(args.config)
    log.info("Paper-live: simulando con datos hasta la fecha indicada. Sin órdenes reales.")
    symbol = config.get("symbol", "BTCUSDT")
    timeframe = config.get("timeframe", "4h")
    pl = config.get("paper_live", config.get("backtest", {}))
    start = getattr(args, "start_date", None) or pl.get("start_date") or "2024-01-01"
    end_raw = getattr(args, "end_date", None) or pl.get("end_date") or "today"
    end = _resolve_end_date(end_raw)
    cache_dir = getattr(args, "cache_dir", None) or "data/cache"
    df = get_ohlcv_feed(symbol=symbol, timeframe=timeframe, start_date=start, end_date=end, cache_dir=cache_dir, use_cache=True)
    if df.empty:
        log.error("No data for paper-live")
        return
    result = run_backtest(df, config, run_id=None)
    result.run_type = "paper_live"
    db_path = getattr(args, "db", None) or DEFAULT_DB
    init_db(db_path)
    run_id = save_run("paper_live", result.start_date, result.end_date, result.config, db_path=db_path)
    save_trades(run_id, result.trades, db_path=db_path)
    save_equity(run_id, result.equity_curve, db_path=db_path)
    log.info("Paper-live run_id=%s | return=%.2f%% | trades=%s", run_id, result.total_return_pct, result.n_trades)


def main() -> None:
    parser = argparse.ArgumentParser(description="BTCUSDT 4H Squeeze Breakout CLI")
    parser.add_argument("--config", "-c", default=str(DEFAULT_CONFIG), help="Config YAML path")
    parser.add_argument("--cache-dir", default="data/cache", help="OHLCV cache directory")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-dir", default=None, help="Log directory for rotation")
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p):
        p.add_argument("--config", "-c", default=str(DEFAULT_CONFIG), help="Config YAML path")
        p.add_argument("--cache-dir", default="data/cache", help="OHLCV cache directory")
        p.add_argument("--db", default=str(DEFAULT_DB), help="SQLite DB path")

    p_fetch = sub.add_parser("fetch-data")
    _add_common(p_fetch)
    p_fetch.add_argument("--start-date", default=None, help="Start date YYYY-MM-DD (overrides config)")
    p_fetch.add_argument("--end-date", default=None, help="End date YYYY-MM-DD or 'today' for up to now (overrides config)")
    p_fetch.set_defaults(func=cmd_fetch_data)

    p_bt = sub.add_parser("backtest")
    _add_common(p_bt)
    p_bt.add_argument("--start-date", default=None, help="Override backtest start YYYY-MM-DD")
    p_bt.add_argument("--end-date", default=None, help="Override backtest end YYYY-MM-DD")
    p_bt.set_defaults(func=cmd_backtest)

    p_wf = sub.add_parser("walkforward")
    _add_common(p_wf)
    p_wf.add_argument("--start-date", default=None, help="WF range start YYYY-MM-DD (overrides config)")
    p_wf.add_argument("--end-date", default=None, help="WF range end YYYY-MM-DD (overrides config)")
    p_wf.set_defaults(func=cmd_walkforward)

    p_pl = sub.add_parser("paper-live")
    _add_common(p_pl)
    p_pl.add_argument("--start-date", default=None, help="Inicio del paper trade YYYY-MM-DD (sin --execute)")
    p_pl.add_argument("--end-date", default=None, help="Fin YYYY-MM-DD o 'today' (sin --execute)")
    p_pl.add_argument("--execute", action="store_true", help="Ejecutar órdenes reales en Binance Futures Testnet")
    p_pl.set_defaults(func=cmd_paper_live)

    p_weekly = sub.add_parser("weekly-report")
    _add_common(p_weekly)
    p_weekly.add_argument("--state", default=None, help="Ruta a paper_live_state.json (default: data/paper_live_state.json)")
    p_weekly.set_defaults(func=cmd_weekly_report)

    args = parser.parse_args()
    setup_logging(level=args.log_level, log_dir=args.log_dir)
    args.func(args)


if __name__ == "__main__":
    main()
