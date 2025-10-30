#!/usr/bin/env python3
# plot_udp_timeseries_iperf3.py
#
# Reads ../data/test.json and outputs ./ue_ran_performance_udp_iperf3.png (dpi=300)

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import seaborn as sns

INFILE = Path("../data/test.json")
OUTFILE = Path("./ue_ran_performance_udp_iperf3.png")

COLOR_PALETTE = ["#0000FF", "#FF0000"]

LINEWIDTH = 1.5

def _get_rel_time_s(sample, t0_epoch=None):
    """Return relative time (seconds) from a sample supporting different formats."""
    if "t_rel_s" in sample:
        return float(sample["t_rel_s"])
    if "t_epoch" in sample:
        return float(sample["t_epoch"])
    if "timestamp" in sample:
        return float(sample["timestamp"])
    return 0.0


def _make_relative(xs):
    """If xs look like epochs (large), convert to relative by subtracting min."""
    if not xs:
        return xs
    xmin = min(xs)
    if xmin > 10_000_000:  # epoch-like
        return [x - xmin for x in xs]
    return xs


def _mbps(bps):
    return float(bps) / 1e6


def main():
    with INFILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    samples = data.get("samples", [])
    summary = data.get("summary", {})

    # Split by direction
    ul = [s for s in samples if s.get("direction") == "uplink"]
    dl = [s for s in samples if s.get("direction") == "downlink"]

    # X axis (relative seconds)
    x_ul = _make_relative([_get_rel_time_s(s) for s in ul])
    x_dl = _make_relative([_get_rel_time_s(s) for s in dl])

    # Y left: throughput in Mbps
    y_ul_mbps = [_mbps(s.get("bandwidth_bps", 0.0)) for s in ul]
    y_dl_mbps = [_mbps(s.get("bandwidth_bps", 0.0)) for s in dl]

    # Y right: jitter (ms) and loss (%) — downlink only
    y_dl_jitter_ms = [float(s.get("jitter_ms", 0.0)) for s in dl]
    y_dl_loss_pct = [float(s.get("loss_pct", 0.0)) for s in dl]

    # Pull stats from summary if present; else compute minimal ones
    uplink_stats = summary.get("uplink", {}).get("bandwidth_mbps", {})
    downlink_stats = summary.get("downlink", {}).get("bandwidth_mbps", {})
    dwn_avg_jitter = summary.get("downlink", {}).get("avg_jitter_ms", None)
    dwn_avg_loss = summary.get("downlink", {}).get("avg_loss_pct", None)

    # Fallbacks
    def _safe_stats(arr):
        if not arr:
            return {"avg": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
        import statistics as stats
        return {
            "avg": stats.mean(arr),
            "min": min(arr),
            "max": max(arr),
            "std": stats.pstdev(arr) if len(arr) > 1 else 0.0,
        }

    if not uplink_stats:
        uplink_stats = _safe_stats(y_ul_mbps)
    if not downlink_stats:
        downlink_stats = _safe_stats(y_dl_mbps)
    if dwn_avg_jitter is None:
        dwn_avg_jitter = sum(y_dl_jitter_ms) / len(y_dl_jitter_ms) if y_dl_jitter_ms else 0.0
    if dwn_avg_loss is None:
        dwn_avg_loss = sum(y_dl_loss_pct) / len(y_dl_loss_pct) if y_dl_loss_pct else 0.0

    # === Plot ===
    sns.set_theme(context="paper", style="ticks", font_scale=1.4)
    fig, ax_left = plt.subplots(figsize=(10, 6))

    # Left axis: throughput
    ln_ul, = ax_left.plot(x_ul, y_ul_mbps, label="UL", linewidth=LINEWIDTH, color=COLOR_PALETTE[0])
    ln_dl, = ax_left.plot(x_dl, y_dl_mbps, label="DL", linewidth=LINEWIDTH, color=COLOR_PALETTE[1])
    ax_left.set_xlabel("Time (s)")
    ax_left.set_ylabel("Throughput (Mbps)")

    # Right axis: jitter and loss (use DL color with different linestyles)
    ax_right = ax_left.twinx()
    ln_jit, = ax_right.plot(x_dl, y_dl_jitter_ms, linestyle="--", label="Jitter", linewidth=LINEWIDTH, color=COLOR_PALETTE[0])
    ln_loss, = ax_right.plot(x_dl, y_dl_loss_pct, linestyle=":", label="Loss", linewidth=LINEWIDTH, color=COLOR_PALETTE[1])
    ax_right.set_ylabel("Jitter (ms) / Loss (%)")

    # Title
    ax_left.set_title("UE-side RAN performance: Uplink/Downlink Throughput, Jitter and Loss")

    # Spines styling
    for ax in (ax_left, ax_right):
        for side in ("top", "right", "bottom", "left"):
            if side in ax.spines:
                ax.spines[side].set_color("black")
                ax.spines[side].set_linewidth(LINEWIDTH)


    # === Major grids only ===
    ax_left.set_axisbelow(True)
    ax_right.set_axisbelow(True)
    ax_left.grid(True, which="major", axis="both", linestyle="--", alpha=0.5)
    ax_right.yaxis.grid(True, which="major", linestyle="-.", alpha=0.5)

    # Legends: series legend
    series_handles = [ln_ul, ln_dl, ln_jit, ln_loss]
    series_labels = [h.get_label() for h in series_handles]
    leg1 = ax_left.legend(series_handles, series_labels, loc="upper left", frameon=True)
    frame_leg1 = leg1.get_frame()
    frame_leg1.set_edgecolor("black")
    frame_leg1.set_linewidth(1.5)

    # === Stats legends (text-only) ===
    ul_lines = [
        f"UL min = {uplink_stats['min']:.2f} Mbps",
        f"UL avg = {uplink_stats['avg']:.2f} Mbps",
        f"UL max = {uplink_stats['max']:.2f} Mbps",
        f"UL std = {uplink_stats['std']:.2f} Mbps",
    ]
    dl_lines = [
        f"DL min = {downlink_stats['min']:.2f} Mbps",
        f"DL avg = {downlink_stats['avg']:.2f} Mbps",
        f"DL max = {downlink_stats['max']:.2f} Mbps",
        f"DL std = {downlink_stats['std']:.2f} Mbps",
        f"Jitter avg = {dwn_avg_jitter:.3f} ms",
        f"Loss avg = {dwn_avg_loss:.3f} %",
    ]

    # Dummy handles for text-only legends
    ul_handles = [Line2D([], [], linestyle="", label=s, color="black") for s in ul_lines]
    dl_handles = [Line2D([], [], linestyle="", label=s, color="black") for s in dl_lines]

    # Keep the series legend (Legend 1)
    leg1 = ax_left.legend([ln_ul, ln_dl, ln_jit, ln_loss],
                        [h.get_label() for h in [ln_ul, ln_dl, ln_jit, ln_loss]],
                        loc="upper left", frameon=True)
    leg1.get_frame().set_edgecolor("black"); leg1.get_frame().set_linewidth(1.5)
    ax_left.add_artist(leg1)  # preserve when adding more legends

    # Legend 2: UL stats (top-right)
    leg2 = ax_left.legend(
        ul_handles, [h.get_label() for h in ul_handles],
        loc="upper right", frameon=True, title="Legend 2",
        handlelength=0, handletextpad=0.2, borderpad=0.4, labelspacing=0.3
    )
    leg2.get_frame().set_edgecolor("black"); leg2.get_frame().set_linewidth(1.5)
    ax_left.add_artist(leg2)  # preserve when adding the next one

    # Legend 3: DL stats + jitter/loss (bottom-right)
    leg3 = ax_left.legend(
        dl_handles, [h.get_label() for h in dl_handles],
        loc="lower right", frameon=True, title="Legend 3",
        handlelength=0, handletextpad=0.2, borderpad=0.4, labelspacing=0.3
    )
    leg3.get_frame().set_edgecolor("black"); leg3.get_frame().set_linewidth(1.5)



    # ax_left.margins(y=0.1)
    # ax_right.margins(y=0.1)

    sns.despine(ax=ax_left)
    fig.tight_layout()


    fig.savefig(OUTFILE, dpi=300)
    print(f"Saved figure to {OUTFILE.resolve()}")
    plt.show()


if __name__ == "__main__":
    main()
