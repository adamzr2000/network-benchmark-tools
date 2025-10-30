

Requirements
```bash
sudo apt-get install -y fping
sudo setcap cap_net_raw+ep "$(command -v fping)"
```

```bash
python3 rtt_latency_fping.py 8.8.8.8 -o ./data/test.csv
```