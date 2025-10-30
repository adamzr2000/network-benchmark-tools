#!/usr/bin/env python3
"""
udp_iperf_timeseries.py

Run iperf3 UDP tests (uplink and downlink) and export timeseries metrics to JSON:
- timestamps:
    * t_rel_s  (seconds from test start; great for plotting)
    * t_epoch  (Unix epoch; optional)
- direction ("uplink" | "downlink")
- bandwidth_bps
- For DOWNLINK ONLY: jitter_ms (client-side), loss_pct (client-side)

Also appends a 'summary' section:
- Uplink: bandwidth_mbps {avg, min, max, std}
- Downlink: bandwidth_mbps {avg, min, max, std}, avg_jitter_ms, avg_loss_pct
"""

import argparse
import json
import time
from pathlib import Path
from statistics import mean, pstdev
import iperf3

def _safe_mean(xs):
    return mean(xs) if xs else 0.0

def _safe_pstdev(xs):
    return pstdev(xs) if len(xs) > 1 else 0.0

def _uplink_summary(samples):
    sdir = [s for s in samples if s.get("direction") == "uplink"]
    mbps = [s["bandwidth_bps"] / 1e6 for s in sdir]
    return {
        "num_samples": len(sdir),
        "bandwidth_mbps": {
            "avg": _safe_mean(mbps),
            "min": min(mbps) if mbps else 0.0,
            "max": max(mbps) if mbps else 0.0,
            "std": _safe_pstdev(mbps),
        },
    }

def _downlink_summary(samples):
    sdir = [s for s in samples if s.get("direction") == "downlink"]
    mbps = [s["bandwidth_bps"] / 1e6 for s in sdir]
    jitter_ms = [float(s.get("jitter_ms", 0.0)) for s in sdir]
    loss_pct = [float(s.get("loss_pct", 0.0)) for s in sdir]
    return {
        "num_samples": len(sdir),
        "bandwidth_mbps": {
            "avg": _safe_mean(mbps),
            "min": min(mbps) if mbps else 0.0,
            "max": max(mbps) if mbps else 0.0,
            "std": _safe_pstdev(mbps),
        },
        "avg_jitter_ms": _safe_mean(jitter_ms),
        "avg_loss_pct": _safe_mean(loss_pct),
    }

def build_summary(samples):
    return {
        "uplink": _uplink_summary(samples),
        "downlink": _downlink_summary(samples),
    }

def _extract_interval_stats(it: dict) -> dict:
    """
    Return: end, start, bps, jitter_ms, loss_pct
    Tries 'sum' -> 'sum_received' -> 'sum_sent' -> aggregate over 'streams'.
    """
    cand = it.get("sum") or it.get("sum_received") or it.get("sum_sent")
    if cand:
        return {
            "start": float(cand.get("start", 0.0)),
            "end": float(cand.get("end", 0.0)),  # seconds since test start
            "bps": float(cand.get("bits_per_second", cand.get("bps", 0.0))),
            "jitter_ms": float(cand.get("jitter_ms", 0.0)),
            "loss_pct": float(cand.get("lost_percent", cand.get("lost_percent", 0.0))),
        }

    streams = it.get("streams") or []
    if streams:
        start = None
        end = 0.0
        bps = 0.0
        jitter_ms = None
        loss_pct = None
        for s in streams:
            snd = s.get("sender", {}) or {}
            rcv = s.get("receiver", {}) or {}
            src = rcv or snd or s
            if start is None:
                start = float(src.get("start", 0.0))
            else:
                start = min(start, float(src.get("start", 0.0)))
            end = max(end, float(src.get("end", 0.0)))
            bps += float(src.get("bits_per_second", src.get("bps", 0.0)))
            if jitter_ms is None and "jitter_ms" in src:
                jitter_ms = float(src["jitter_ms"])
            if loss_pct is None and "lost_percent" in src:
                loss_pct = float(src["lost_percent"])
        return {
            "start": float(start or 0.0),
            "end": end,
            "bps": bps,
            "jitter_ms": float(jitter_ms or 0.0),
            "loss_pct": float(loss_pct or 0.0),
        }

    return {"start": 0.0, "end": 0.0, "bps": 0.0, "jitter_ms": 0.0, "loss_pct": 0.0}

def _make_ts_fields(end_rel_s: float, t0_epoch: float, time_format: str):
    """
    Produce timestamp fields per user choice.
    - relative: {'t_rel_s': end_rel_s}
    - epoch:    {'t_epoch': t0_epoch + end_rel_s}
    - both:     both fields
    """
    if time_format == "relative":
        return {"t_rel_s": end_rel_s}
    elif time_format == "epoch":
        return {"t_epoch": t0_epoch + end_rel_s}
    else:  # both (default)
        return {"t_rel_s": end_rel_s, "t_epoch": t0_epoch + end_rel_s}

def _run_udp_once(
    server: str,
    port: int,
    duration: int,
    bandwidth_mbps: float,
    reverse: bool,
    omit: int,
    blksize: int,
    time_format: str,
):
    client = iperf3.Client()
    client.server_hostname = server
    client.port = port
    client.protocol = 'udp'
    client.duration = duration
    client.reverse = reverse
    client.omit = omit
    if blksize > 0:
        client.blksize = blksize
    client.bandwidth = int(bandwidth_mbps * 1_000_000)

    # t0 from wall clock (for epoch), while relative uses iperf interval 'end'
    t0_epoch = time.time()
    result = client.run()
    if result.error:
        raise RuntimeError(f"iperf3 error (reverse={reverse}): {result.error}")

    raw = result.json or {}
    intervals = raw.get("intervals", [])
    direction = "downlink" if reverse else "uplink"

    samples = []
    for it in intervals:
        stats = _extract_interval_stats(it)
        ts_fields = _make_ts_fields(stats["end"], t0_epoch, time_format)

        entry = {
            **ts_fields,
            "direction": direction,
            "bandwidth_bps": stats["bps"],
        }
        if direction == "downlink":
            entry["jitter_ms"] = stats["jitter_ms"]
            entry["loss_pct"] = stats["loss_pct"]
        samples.append(entry)

    meta = {
        "server": server,
        "port": port,
        "protocol": "udp",
        "duration_s": duration,
        "bandwidth_target_mbps": bandwidth_mbps,
        "reverse": reverse,
        "omit_s": omit,
        "blksize": blksize if blksize > 0 else None,
        "iperf3_version_client": raw.get("start", {}).get("version"),
        "t0_epoch": t0_epoch,  # useful when using relative timestamps
        "time_format": time_format,
    }
    return meta, samples

def run_udp_bi(
    server: str,
    port: int,
    duration: int,
    bandwidth_mbps: float,
    omit: int = 0,
    blksize: int = 0,
    time_format: str = "both",
):
    """
    Run uplink (client->server) and downlink (server->client via --reverse) sequentially.
    Returns a combined structure with metadata, per-interval samples, and summary.
    """
    meta_up, samples_up = _run_udp_once(
        server, port, duration, bandwidth_mbps, reverse=False,
        omit=omit, blksize=blksize, time_format=time_format
    )
    meta_down, samples_down = _run_udp_once(
        server, port, duration, bandwidth_mbps, reverse=True,
        omit=omit, blksize=blksize, time_format=time_format
    )

    combined_samples = samples_up + samples_down

    return {
        "metadata": {
            "server": server,
            "port": port,
            "protocol": "udp",
            "duration_s": duration,
            "bandwidth_target_mbps": bandwidth_mbps,
            "omit_s": omit,
            "blksize": blksize if blksize > 0 else None,
            "time_format": time_format,
            "tests": {
                "uplink": {k: v for k, v in meta_up.items() if k not in ("reverse", "time_format")},
                "downlink": {k: v for k, v in meta_down.items() if k not in ("reverse", "time_format")},
            }
        },
        "samples": combined_samples,
        "summary": build_summary(combined_samples),
    }

def main():
    parser = argparse.ArgumentParser(description="Run iperf3 UDP in both directions and export interval metrics to JSON.")
    parser.add_argument("--server", required=True, help="iperf3 server hostname or IP")
    parser.add_argument("--port", type=int, default=5201, help="iperf3 server port (default: 5201)")
    parser.add_argument("--duration", type=int, default=10, help="Test duration in seconds (default: 10)")
    parser.add_argument("--bandwidth-mbps", type=float, default=10.0, help="Target UDP bandwidth in Mbps (default: 10)")
    parser.add_argument("--omit", type=int, default=0, help="Seconds to omit at start (warm-up). Default: 0")
    parser.add_argument("--blksize", type=int, default=0, help="Datagram size (bytes); 0 to let iperf3 choose")
    parser.add_argument("--time-format", choices=["relative", "epoch", "both"], default="both",
                        help="Timestamp format for samples (default: both)")
    parser.add_argument("--output", required=True, help="Output JSON file path")

    args = parser.parse_args()

    result = run_udp_bi(
        server=args.server,
        port=args.port,
        duration=args.duration,
        bandwidth_mbps=args.bandwidth_mbps,
        omit=args.omit,
        blksize=args.blksize,
        time_format=args.time_format,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Console summary
    summary = result.get("summary", {})
    def _fmt_bw(bw): return f'{bw["avg"]:.2f} avg | {bw["min"]:.2f} min | {bw["max"]:.2f} max | {bw["std"]:.2f} std'
    upl = summary.get("uplink", {})
    dwn = summary.get("downlink", {})
    print(f"Wrote {out_path} with {len(result['samples'])} samples.")
    print("=== SUMMARY (client-side) ===")
    print(f'Uplink  samples: {upl.get("num_samples", 0)}')
    if "bandwidth_mbps" in upl:
        print(f'  BW Mbps: {_fmt_bw(upl["bandwidth_mbps"])}')
    print(f'Downlink samples: {dwn.get("num_samples", 0)}')
    if "bandwidth_mbps" in dwn:
        print(f'  BW Mbps: {_fmt_bw(dwn["bandwidth_mbps"])}')
    print(f'  Jitter ms (avg): {dwn.get("avg_jitter_ms", 0.0):.3f}')
    print(f'  Loss % (avg):    {dwn.get("avg_loss_pct", 0.0):.3f}')

if __name__ == "__main__":
    main()
