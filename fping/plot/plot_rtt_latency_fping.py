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

INFILE = Path("../data/test.csv")
OUTFILE = Path("./cdf_rtt_latency_fping.png")

# Style per request
sns.set_theme(context="paper", style="ticks", font_scale=1.6)

def _ecdf(values):
    # type: (np.ndarray) -> tuple
    v = np.sort(values)
    n = v.size
    y = np.arange(1, n + 1, dtype=float) / n
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
    ax.step(x, y, where="post", linewidth=2)

    for val, label in [(p50, "P50"), (p90, "P90"), (p95, "P95"), (p99, "P99")]:
        ax.axvline(val, linestyle="--", linewidth=1)
        ax.text(val, 0.02, label, rotation=90, va="bottom", ha="right")

    ax.set_xlabel("Ping RTT (ms)")
    ax.set_ylabel("CDF")
    # Add a bit of headroom at the top
    ax.set_ylim(0.0, 1.03)
    ax.set_xlim(left=max(0.0, rtt_min * 0.95), right=rtt_max * 1.05)
    ax.set_title("CDF of Ping RTT")

    # Stats legend
    # stats_text = (
    #     f"n={n}\n"
    #     f"min={rtt_min:.2f} avg={rtt_mean:.2f} max={rtt_max:.2f} std={rtt_std:.2f} ms\n"
    #     f"P50={p50:.2f}  P90={p90:.2f}  P95={p95:.2f}  P99={p99:.2f} ms"
    # )

    # stats_text = (
    #     f"n={n}\n"
    #     f"P50={p50:.2f} ms\nP90={p90:.2f} ms\nP95={p95:.2f} ms\nP99={p99:.2f} ms"
    # )

    stats_text = (
        f"n={n}\n"
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
    )
    ax.grid(True, which="major", axis="both", linestyle="--", alpha=0.8)


    # Spines: dark + slightly thicker
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_color("black")
        ax.spines[side].set_linewidth(2)

    # ax.spines["top"].set_visible(False)
    # ax.spines["right"].set_visible(False)
                                
    fig.tight_layout()
    fig.savefig(OUTFILE, dpi=300)
    print(f"[ok] Saved CDF plot → {OUTFILE}")
    # Optional interactive view:
    plt.show()

if __name__ == "__main__":
    main()
