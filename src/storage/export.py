"""Export trades and summary to CSV/Parquet."""
from pathlib import Path
from typing import Any

import pandas as pd

from .models import get_trades, get_runs, get_equity, get_wf_windows, DEFAULT_DB_PATH


def export_trades_csv(
    run_id: int,
    out_path: str | Path,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Path:
    df = get_trades(run_id, db_path)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def export_trades_parquet(
    run_id: int,
    out_path: str | Path,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Path:
    df = get_trades(run_id, db_path)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def export_summary_csv(
    run_ids: list[int] | None = None,
    out_path: str | Path = "data/exports/summary.csv",
    db_path: Path | str = DEFAULT_DB_PATH,
) -> Path:
    runs = get_runs(db_path=db_path)
    if run_ids is not None:
        run_ids_set = set(run_ids)
        runs = [r for r in runs if r["id"] in run_ids_set]
    rows = []
    for r in runs:
        params = r.get("params") or {}
        if isinstance(params, str):
            try:
                import json
                params = json.loads(params)
            except Exception:
                params = {}
            bt = params.get("backtest", {})
        else:
            bt = params.get("backtest", {})
        rows.append({
            "run_id": r["id"],
            "tipo": r["tipo"],
            "start_date": r["start_date"],
            "end_date": r["end_date"],
            "initial_capital": bt.get("initial_capital"),
        })
    df = pd.DataFrame(rows)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path
