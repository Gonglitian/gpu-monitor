---
name: deploy-gpu-monitor
description: Deploy and manage the GPU monitor data collector on Slurm clusters. Use this skill whenever the user asks to set up, deploy, configure, troubleshoot, or manage GPU monitoring on any cluster — including phrases like "deploy on BCC", "setup monitor", "monitor not working", "add a new cluster", "GPU data not updating", or "配置监控", "部署到新集群". Also use when the user mentions wanting to check why data stopped updating, restart the collector, or add a new cluster to the dashboard.
---

# Deploy GPU Monitor

This skill automates deploying the GPU monitor collector on a Slurm cluster. The collector runs as a lightweight Slurm CPU job (1 core, 512MB) that collects GPU allocation data every 60 seconds via `sinfo`/`squeue` and pushes JSON to GitHub, where GitHub Pages renders the dashboard.

## Architecture Overview

```
Slurm compute node (sbatch, epyc/batch partition, 30-day walltime)
  └─ gpu_monitor_job.sh → while loop, 60s interval
       └─ gpu_monitor_collect.py → sinfo/squeue → JSON → GitHub API PUT

GitHub repo (Gonglitian/gpu-monitor)
  ├─ data/<cluster>.json  ← pushed by collector
  └─ index.html           ← GitHub Pages dashboard

.bashrc auto-recovery: if job dies, resubmits on next login
```

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

### Step 6: Customize gpu_monitor_job.sh

Edit these lines for the target cluster:

```bash
#SBATCH -p epyc              # ← change to the cluster's long-walltime partition
#SBATCH -o /path/to/.gpu_monitor_slurm.log  # ← user's home dir
SCRIPT_DIR="/path/to/scripts"  # ← absolute path to where collect.py lives
```

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
sbatch /path/to/gpu_monitor_job.sh newcluster
squeue -u $USER -n gpu-monitor   # verify running
tail -f ~/.gpu_monitor_slurm.log  # check logs
```

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

## Current Deployments

| Cluster | Partition | Script path | Auto-recovery |
|---------|-----------|-------------|---------------|
| HPCC | epyc (30d) | `/rhome/lgong024/shared/bin/` | Yes (.bashrc) |
| BCC | — | — | Not yet deployed |
