"""
Streamlit dashboard: Runs list, Run detail (equity, drawdown, trades, price + markers), Walk-forward.
Uses Plotly for interactive charts.
"""
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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
init_db(DB_PATH)


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
    page = st.sidebar.radio("Page", ["Runs", "Run detail", "Walk-Forward"], index=0)
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
    else:
        page_runs()


if __name__ == "__main__":
    main()
