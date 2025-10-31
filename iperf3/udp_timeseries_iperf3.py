#!/usr/bin/env python3
import argparse, json, re, shutil, subprocess, time
from pathlib import Path
from statistics import mean, pstdev
import iperf3

def _safe_mean(xs): return mean(xs) if xs else 0.0
def _safe_pstdev(xs): return pstdev(xs) if len(xs) > 1 else 0.0

def _direction_summary(samples, direction):
    sdir = [s for s in samples if s.get("direction") == direction]
    mbps = [s["bandwidth_bps"]/1e6 for s in sdir]
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
        "uplink": _direction_summary(samples, "uplink"),         # sender-side intervals
        "uplink_rx": _direction_summary(samples, "uplink_rx"),   # receiver-side intervals (new)
        "downlink": _direction_summary(samples, "downlink"),     # receiver-side intervals
    }

def _extract_interval_stats(it: dict, prefer_receiver: bool = True) -> dict:
    cand = None
    if prefer_receiver:
        cand = it.get("sum_received") or it.get("sum")
        if not cand: cand = it.get("sum_sent")
    else:
        cand = it.get("sum_sent") or it.get("sum") or it.get("sum_received")
    if cand:
        return {
            "end": float(cand.get("end", 0.0)),
            "bps": float(cand.get("bits_per_second", cand.get("bps", 0.0))),
            "jitter_ms": float(cand.get("jitter_ms", 0.0)),
            "loss_pct": float(cand.get("lost_percent", 0.0)),
        }
    streams = it.get("streams") or []
    if streams:
        end=bps=0.0; jitter_ms=loss_pct=None
        for s in streams:
            snd = s.get("sender", {}) or {}
            rcv = s.get("receiver", {}) or {}
            src = rcv if prefer_receiver else (snd or rcv) or {}
            end = max(end, float(src.get("end", 0.0)))
            bps += float(src.get("bits_per_second", src.get("bps", 0.0)))
            if jitter_ms is None and "jitter_ms" in src: jitter_ms=float(src["jitter_ms"])
            if loss_pct is None and "lost_percent" in src: loss_pct=float(src["lost_percent"])
        return {"end": end, "bps": bps, "jitter_ms": float(jitter_ms or 0.0), "loss_pct": float(loss_pct or 0.0)}
    return {"end": 0.0, "bps": 0.0, "jitter_ms": 0.0, "loss_pct": 0.0}

# ---- Parse receiver per-interval lines from server_output_text ----
_RX_CLI_RECV_INTERVAL = re.compile(
    r"\[\s*\d+\]\s*(\d+\.\d+)-(\d+\.\d+)\s*sec\s+"
    r"([\d\.]+)\s*MBytes\s+([\d\.]+)\s*Mbits/sec\s+"
    r"([\d\.]+)\s*ms\s+(\d+)/(\d+)\s*\(([\d\.]+)%\)\s*$",
    re.IGNORECASE
)

def _parse_receiver_interval_lines(text: str):
    points = []
    if not text: return points
    for line in text.splitlines():
        m = _RX_CLI_RECV_INTERVAL.search(line)
        if not m: continue
        start_s = float(m.group(1)); end_s = float(m.group(2))
        mbps = float(m.group(4))
        jitter_ms = float(m.group(5))
        lost = int(m.group(6)); total = int(m.group(7))
        loss_pct = float(m.group(8)) if total > 0 else 0.0
        points.append({
            "start": start_s, "end": end_s,
            "bandwidth_mbps": mbps, "jitter_ms": jitter_ms,
            "loss_pct": loss_pct
        })
    return points

def _ul_via_cli(server, port, duration, bandwidth_mbps, blksize, omit, debug=False, save_ul_raw: Path=None):
    if not shutil.which("iperf3"):
        raise RuntimeError("iperf3 CLI not found in PATH; required for uplink run.")
    cmd = [
        "iperf3","-c",server,"-p",str(port),
        "-u","-b",f"{float(bandwidth_mbps)}M",
        "-t",str(int(duration)),"-i","1",
        "--json","--get-server-output"
    ]
    if blksize and int(blksize)>0: cmd += ["-l", str(int(blksize))]
    if omit and int(omit)>0: cmd += ["-O", str(int(omit))]
    if debug: print("[DBG] UL CLI:", " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"iperf3 CLI uplink failed: {p.stderr.strip() or p.stdout.strip()}")
    try:
        raw = json.loads(p.stdout)
    except Exception as e:
        raise RuntimeError(f"iperf3 CLI uplink returned non-JSON output: {e}")
    if save_ul_raw:
        save_ul_raw.parent.mkdir(parents=True, exist_ok=True)
        with save_ul_raw.open("w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    # Sender-side intervals (from JSON)
    intervals = raw.get("intervals", []) or []
    start_ts = float(raw.get("start", {}).get("timestamp", {}).get("timesecs", time.time()))
    samples_ul_sender = []
    for it in intervals:
        stats = _extract_interval_stats(it, prefer_receiver=False)
        ts = start_ts + stats["end"]
        samples_ul_sender.append({
            "timestamp": ts,
            "direction": "uplink",
            "bandwidth_bps": stats["bps"],
            "jitter_ms": stats["jitter_ms"],
            "loss_pct": stats["loss_pct"],
        })

    # Receiver-side per-intervals (from server_output_text)
    s_text = raw.get("server_output_text") or ""
    rx_points = _parse_receiver_interval_lines(s_text)
    samples_ul_rx = []
    for pt in rx_points:
        # clamp to duration (server sometimes prints a bit beyond T)
        if pt["end"] > duration + 0.5:  # small slack
            continue
        ts = start_ts + pt["end"]
        samples_ul_rx.append({
            "timestamp": ts,
            "direction": "uplink_rx",  # receiver-side series
            "bandwidth_bps": pt["bandwidth_mbps"] * 1e6,
            "jitter_ms": pt["jitter_ms"],
            "loss_pct": pt["loss_pct"],
        })

    # Final receiver totals (already handled)
    recv_total = None
    # Try the last receiver line in text:
    if rx_points:
        # compute a simple average from text’s final line
        last = rx_points[-1]
        # Not strictly necessary; we keep totals out of these intervals
    # Or from the final receiver summary line (not per-interval; we keep previous logic if needed)

    meta = {
        "server": server,
        "port": port,
        "protocol": "udp",
        "duration_s": duration,
        "bandwidth_target_mbps": bandwidth_mbps,
        "reverse": False,
        "omit_s": omit,
        "blksize": blksize if blksize and blksize>0 else None,
        "iperf3_version_client": raw.get("start", {}).get("version"),
        # keep full text in case you want to re-parse later
        "server_output_text_present": bool(s_text),
    }

    # Extract final receiver totals too (for the UL summary override)
    # Parse the very last "receiver" line:
    last_recv = None
    for line in reversed(s_text.splitlines()):
        if "receiver" in line:
            m = re.search(r"([\d\.]+)\s*Mbits/sec\s+([\d\.]+)\s*ms\s+(\d+)/(\d+)\s*\(([\d\.]+)%\)", line)
            if m:
                last_recv = {
                    "bandwidth_mbps": float(m.group(1)),
                    "jitter_ms": float(m.group(2)),
                    "lost_packets": int(m.group(3)),
                    "packets": int(m.group(4)),
                    "lost_percent": float(m.group(5)),
                }
            break
    if last_recv:
        meta["receiver_totals"] = last_recv

    return meta, samples_ul_sender, samples_ul_rx

def _dl_via_lib(server, port, duration, bandwidth_mbps, omit, blksize):
    client = iperf3.Client()
    client.server_hostname = server
    client.port = port
    client.protocol = 'udp'
    client.duration = duration
    client.reverse = True
    client.omit = omit
    if blksize and blksize>0: client.blksize = blksize
    client.bandwidth = int(float(bandwidth_mbps) * 1_000_000)
    wall_start = time.time()
    result = client.run()
    if result.error:
        raise RuntimeError(f"iperf3 DL error: {result.error}")
    raw = result.json or {}
    intervals = raw.get("intervals", []) or []
    samples = []
    for it in intervals:
        stats = _extract_interval_stats(it, prefer_receiver=True)
        ts = wall_start + stats["end"]
        samples.append({
            "timestamp": ts,
            "direction": "downlink",
            "bandwidth_bps": stats["bps"],
            "jitter_ms": stats["jitter_ms"],
            "loss_pct": stats["loss_pct"],
        })
    meta = {
        "server": server, "port": port, "protocol": "udp",
        "duration_s": duration, "bandwidth_target_mbps": bandwidth_mbps,
        "reverse": True, "omit_s": omit,
        "blksize": blksize if blksize and blksize>0 else None,
        "iperf3_version_client": raw.get("start", {}).get("version"),
    }
    return meta, samples

def run_udp_bi(server, port, duration, ul_mbps, dl_mbps, omit=0, blksize=0, debug=False, save_ul_raw: Path=None):
    meta_up, samples_up_sender, samples_up_rx = _ul_via_cli(
        server, port, duration, ul_mbps, blksize, omit, debug=debug, save_ul_raw=save_ul_raw
    )
    meta_down, samples_down = _dl_via_lib(server, port, duration, dl_mbps, omit, blksize)
    samples = samples_up_sender + samples_up_rx + samples_down
    summary = build_summary(samples)

    # UL summary override with receiver totals if present
    ul_recv = meta_up.get("receiver_totals")
    if ul_recv:
        summary["uplink"]["bandwidth_mbps"]["avg"] = float(ul_recv["bandwidth_mbps"])
        summary["uplink"]["avg_jitter_ms"] = float(ul_recv["jitter_ms"])
        summary["uplink"]["avg_loss_pct"] = float(ul_recv["lost_percent"])

    return {
        "metadata": {
            "server": server, "port": port, "protocol": "udp",
            "duration_s": duration, "omit_s": omit,
            "blksize": blksize if blksize and blksize>0 else None,
            "tests": {
                "uplink":   {**{k:v for k,v in meta_up.items() if k!="reverse"}, "direction":"uplink"},
                "downlink": {**{k:v for k,v in meta_down.items() if k!="reverse"}, "direction":"downlink"},
            },
            "notes": {
                "uplink_intervals_sender": True,
                "uplink_intervals_receiver_series": "uplink_rx",
                "uplink_summary_uses_receiver_totals_when_available": True
            }
        },
        "samples": samples,
        "summary": summary,
    }

def main():
    p = argparse.ArgumentParser(description="iperf3 UDP: UL (CLI w/ server_output) + DL (lib); export timeseries + summary")
    p.add_argument("--server", required=True)
    p.add_argument("--port", type=int, default=5201)
    p.add_argument("--duration", type=int, default=10)
    p.add_argument("--ul-mbps", type=float, required=True)
    p.add_argument("--dl-mbps", type=float, required=True)
    p.add_argument("--omit", type=int, default=0)
    p.add_argument("--blksize", type=int, default=0)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--save-ul-raw", type=str, default=None)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    save_ul_raw_path = Path(args.save_ul_raw) if args.save_ul_raw else None
    result = run_udp_bi(
        server=args.server, port=args.port, duration=args.duration,
        ul_mbps=args.ul_mbps, dl_mbps=args.dl_mbps,
        omit=args.omit, blksize=args.blksize,
        debug=args.debug, save_ul_raw=save_ul_raw_path
    )
    out_path = Path(args.output); out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # Console
    summary = result["summary"]
    def _fmt_bw(bw): return f'{bw["avg"]:.2f} avg | {bw["min"]:.2f} min | {bw["max"]:.2f} max | {bw["std"]:.2f} std'
    print(f"Wrote {out_path} with {len(result['samples'])} samples.")
    print("=== SUMMARY (UL summary = receiver totals; UL has sender & receiver series) ===")
    upl, uplrx, dwn = summary["uplink"], summary["uplink_rx"], summary["downlink"]
    print(f'Uplink (sender) target: {args.ul_mbps:.2f} Mbps | samples: {upl["num_samples"]}')
    print(f'  BW Mbps: {_fmt_bw(upl["bandwidth_mbps"])}')
    print(f'  Jitter ms (avg): {upl["avg_jitter_ms"]:.3f}')
    print(f'  Loss % (avg):    {upl["avg_loss_pct"]:.3f}')
    print(f'Uplink RX (server) | samples: {uplrx["num_samples"]}')
    print(f'  BW Mbps: {_fmt_bw(uplrx["bandwidth_mbps"])}')
    print(f'  Jitter ms (avg): {uplrx["avg_jitter_ms"]:.3f}')
    print(f'  Loss % (avg):    {uplrx["avg_loss_pct"]:.3f}')
    print(f'Downlink target: {args.dl_mbps:.2f} Mbps | samples: {dwn["num_samples"]}')
    print(f'  BW Mbps: {_fmt_bw(dwn["bandwidth_mbps"])}')
    print(f'  Jitter ms (avg): {dwn["avg_jitter_ms"]:.3f}')
    print(f'  Loss % (avg):    {dwn["avg_loss_pct"]:.3f}')

if __name__ == "__main__":
    main()
