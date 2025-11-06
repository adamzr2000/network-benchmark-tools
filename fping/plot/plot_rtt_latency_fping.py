#!/usr/bin/env python3
# plot_rtt_latency_fping.py
#
# Reads ../data/test.csv (columns: ts_epoch_ms,dst,seq,rtt_ms)
# Writes ./cdf_rtt_latency_fping.png (dpi=300)

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import seaborn as sns


# INFILE = Path("../data/test.csv")
INFILE = Path("../data/test1/robot_5g_c1000_p100.csv")
OUTFILE = Path("./cdf_rtt_latency_fping.png")

# Style per request
sns.set_theme(context="paper", style="ticks", font_scale=1.6)

COLOR = "#0000FF"

# ✅ (4) Improved ECDF using unique values for efficiency
def _ecdf(values):
    v, counts = np.unique(np.sort(values), return_counts=True)
    cum = np.cumsum(counts)
    y = cum / cum[-1]
    return v, y

def main():
    if not INFILE.exists():
        raise FileNotFoundError(f"Input file not found: {INFILE}")

    df = pd.read_csv(INFILE)
    if "rtt_ms" not in df.columns:
        raise ValueError("CSV must contain an 'rtt_ms' column")

    rtt = pd.to_numeric(df["rtt_ms"], errors="coerce").to_numpy()
    rtt = rtt[np.isfinite(rtt)]
    rtt = rtt[rtt >= 0]
    if rtt.size == 0:
        raise ValueError("No valid RTT samples to plot after filtering.")

    # Stats
    n = rtt.size
    p50 = float(np.percentile(rtt, 50))
    p90 = float(np.percentile(rtt, 90))
    p95 = float(np.percentile(rtt, 95))
    p99 = float(np.percentile(rtt, 99))
    rtt_min = float(np.min(rtt))
    rtt_max = float(np.max(rtt))
    rtt_mean = float(np.mean(rtt))
    rtt_std = float(np.std(rtt, ddof=1)) if n > 1 else float("nan")  # sample std

    # ECDF
    x, y = _ecdf(rtt)

    # Plot
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.step(x, y, where="post", linewidth=2, color=COLOR)

    for val, label in [(p50, "P50"), (p90, "P90"), (p95, "P95"), (p99, "P99")]:
        ax.axvline(val, linestyle="--", linewidth=1, color=COLOR)
        ax.text(val, 0.02, label, rotation=90, va="bottom", ha="right", color=COLOR)

    ax.set_xlabel("Ping RTT (ms)")
    ax.set_ylabel("CDF")
    ax.set_ylim(0.0, 1.03)

    # ✅ (5) Log x-axis if RTT range is large
    if rtt_min > 0 and (rtt_max / rtt_min) > 50:
        ax.set_xscale("log")
        ax.set_xlabel("Ping RTT (ms, log scale)")
        # avoid negative x-limit with log scale
        ax.set_xlim(left=rtt_min * 0.95, right=rtt_max * 1.05)
    else:
        ax.set_xlim(left=max(0.0, rtt_min * 0.95), right=rtt_max * 1.05)

    ax.set_title("CDF of Ping RTT")

    stats_text = (
        f"n={n} samples\n"
        f"Min={rtt_min:.2f} ms\nAvg={rtt_mean:.2f} ms\nMax={rtt_max:.2f} ms\nStd={rtt_std:.2f} ms\n"
    )

    stats_handle = Line2D([], [], linestyle="none", marker=None, label=stats_text)
    ax.legend(
        handles=[stats_handle],
        loc="center right",
        frameon=True,
        fancybox=True,
        framealpha=0.9,
        borderpad=0.8,
        handlelength=0,
        handletextpad=0.0,
        fontsize=12
    )
    ax.grid(True, which="major", axis="both", linestyle="--", alpha=0.8)

    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_color("black")
        ax.spines[side].set_linewidth(2)

    fig.tight_layout()
    fig.savefig(OUTFILE, dpi=300)
    print(f"[ok] Saved CDF plot → {OUTFILE}")
    plt.show()

if __name__ == "__main__":
    main()
