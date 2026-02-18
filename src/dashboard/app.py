"""
Streamlit dashboard: Live Monitor, Runs list, Run detail, Walk-forward.
Uses Plotly for interactive charts.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

from src.storage.models import (
    init_db,
    get_runs,
    get_run,
    get_trades,
    get_equity,
    get_wf_windows,
    DEFAULT_DB_PATH,
)

st.set_page_config(page_title="Squeeze Breakout 4H", layout="wide")
DB_PATH = Path("data/trading.db")
STATE_LONG = Path("data/paper_live_state.json")
STATE_SHORT = Path("data/paper_live_state_short.json")
init_db(DB_PATH)

STALE_MINUTES = 6  # Si last_heartbeat > 6 min → runner probablemente caído


def _load_live_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _heartbeat_status(heartbeat_str: str | None) -> tuple[str, str]:
    """Retorna (emoji, label): running, stale, unknown."""
    if not heartbeat_str:
        return "⚫", "Desconocido"
    try:
        ts = datetime.fromisoformat(heartbeat_str.replace("Z", "+00:00"))
        ts_naive = ts.replace(tzinfo=None) if ts.tzinfo else ts
        delta = datetime.utcnow() - ts_naive
        mins = delta.total_seconds() / 60
    except Exception:
        return "⚫", "Desconocido"
    if mins < STALE_MINUTES:
        return "🟢", f"Activo ({mins:.0f} min)"
    return "🟡", f"Stale ({mins:.0f} min)"


def _load_last_bars(symbol: str = "BTCUSDT", timeframe: str = "4h", days: int = 30) -> pd.DataFrame:
    """Carga las últimas N días de OHLCV para el gráfico."""
    try:
        from src.data.feed import get_ohlcv_feed
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        df = get_ohlcv_feed(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            use_cache=True,
        )
        return df if df is not None and not df.empty else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def page_live_monitor() -> None:
    st.title("Live Monitor")
    st.caption("Estado de los runners LONG y SHORT en paper-live (Bybit Testnet)")

    if st_autorefresh:
        st_autorefresh(interval=60 * 1000, key="livemonitor")
    else:
        if st.button("🔄 Refrescar"):
            st.rerun()

    state_long = _load_live_state(STATE_LONG)
    state_short = _load_live_state(STATE_SHORT)

    # --- Resumen estado de cuenta ---
    st.subheader("Resumen estado de cuenta")
    bal_long = state_long.get("balance_usdt")
    bal_short = state_short.get("balance_usdt")
    bal = bal_long if bal_long is not None else bal_short
    if bal is not None:
        bal = float(bal)
    pnl_long = sum(t.get("pnl_net", 0) for t in state_long.get("closed_trades", []))
    pnl_short = sum(t.get("pnl_net", 0) for t in state_short.get("closed_trades", []))
    initial = 10000.0
    ret_pct = ((bal - initial) / initial * 100) if bal is not None else 0

    acc1, acc2, acc3, acc4 = st.columns(4)
    with acc1:
        st.metric("Balance", f"{bal:,.2f} USDT" if bal is not None else "—")
    with acc2:
        st.metric("PnL LONG", f"{pnl_long:+,.2f} USDT")
    with acc3:
        st.metric("PnL SHORT", f"{pnl_short:+,.2f} USDT")
    with acc4:
        st.metric("Retorno total", f"{ret_pct:+.2f}%")
    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("LONG")
        emoji, label = _heartbeat_status(state_long.get("last_heartbeat"))
        st.metric("Estado", f"{emoji} {label}")
        st.caption(f"Última vela: {state_long.get('last_candle_time', '—')}")
        pos = state_long.get("position")
        if pos:
            st.info(f"**En posición** | Entry: {float(pos.get('entry_price', 0)):,.0f} | Stop: {float(pos.get('stop', 0)):,.0f} | Qty: {float(pos.get('qty', 0)):.5f} BTC")
        else:
            st.success("Sin posición")
        bal = state_long.get("balance_usdt")
        if bal is not None:
            st.metric("Balance", f"{float(bal):,.2f} USDT")
        trades = state_long.get("closed_trades", [])
        if trades:
            recent = trades[-10:]
            total_pnl = sum(t.get("pnl_net", 0) for t in trades)
            n_wins = sum(1 for t in trades if t.get("pnl_net", 0) > 0)
            st.metric("PnL total", f"{total_pnl:,.2f} USDT")
            st.metric("Win rate", f"{n_wins}/{len(trades)} ({n_wins/len(trades)*100:.0f}%)" if trades else "—")
            st.caption("Últimos trades")
            for t in reversed(recent):
                pnl = t.get("pnl_net", 0)
                sym = "✅" if pnl > 0 else "❌"
                st.text(f"{sym} {t.get('exit_time','?')[:16]} | {pnl:+.2f} USDT | {t.get('exit_reason','')}")

    with col2:
        st.subheader("SHORT")
        emoji, label = _heartbeat_status(state_short.get("last_heartbeat"))
        st.metric("Estado", f"{emoji} {label}")
        st.caption(f"Última vela: {state_short.get('last_candle_time', '—')}")
        pos = state_short.get("position")
        if pos:
            st.info(f"**En posición** | Entry: {float(pos.get('entry_price', 0)):,.0f} | Stop: {float(pos.get('stop', 0)):,.0f} | Qty: {float(pos.get('qty', 0)):.5f} BTC")
        else:
            st.success("Sin posición")
        bal = state_short.get("balance_usdt")
        if bal is not None:
            st.metric("Balance", f"{float(bal):,.2f} USDT")
        trades = state_short.get("closed_trades", [])
        if trades:
            total_pnl = sum(t.get("pnl_net", 0) for t in trades)
            n_wins = sum(1 for t in trades if t.get("pnl_net", 0) > 0)
            st.metric("PnL total", f"{total_pnl:,.2f} USDT")
            st.metric("Win rate", f"{n_wins}/{len(trades)} ({n_wins/len(trades)*100:.0f}%)" if trades else "—")
            recent = trades[-10:]
            st.caption("Últimos trades")
            for t in reversed(recent):
                pnl = t.get("pnl_net", 0)
                sym = "✅" if pnl > 0 else "❌"
                st.text(f"{sym} {t.get('exit_time','?')[:16]} | {pnl:+.2f} USDT | {t.get('exit_reason','')}")

    # --- Gráfico últimas barras ---
    st.divider()
    st.subheader("Últimas velas 4H (BTCUSDT)")
    df_ohlcv = _load_last_bars(days=30)
    if not df_ohlcv.empty:
        df_ohlcv = df_ohlcv.tail(150)  # últimas 150 barras (~25 días)
        fig = go.Figure(data=[
            go.Candlestick(
                x=df_ohlcv["open_time"],
                open=df_ohlcv["open"],
                high=df_ohlcv["high"],
                low=df_ohlcv["low"],
                close=df_ohlcv["close"],
                name="BTC",
            )
        ])
        # Marcadores de entrada si hay posición abierta
        for name, state, color, sym in [("LONG", state_long, "green", "triangle-up"), ("SHORT", state_short, "red", "triangle-down")]:
            pos = state.get("position")
            if pos:
                entry = float(pos.get("entry_price", 0))
                entry_ts = pos.get("entry_time")
                if entry_ts and entry > 0:
                    try:
                        entry_dt = pd.to_datetime(entry_ts)
                        fig.add_trace(
                            go.Scatter(
                                x=[entry_dt],
                                y=[entry],
                                mode="markers",
                                name=f"{name} entry",
                                marker=dict(symbol=sym, size=14, color=color, line=dict(width=2, color="white")),
                            )
                        )
                    except Exception:
                        pass
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=400,
            title="Precio BTCUSDT 4H",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos OHLCV. Ejecuta `python cli.py fetch-data --end-date today` para cargar velas.")

    st.divider()
    total_long = sum(t.get("pnl_net", 0) for t in state_long.get("closed_trades", []))
    total_short = sum(t.get("pnl_net", 0) for t in state_short.get("closed_trades", []))
    st.metric("PnL combinado (LONG + SHORT)", f"{total_long + total_short:,.2f} USDT")


def page_runs() -> None:
    st.title("Runs (Backtest & Walk-Forward)")
    tipo_filter = st.sidebar.selectbox("Tipo", ["all", "backtest", "walk_forward", "paper_live"], index=0)
    runs = get_runs(tipo=None if tipo_filter == "all" else tipo_filter, db_path=DB_PATH)
    if not runs:
        st.info("No runs yet. Run `python cli.py backtest --config configs/base.yaml`")
        return
    for r in runs:
        params = r.get("params")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                params = {}
        bt = (params or {}).get("backtest", {})
        cap = bt.get("initial_capital", "-")
        st.subheader(f"Run #{r['id']} — {r['tipo']}")
        st.caption(f"{r['start_date']} → {r['end_date']} | capital: {cap}")
        if st.button("View detail", key=f"run_{r['id']}"):
            st.session_state["run_id"] = int(r["id"])
            st.session_state["page"] = "detail"
            st.rerun()
    # Compare 2 runs
    st.divider()
    st.subheader("Compare 2 runs")
    ids = [r["id"] for r in runs]
    c1, c2 = st.columns(2)
    with c1:
        run_a = st.selectbox("Run A", ids, key="cmp_a")
    with c2:
        run_b = st.selectbox("Run B", ids, key="cmp_b")
    if run_a and run_b and run_a != run_b:
        eq_a = get_equity(run_a, db_path=DB_PATH)
        eq_b = get_equity(run_b, db_path=DB_PATH)
        if not eq_a.empty and not eq_b.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=eq_a["ts"], y=eq_a["equity"], name=f"Run {run_a}"))
            fig.add_trace(go.Scatter(x=eq_b["ts"], y=eq_b["equity"], name=f"Run {run_b}"))
            fig.update_layout(title="Equity comparison", xaxis_title="Time", yaxis_title="Equity")
            st.plotly_chart(fig, use_container_width=True)


def page_run_detail(run_id: int) -> None:
    st.title(f"Run #{run_id} — Detail")
    run = get_run(run_id, db_path=DB_PATH)
    if not run:
        st.warning("Run not found")
        return
    params = run.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {}
    st.caption(f"{run['tipo']} | {run['start_date']} → {run['end_date']}")

    equity_df = get_equity(run_id, db_path=DB_PATH)
    if not equity_df.empty:
        equity_df = equity_df.sort_values("ts")
        eq_series = equity_df.set_index("ts")["equity"]
        peak = eq_series.expanding().max()
        dd = (peak - eq_series) / peak * 100
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.4],
                            subplot_titles=("Equity", "Drawdown %"))
        fig.add_trace(go.Scatter(x=equity_df["ts"], y=equity_df["equity"], name="Equity"), row=1, col=1)
        fig.add_trace(go.Scatter(x=equity_df["ts"], y=dd, name="Drawdown %", fill="tozeroy"), row=2, col=1)
        fig.update_layout(height=500, title_text="Equity & Drawdown")
        st.plotly_chart(fig, use_container_width=True)

    trades_df = get_trades(run_id, db_path=DB_PATH)
    if not trades_df.empty:
        st.subheader("Trades")
        st.dataframe(trades_df, use_container_width=True)
        n_wins = (trades_df["pnl_net"] > 0).sum()
        n_trades = len(trades_df)
        win_rate = n_wins / n_trades * 100 if n_trades else 0
        gross_profit = trades_df.loc[trades_df["pnl_net"] > 0, "pnl_net"].sum()
        gross_loss = abs(trades_df.loc[trades_df["pnl_net"] < 0, "pnl_net"].sum())
        pf = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0)
        st.metric("Win rate", f"{win_rate:.1f}%")
        st.metric("Profit factor", f"{pf:.2f}")
    else:
        st.info("No trades for this run.")

    # Price chart with entry/exit markers (if we had OHLCV we'd overlay; here we show trade times)
    if not trades_df.empty:
        st.subheader("Trade timeline (entry / exit)")
        trades_df["entry_time"] = pd.to_datetime(trades_df["entry_time"])
        trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trades_df["entry_time"], y=trades_df["entry_fill"], mode="markers", name="Entry", marker=dict(symbol="triangle-up", size=12, color="green")))
        fig.add_trace(go.Scatter(x=trades_df["exit_time"], y=trades_df["exit_fill"], mode="markers", name="Exit", marker=dict(symbol="triangle-down", size=12, color="red")))
        fig.update_layout(title="Entry/Exit levels", xaxis_title="Time", yaxis_title="Price")
        st.plotly_chart(fig, use_container_width=True)

    if st.button("← Back to Runs"):
        st.session_state.pop("run_id", None)
        st.session_state.pop("page", None)
        st.rerun()


def page_walk_forward() -> None:
    st.title("Walk-Forward")
    runs = get_runs(tipo="walk_forward", db_path=DB_PATH)
    if not runs:
        st.info("No walk-forward runs. Run `python cli.py walkforward --config configs/wf.yaml`")
        return
    run_id = st.selectbox("Select WF run", [r["id"] for r in runs], key="wf_run")
    if not run_id:
        return
    wf_df = get_wf_windows(run_id, db_path=DB_PATH)
    if wf_df.empty:
        st.warning("No windows for this run")
        return
    st.subheader("Metrics by window")
    st.dataframe(wf_df, use_container_width=True)
    fig = make_subplots(rows=2, cols=2, subplot_titles=("Return %", "Profit factor", "Max DD %", "Win rate %"))
    x = wf_df["window_start"].astype(str)
    fig.add_trace(go.Bar(x=x, y=wf_df["total_return_pct"], name="Return %"), row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=wf_df["profit_factor"], name="PF"), row=1, col=2)
    fig.add_trace(go.Bar(x=x, y=wf_df["max_drawdown_pct"], name="DD %"), row=2, col=1)
    fig.add_trace(go.Bar(x=x, y=wf_df["win_rate"], name="Win rate %"), row=2, col=2)
    fig.update_layout(height=500, title_text="Walk-Forward: metrics by window")
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    # If we navigated from "View detail" button, show that run
    if st.session_state.get("page") == "detail" and st.session_state.get("run_id") is not None:
        page_run_detail(st.session_state["run_id"])
        return
    page = st.sidebar.radio("Page", ["Live Monitor", "Runs", "Run detail", "Walk-Forward"], index=0)
    if page == "Run detail":
        run_id = st.session_state.get("run_id")
        if run_id is not None:
            page_run_detail(run_id)
        else:
            runs = get_runs(db_path=DB_PATH)
            run_id = st.selectbox("Select run", [r["id"] for r in runs], key="detail_run")
            if run_id:
                page_run_detail(run_id)
    elif page == "Walk-Forward":
        page_walk_forward()
    elif page == "Live Monitor":
        page_live_monitor()
    else:
        page_runs()


if __name__ == "__main__":
    main()
