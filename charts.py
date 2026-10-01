"""Step 6: charts from results/.

    ./venv/bin/python charts.py   -> charts/01_benchmarks.png, 02_by_hour.png, 03_top_violations.png, 04_boroughs.png
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
R = HERE / "results"
INK, DIM, GRID, BG, BLUE, ORANGE, GRAY = "#f2f2f0", "#8a8a87", "#1d1d1d", "#0b0b0b", "#3987e5", "#d95926", "#9a9a96"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG, "text.color": INK,
    "axes.edgecolor": "#3a3a3a", "axes.labelcolor": DIM, "xtick.color": DIM, "ytick.color": DIM,
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 1,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.family": ["Helvetica Neue", "Arial", "DejaVu Sans"], "font.size": 11, "axes.titlesize": 12,
    "axes.titlelocation": "left", "axes.titlepad": 10,
})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(HERE / "charts" / name, dpi=150)
    plt.close(fig)


def bars(ax, labels, values, unit, colors, title):
    ax.barh(labels, values, color=colors, height=0.55)
    ax.set_xscale("log")
    for i, v in enumerate(values):
        ax.text(v * 1.25, i, (f"{v:,.0f}" if v >= 100 else f"{v:.3g}") + f" {unit}", va="center", color=INK, fontsize=9)
    ax.set_xlim(min(values) / 3, max(values) * 30)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_title(title)


def main():
    (HERE / "charts").mkdir(exist_ok=True)
    b = json.loads((R / "benchmarks.json").read_text())
    fig, axes = plt.subplots(3, 2, figsize=(11, 8.6))
    iv = b["insert_vs_copy_200k_rows"]
    bars(axes[0, 0], ["row-by-row INSERT", "COPY"], [iv["insert_seconds"], iv["copy_seconds"]], "s", [GRAY, BLUE],
         f"Bulk load, 200,000 rows: COPY {iv['copy_times_faster']:.0f}x faster")
    p = b["pruning"]
    bars(axes[0, 1], ["one big table", "partitioned (reads 1 of 12)"], [p["unpartitioned_no_index"]["ms"], p["partitioned"]["ms"]], "ms",
         [GRAY, BLUE], "One day's tickets: partition pruning")
    bb = b["brin_vs_btree"]
    bars(axes[1, 0], ["B-tree index", "BRIN index"], [bb["btree_mb"], bb["brin_mb"]], "MB", [GRAY, BLUE],
         f"Index on issue date: BRIN is {bb['btree_mb'] / bb['brin_mb']:,.0f}x smaller")
    bars(axes[1, 1], ["no index", "BRIN", "B-tree"], [bb["no_index"]["ms"], bb["brin"]["ms"], bb["btree"]["ms"]], "ms",
         [GRAY, BLUE, BLUE], "One week's tickets on the big table")
    r = b["retention_one_month"]
    bars(axes[2, 0], ["DELETE a month", "DETACH a partition"], [r["delete_ms"], r["detach_partition_ms"]], "ms", [GRAY, BLUE],
         "Removing a month of data (1.46M rows)")
    d = b["dashboard"]
    bars(axes[2, 1], ["base table", "materialized view"],
         [d["base_table"]["ms"], d["materialized_view"]["ms"]], "ms", [GRAY, BLUE], "Monthly fines by borough (dashboard)")
    fig.suptitle("What partitioning, BRIN, COPY and a materialized view buy on 15.3 million tickets (log scales)",
                 x=0.01, ha="left", fontsize=13, color=INK)
    save(fig, "01_benchmarks.png")

    h = pd.read_csv(R / "by_hour.csv")
    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(h["hour"], h["camera"] / 1e3, color=ORANGE, linewidth=2, marker="o", markersize=4, label="camera tickets")
    ax.plot(h["hour"], h["officer"] / 1e3, color=BLUE, linewidth=2, marker="o", markersize=4, label="officer tickets")
    ax.set_xticks(range(0, 24, 2), [f"{x:02d}:00" for x in range(0, 24, 2)])
    ax.set_ylabel("tickets in the year (thousands)")
    ax.legend(frameon=False, labelcolor=INK, loc="upper left")
    ax.grid(axis="x", visible=False)
    ax.set_title("Officers ticket mostly in the morning; cameras ticket around the clock")
    save(fig, "02_by_hour.png")

    t = pd.read_csv(R / "top_violations.csv").iloc[::-1]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.barh(t["definition"].str.title(), t["tickets"] / 1e6, color=[ORANGE if c == "t" or c is True else BLUE for c in t["camera"]], height=0.65)
    for i, (v, pct, fine) in enumerate(zip(t["tickets"], t["pct"], t["fine_elsewhere"])):
        ax.text(v / 1e6 + 0.03, i, f"{v / 1e6:.2f}M ({pct}%), ${fine:.0f}", va="center", color=INK, fontsize=9)
    ax.set_xlim(0, t["tickets"].max() / 1e6 * 1.35)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("tickets, fiscal year 2026 (millions); orange = camera, label = share and fine outside lower Manhattan")
    ax.set_title("The 12 most common violations")
    save(fig, "03_top_violations.png")

    bo = pd.read_csv(R / "by_borough.csv")
    bo = bo[bo["borough"] != "Unknown"].iloc[::-1]
    cam = bo["tickets"] * bo["camera_pct"] / 100
    fig, ax = plt.subplots(figsize=(10, 3.6))
    ax.barh(bo["borough"], (bo["tickets"] - cam) / 1e6, color=BLUE, height=0.6, label="officer")
    ax.barh(bo["borough"], cam / 1e6, left=(bo["tickets"] - cam) / 1e6, color=ORANGE, height=0.6, label="camera")
    for i, (tot, pct) in enumerate(zip(bo["tickets"], bo["camera_pct"])):
        ax.text(tot / 1e6 + 0.05, i, f"{tot / 1e6:.2f}M, {pct:.0f}% camera", va="center", color=INK, fontsize=9)
    ax.set_xlim(0, bo["tickets"].max() / 1e6 * 1.35)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, labelcolor=INK, loc="lower right")
    ax.set_xlabel("tickets (millions)")
    ax.set_title("Manhattan's tickets come from officers; Staten Island's mostly from cameras")
    save(fig, "04_boroughs.png")
    print("charts written")


if __name__ == "__main__":
    main()
