"""Detalle de ventanas Walk-Forward para dos runs."""
import sqlite3
import sys

DB = "data/trading.db"


def show_wf(run_id: int, label: str):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM wf_windows WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall()
    if not rows:
        print(f"No hay ventanas para run_id={run_id}")
        return

    print("=" * 95)
    print(f"{label} Walk-Forward (run_id={run_id}) - {len(rows)} ventanas")
    print("=" * 95)
    hdr = f"{'#':>3} | {'Start':>10} | {'End':>10} | {'Trades':>6} | {'Return%':>8} | {'PF':>7} | {'DD%':>6} | {'WinRate%':>8}"
    print(hdr)
    print("-" * 95)

    returns = []
    dds = []
    trades_total = 0
    positive = 0
    negative_indices = []

    for i, r in enumerate(rows):
        ret = r["total_return_pct"] or 0
        pf = r["profit_factor"] or 0
        dd = r["max_drawdown_pct"] or 0
        wr = r["win_rate"] or 0
        tr = r["n_trades"] or 0
        returns.append(ret)
        dds.append(dd)
        trades_total += tr
        if ret > 0:
            positive += 1
        else:
            negative_indices.append(i)
        pf_show = min(pf, 99.0)
        print(
            f"{i:>3} | {r['window_start']:>10} | {r['window_end']:>10} | "
            f"{tr:>6} | {ret:>8.2f} | {pf_show:>7.2f} | {dd:>6.2f} | {wr * 100:>8.1f}"
        )

    print("-" * 95)
    n = len(rows)
    mean_ret = sum(returns) / n
    sorted_rets = sorted(returns)
    median_ret = sorted_rets[n // 2]
    std_ret = (sum((r - mean_ret) ** 2 for r in returns) / n) ** 0.5
    print(f"  Ventanas positivas: {positive}/{n} ({positive / n * 100:.0f}%)")
    print(f"  Mean return:   {mean_ret:.2f}%")
    print(f"  Median return: {median_ret:.2f}%")
    print(f"  Min return:    {min(returns):.2f}% | Max return: {max(returns):.2f}%")
    print(f"  Std return:    {std_ret:.2f}%")
    print(f"  Mean DD:       {sum(dds) / n:.2f}%")
    print(f"  Max DD:        {max(dds):.2f}%")
    print(f"  Total trades:  {trades_total}")
    if negative_indices:
        print(f"  Ventanas negativas (indices): {negative_indices}")
    print()
    conn.close()


if __name__ == "__main__":
    long_id = int(sys.argv[1]) if len(sys.argv) > 1 else 84
    short_id = int(sys.argv[2]) if len(sys.argv) > 2 else 85
    show_wf(long_id, "LONG")
    show_wf(short_id, "SHORT")
