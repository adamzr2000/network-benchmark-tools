
# Network performance with UDP iperf3

Tool to run **UDP iperf3** tests (UL & DL), collect **per-interval time-series** and compute **summaries**.  
It exports a single JSON with:
- `samples`: timestamped points (bps, jitter ms, loss %)  
  - `direction: "uplink_rx"` → **UL at receiver (server)**  
  - `direction: "uplink"` → UL at sender (client) — context only  
  - `direction: "downlink"` → DL at receiver (client, reverse mode)  
- `summary`: avg/min/max/std (Mbps), avg jitter (ms), avg loss (%)

## Prereqs
```bash
sudo apt-get install -y iperf3
pip install iperf3
```

## Start server
```bash
iperf3 -s              # on the remote server (UDP/TCP 5201)
```

## Run (basic)
```bash
python3 udp_timeseries_iperf3.py --server 10.5.99.12 --duration 10 --blksize 1340 --ul-mbps 300 --dl-mbps 30 --output ./data/test.json
```

## Common options
- `--server` IP/host of iperf3 server
- `--port` server port (default: 5201)
- `--duration` seconds (default: 10)
- `--blksize` UDP datagram size bytes (e.g., 1200/1340)
- `--omit` warm-up seconds to discard (default: 0)
- `--ul-mbps` target uplink rate (client→server)
- `--dl-mbps` target downlink rate (server→client, reverse)
- `--debug` print extra logs
- `--save-ul-raw FILE` save raw UL JSON from iperf3 CLI


## Examples

```bash
python3 udp_timeseries_iperf3.py --server 10.5.15.17 --duration 60 --blksize 1200 --ul-mbps 260 --dl-mbps 800 --output ./data/robot_5g_ul260M_dl800M_bs1200.json

python3 udp_timeseries_iperf3.py --server 10.5.15.17 --duration 60 --blksize 1200 --ul-mbps 260 --dl-mbps 820 --output ./data/robot_5g_ul260M_dl820M_bs1200.json

python3 udp_timeseries_iperf3.py --server 10.5.15.17 --duration 60 --blksize 1200 --ul-mbps 260 --dl-mbps 840 --output ./data/robot_5g_ul260M_dl840M_bs1200.json
```

