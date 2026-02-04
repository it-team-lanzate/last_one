"""SQLite persistence: runs, trades, equity snapshots, wf_windows."""
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_DB_PATH = Path("data/trading.db")


def _get_conn(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    conn = _get_conn(db_path)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            params TEXT,
            seed INTEGER,
            version TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            entry_time TEXT,
            exit_time TEXT,
            entry_fill REAL,
            exit_fill REAL,
            qty REAL,
            r_value REAL,
            r_realized REAL,
            fee_entry REAL,
            fee_exit REAL,
            slippage_entry REAL,
            slippage_exit REAL,
            exit_reason TEXT,
            pnl REAL,
            pnl_net REAL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        CREATE TABLE IF NOT EXISTS equity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            ts TEXT NOT NULL,
            equity REAL NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        CREATE TABLE IF NOT EXISTS wf_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            window_start TEXT,
            window_end TEXT,
            n_trades INTEGER,
            total_return_pct REAL,
            profit_factor REAL,
            max_drawdown_pct REAL,
            win_rate REAL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        """)
        conn.commit()
    finally:
        conn.close()


def save_run(
    tipo: str,
    start_date: str,
    end_date: str,
    params: dict[str, Any],
    run_id: int | None = None,
    seed: int | None = None,
    version: str = "1.0",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    conn = _get_conn(db_path)
    try:
        params_json = json.dumps(params)
        if run_id is not None:
            conn.execute(
                "INSERT INTO runs (id, tipo, start_date, end_date, params, seed, version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, tipo, start_date, end_date, params_json, seed, version),
            )
            conn.commit()
            return run_id
        cur = conn.execute(
            "INSERT INTO runs (tipo, start_date, end_date, params, seed, version) VALUES (?, ?, ?, ?, ?, ?)",
            (tipo, start_date, end_date, params_json, seed, version),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def _trade_val(t: Any, key: str, default: Any = None) -> Any:
    """Get attribute from Trade dataclass or dict."""
    if hasattr(t, key):
        return getattr(t, key)
    if isinstance(t, dict):
        return t.get(key, default)
    return default


def save_trades(
    run_id: int,
    trades: list[Any],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        for t in trades:
            conn.execute(
                """INSERT INTO trades (run_id, entry_time, exit_time, entry_fill, exit_fill, qty, r_value, r_realized,
                   fee_entry, fee_exit, slippage_entry, slippage_exit, exit_reason, pnl, pnl_net)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    str(_trade_val(t, "entry_time")),
                    str(_trade_val(t, "exit_time")),
                    _trade_val(t, "entry_fill"),
                    _trade_val(t, "exit_fill"),
                    _trade_val(t, "qty"),
                    _trade_val(t, "r_value"),
                    _trade_val(t, "r_realized"),
                    _trade_val(t, "fee_entry", 0),
                    _trade_val(t, "fee_exit"),
                    _trade_val(t, "slippage_entry", 0),
                    _trade_val(t, "slippage_exit", 0),
                    _trade_val(t, "exit_reason"),
                    _trade_val(t, "pnl"),
                    _trade_val(t, "pnl_net"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def save_equity(
    run_id: int,
    equity_curve: list[tuple[Any, float]],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        for ts, eq in equity_curve:
            ts_str = str(ts) if hasattr(ts, "isoformat") else str(ts)
            conn.execute(
                "INSERT INTO equity (run_id, ts, equity) VALUES (?, ?, ?)",
                (run_id, ts_str, eq),
            )
        conn.commit()
    finally:
        conn.close()


def save_wf_window(
    run_id: int,
    window_start: str,
    window_end: str,
    n_trades: int,
    total_return_pct: float,
    profit_factor: float,
    max_drawdown_pct: float,
    win_rate: float,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            """INSERT INTO wf_windows (run_id, window_start, window_end, n_trades, total_return_pct, profit_factor, max_drawdown_pct, win_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, window_start, window_end, n_trades, total_return_pct, profit_factor, max_drawdown_pct, win_rate),
        )
        conn.commit()
    finally:
        conn.close()


def get_runs(
    tipo: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_path)
    try:
        if tipo:
            rows = conn.execute(
                "SELECT id, tipo, start_date, end_date, params, seed, version, created_at FROM runs WHERE tipo = ? ORDER BY id DESC",
                (tipo,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, tipo, start_date, end_date, params, seed, version, created_at FROM runs ORDER BY id DESC"
            ).fetchall()
        cols = ["id", "tipo", "start_date", "end_date", "params", "seed", "version", "created_at"]
        out = [dict(zip(cols, r)) for r in rows]
        for o in out:
            if isinstance(o.get("params"), str):
                try:
                    o["params"] = json.loads(o["params"])
                except Exception:
                    pass
        return out
    finally:
        conn.close()


def get_run(run_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, tipo, start_date, end_date, params, seed, version, created_at FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        cols = ["id", "tipo", "start_date", "end_date", "params", "seed", "version", "created_at"]
        out = dict(zip(cols, row))
        if isinstance(out.get("params"), str):
            try:
                out["params"] = json.loads(out["params"])
            except Exception:
                pass
        return out
    finally:
        conn.close()


def get_trades(run_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> pd.DataFrame:
    conn = _get_conn(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM trades WHERE run_id = ? ORDER BY exit_time",
            conn,
            params=(run_id,),
        )
        return df
    finally:
        conn.close()


def get_equity(run_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> pd.DataFrame:
    conn = _get_conn(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT ts, equity FROM equity WHERE run_id = ? ORDER BY ts",
            conn,
            params=(run_id,),
        )
        df["ts"] = pd.to_datetime(df["ts"])
        return df
    finally:
        conn.close()


def get_wf_windows(run_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> pd.DataFrame:
    conn = _get_conn(db_path)
    try:
        df = pd.read_sql_query(
            "SELECT * FROM wf_windows WHERE run_id = ? ORDER BY window_start",
            conn,
            params=(run_id,),
        )
        return df
    finally:
        conn.close()
