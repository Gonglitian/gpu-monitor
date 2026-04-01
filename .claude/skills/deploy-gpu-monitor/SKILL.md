---
name: deploy-gpu-monitor
description: Deploy and manage the GPU monitor data collector on Slurm clusters. Use this skill whenever the user asks to set up, deploy, configure, troubleshoot, or manage GPU monitoring on any cluster — including phrases like "deploy on BCC", "setup monitor", "monitor not working", "add a new cluster", "GPU data not updating", or "配置监控", "部署到新集群". Also use when the user mentions wanting to check why data stopped updating, restart the collector, or add a new cluster to the dashboard.
---

# Deploy GPU Monitor

This skill automates deploying the GPU monitor collector on a Slurm cluster. The collector runs as a lightweight Slurm CPU job (1 core, 512MB) that collects GPU allocation data every 60 seconds via `sinfo`/`squeue` and pushes JSON to GitHub, where GitHub Pages renders the dashboard.

## Architecture Overview

```
Slurm compute node (sbatch, per-cluster partition & walltime)
  └─ gpu_monitor_job.sh → unified script with per-cluster config (case block)
       ├─ Auto-selects partition/walltime/paths based on cluster arg
       ├─ Duplicate prevention: exits if another gpu-monitor job already running
       ├─ Auto-resubmits before walltime expires
       └─ collect.py → sinfo/squeue → JSON → GitHub API PUT (via stdin, not cmdline)

GitHub repo (Gonglitian/gpu-monitor)
  ├─ data/<cluster>.json  ← pushed by collector
  └─ index.html           ← GitHub Pages dashboard

.bashrc auto-recovery: if job dies, resubmits on next login (duplicate-safe)
```

### Per-cluster differences

| Cluster | GPU Partition(s) | Job Partition | Walltime | GRES Format | Notes |
|---------|-----------------|---------------|----------|-------------|-------|
| HPCC | `gpu,short_gpu,preempt_gpu` | `epyc` | 30 days | `gres/gpu:a100:2` | Multiple GPU partitions |
| BCC | `gpu` | `batch` | 7 days | `gpu:7(S:0-1)` | Socket-aware GRES, shorter walltime |

Both clusters use the same `collect.py` — BCC's socket suffix `(S:0-1)` is stripped transparently during parsing.

## When to Use

- **New cluster deployment**: User wants to add monitoring to a cluster
- **Troubleshooting**: Data stopped updating, job died, network issue
- **Adding a cluster to the dashboard**: New cluster needs config in collect.py + index.html
- **Restarting/managing**: User wants to check status, restart, or stop the collector

## Deploy to a New Cluster

### Step 1: Verify cluster capabilities

SSH to the target cluster and check:

```bash
which sinfo squeue python3 curl sbatch
sinfo -o "%P %l" | head -10   # Find a long-walltime CPU partition
```

Requirements:
- `sinfo` and `squeue` available on compute nodes (test via `srun`)
- `python3` and `curl` available
- Outbound HTTPS to `api.github.com` from compute nodes
- A CPU partition with long walltime (ideally 30 days — `epyc`, `batch`, `intel`)

If compute nodes can't reach GitHub (some clusters block outbound), fall back to screen daemon on the login node. See `references/screen-fallback.md`.

### Step 2: Add cluster to collect.py

Edit `gpu_monitor_collect.py`, add to `CLUSTER_CONFIG`:

```python
CLUSTER_CONFIG = {
    "hpcc": {"partitions": "gpu,short_gpu,preempt_gpu"},
    "bcc": {"partitions": "gpu"},
    "newcluster": {"partitions": "the_gpu_partition"},  # ← add this
}
```

Also update the `argparse` choices:
```python
parser.add_argument("--cluster", required=True, choices=["hpcc", "bcc", "newcluster"])
```

Find the correct partition names with: `sinfo -o "%P %G" | grep gpu`

### Step 3: Add cluster to dashboard

Edit `index.html`, find the `CLUSTERS` array and add the new name:
```javascript
const CLUSTERS = ['hpcc', 'bcc', 'newcluster'];
```

### Step 4: Save GitHub token

```bash
echo 'export GPU_MONITOR_TOKEN="ghp_XXXXX"' > ~/.gpu_monitor_env
chmod 600 ~/.gpu_monitor_env
```

Token must be a GitHub PAT (classic) with `repo` scope. Fine-grained tokens need Contents read/write on `Gonglitian/gpu-monitor`.

### Step 5: Deploy scripts

The scripts live in a shared path. Copy them to the cluster:

```bash
# Option A: shared bin directory
scp gpu_monitor_collect.py gpu_monitor_job.sh user@cluster:/path/to/shared/bin/
```

```bash
# Option B: clone the repo
git clone https://github.com/Gonglitian/gpu-monitor.git ~/.gpu-monitor
```

### Step 6: Add cluster config to gpu_monitor_job.sh

Add a new `case` entry in the per-cluster configuration block:

```bash
case "$CLUSTER" in
    hpcc)
        PARTITION="epyc"
        WALLTIME="30-00:00:00"
        RESUBMIT_AFTER=$((29 * 24 * 3600 + 23 * 3600))
        SCRIPT_DIR="/rhome/lgong024/shared/bin"
        LOG_FILE="/rhome/lgong024/.gpu_monitor_slurm.log"
        ;;
    newcluster)   # ← add this block
        PARTITION="the_cpu_partition"
        WALLTIME="7-00:00:00"
        RESUBMIT_AFTER=$((6 * 24 * 3600 + 23 * 3600))
        SCRIPT_DIR="/path/to/scripts"
        LOG_FILE="/path/to/.gpu_monitor_slurm.log"
        ;;
esac
```

The script auto-selects partition/walltime/paths based on the cluster argument. It also prevents duplicate jobs — if another `gpu-monitor` job is already running, new submissions exit gracefully.

### Step 7: Test

```bash
source ~/.gpu_monitor_env

# Dry run — prints JSON without pushing
python3 /path/to/gpu_monitor_collect.py --cluster newcluster --dry-run

# Real push — check GitHub repo for data/newcluster.json
python3 /path/to/gpu_monitor_collect.py --cluster newcluster
```

### Step 8: Submit Slurm job

```bash
# Option A: auto-submit (detects partition/walltime from cluster config)
bash /path/to/gpu_monitor_job.sh newcluster

# Option B: manual sbatch
sbatch --partition=the_cpu_partition --time=7-00:00:00 /path/to/gpu_monitor_job.sh newcluster

squeue -u $USER -n gpu-monitor   # verify running
tail -f ~/.gpu_monitor_slurm.log  # check logs
```

The script includes duplicate prevention — safe to call multiple times (e.g., from `.bashrc`).

### Step 9: Auto-recovery in .bashrc

```bash
cat >> ~/.bashrc << 'EOF'
# GPU Monitor Auto-Recovery
if ! squeue -u "$USER" -n gpu-monitor -h 2>/dev/null | grep -q gpu-monitor; then
    sbatch /path/to/gpu_monitor_job.sh newcluster >/dev/null 2>&1
fi
EOF
```

This ensures the collector restarts automatically if the job dies (node failure, maintenance, etc.).

### Step 10: Verify dashboard

Open https://gonglitian.github.io/gpu-monitor/ and switch to the new cluster tab.

## Troubleshooting

Read `references/troubleshooting.md` for detailed diagnostics. Quick checklist:

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No data on dashboard | Job not running | `squeue -u $USER -n gpu-monitor` — if empty, resubmit |
| "sinfo returned no nodes" | Wrong partition name | `sinfo -o "%P"` to check, update CLUSTER_CONFIG |
| "Resource not accessible" | Token issue | Need classic PAT with `repo` scope |
| Job exits immediately | Script path wrong | Check `SCRIPT_DIR` in job.sh, verify path exists |
| HTTP 409 conflict | Concurrent pushes | Usually self-resolves next cycle |

## Management Commands

```bash
squeue -u $USER -n gpu-monitor     # Check if running
tail -f ~/.gpu_monitor_slurm.log   # View logs
scancel -n gpu-monitor             # Stop collector
sbatch /path/to/gpu_monitor_job.sh cluster  # Restart
```

## Setup Methods

### Method 1: Slurm Job (recommended)
Runs as a lightweight CPU job on a compute node. Survives login node restarts. The job script is unified — just pass the cluster name:

```bash
# Auto-submit (detects partition/walltime from cluster config)
bash /path/to/gpu_monitor_job.sh <cluster>
```

Features: auto-resubmit before walltime expires, duplicate job prevention, per-cluster config.

### Method 2: Screen Daemon (fallback for non-Slurm or restricted networks)
```bash
bash setup.sh <cluster> <token>
```

Runs on login node via `screen`. Manual restart required if daemon dies.

## Current Deployments

| Cluster | Job Partition | Walltime | Script Path | Auto-recovery | Status |
|---------|--------------|----------|-------------|---------------|--------|
| HPCC | epyc | 30 days | `/rhome/lgong024/shared/bin/` | Yes (.bashrc) | Active |
| BCC | batch | 7 days | `/home/eegrad/lgong024/proj/gpu-monitor/` | Yes (.bashrc) | Active |
