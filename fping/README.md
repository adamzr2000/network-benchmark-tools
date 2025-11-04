

Requirements
```bash
sudo apt-get install -y fping
sudo setcap cap_net_raw+ep "$(command -v fping)"
```

```bash
python3 rtt_latency_fping.py 10.5.1.21 -c 10000 -p 20 -o ./data/robot_5g_c10000_p20.csv
```