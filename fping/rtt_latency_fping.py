#!/usr/bin/env python3
"""
rtt_latency_fping.py — Minimal ICMP RTT collector using fping.

Output CSV columns: ts_epoch_ms,dst,seq,rtt_ms
(Only successful replies are recorded; loss = missing seq numbers.)

Prereqs:
  sudo apt-get install -y fping
  sudo setcap cap_net_raw+ep "$(command -v fping)"
"""

import argparse
import csv
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Iterable, List, Optional

LINE_RE = re.compile(
    r'^\s*(?P<host>[^:\s]+)\s*:\s*\[(?P<seq>\d+)\],.*?,\s*(?P<rtt>[0-9.]+)\s*ms',
    re.IGNORECASE,
)

def parse_args():
    ap = argparse.ArgumentParser(description="Collect ICMP RTTs via fping into a simple CSV.")
    ap.add_argument("hosts", nargs="*", help="Destination hostnames/IPs")
    ap.add_argument("-f", "--hosts-file", type=str, help="File with one host per line")
    ap.add_argument("-c", "--count", type=int, default=1000, help="Probes per host (default: 1000)")
    ap.add_argument("-p", "--period-ms", type=int, default=5, help="Inter-probe period ms (default: 5)")
    ap.add_argument("-s", "--size", type=int, default=None, help="ICMP payload size bytes (optional)")
    ap.add_argument("-o", "--out", type=str, default="rtt_icmp.csv", help="Output CSV path")
    ap.add_argument("--fping-bin", default="fping", help="Path to fping (default: fping)")
    return ap.parse_args()

def load_hosts(args) -> List[str]:
    hosts: List[str] = []
    if args.hosts_file:
        for line in Path(args.hosts_file).read_text().splitlines():
            h = line.strip()
            if h and not h.startswith("#"):
                hosts.append(h)
    hosts += args.hosts or []
    # de-dup preserve order
    seen = set(); ordered = []
    for h in hosts:
        if h not in seen:
            seen.add(h); ordered.append(h)
    if not ordered:
        raise SystemExit("No hosts provided. Use positional hosts or --hosts-file.")
    return ordered

def run_fping(host: str, count: int, period_ms: int, size: Optional[int], fping_bin: str):
    args = [fping_bin, "-c", str(count), "-p", str(period_ms)]
    if size is not None:
        args += ["-b", str(size)]
    args.append(host)
    cmd = " ".join(shlex.quote(a) for a in args)
    with subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1) as p:
        for raw in (p.stdout or []):
            m = LINE_RE.match(raw.strip())
            if m:
                yield {
                    "ts_epoch_ms": int(time.time() * 1000),
                    "dst": m.group("host"),
                    "seq": int(m.group("seq")),
                    "rtt_ms": float(m.group("rtt")),
                }
        # Some builds print per-probe lines to stderr; parse those too
        for raw in (p.stderr.read() or "").splitlines():
            m = LINE_RE.match(raw.strip())
            if m:
                yield {
                    "ts_epoch_ms": int(time.time() * 1000),
                    "dst": m.group("host"),
                    "seq": int(m.group("seq")),
                    "rtt_ms": float(m.group("rtt")),
                }

def write_csv(records: Iterable[dict], out_path: str) -> int:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    rows = list(records)
    rows.sort(key=lambda r: (r["dst"], r["seq"]))
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_epoch_ms", "dst", "seq", "rtt_ms"])
        for r in rows:
            w.writerow([r["ts_epoch_ms"], r["dst"], r["seq"], f"{r['rtt_ms']:.3f}"])
    return len(rows)

def main():
    args = parse_args()
    hosts = load_hosts(args)
    allrecs = []
    for h in hosts:
        allrecs.extend(run_fping(h, args.count, args.period_ms, args.size, args.fping_bin))
    n = write_csv(allrecs, args.out)
    print(f"[ok] Wrote {n} probe rows to {args.out}")

if __name__ == "__main__":
    main()
