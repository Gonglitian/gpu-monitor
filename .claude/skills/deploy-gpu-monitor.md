# Skill: Deploy GPU Monitor on a Slurm Cluster

Deploy the GPU monitor data collector on a new Slurm cluster. This skill automates the full setup process.

## When to use

User asks to deploy/setup/configure GPU monitor on a cluster (HPCC, BCC, or any new Slurm cluster).

## Prerequisites

- SSH access to the target cluster
- A GitHub PAT (classic) with `repo` scope
- The cluster must have: `sinfo`, `squeue`, `python3`, `curl`, outbound HTTPS access
- A Slurm partition with available CPU resources (e.g., `epyc`, `batch`)

## Steps

### 1. Verify cluster connectivity and capabilities

Run on the target cluster to confirm tools are available:
```bash
which sinfo squeue python3 curl sbatch
sinfo -o "%P %l" | head -10   # Check partitions and time limits
```

Pick a long-walltime CPU partition (prefer 30-day limit, e.g., `epyc`, `batch`, `intel`).

### 2. Add cluster config to collect.py

Edit `gpu_monitor_collect.py` (or the repo's `collect.py`) and add the new cluster to `CLUSTER_CONFIG`:

```python
CLUSTER_CONFIG = {
    "hpcc": {"partitions": "gpu,short_gpu,preempt_gpu"},
    "bcc": {"partitions": "gpu"},
    # Add new cluster:
    "newcluster": {"partitions": "gpu_partition_name"},
}
```

Also update the `choices` in `argparse` at the bottom of the script:
```python
parser.add_argument("--cluster", required=True, choices=["hpcc", "bcc", "newcluster"])
```

### 3. Add cluster to dashboard

Edit `index.html` and add the cluster name to the `CLUSTERS` array:
```javascript
const CLUSTERS = ['hpcc', 'bcc', 'newcluster'];
```

### 4. Save GitHub token on the cluster

```bash
echo 'export GPU_MONITOR_TOKEN="ghp_XXXXX"' > ~/.gpu_monitor_env
chmod 600 ~/.gpu_monitor_env
```

### 5. Deploy collector scripts

Option A — If scripts are in a shared path (like `/bigdata/jlilab/shared/bin/`):
```bash
# Copy scripts to shared bin
cp gpu_monitor_collect.py gpu_monitor_job.sh gpu_monitor_daemon.sh /path/to/shared/bin/
chmod +x /path/to/shared/bin/gpu_monitor_*.sh
```

Option B — Clone the repo:
```bash
git clone https://github.com/Gonglitian/gpu-monitor.git ~/.gpu-monitor
```

### 6. Customize gpu_monitor_job.sh for the cluster

Key things to adjust in `gpu_monitor_job.sh`:
- `#SBATCH -p <partition>` — set to the long-walltime CPU partition identified in step 1
- `#SBATCH -o <log_path>` — set to a path in the user's home directory
- `SCRIPT_DIR=` — set to the absolute path where scripts are stored

### 7. Test collection (dry run)

```bash
source ~/.gpu_monitor_env
python3 /path/to/gpu_monitor_collect.py --cluster newcluster --dry-run
```

Verify the JSON output looks correct: nodes, jobs, pending_jobs, users, summary.

### 8. Test actual push

```bash
python3 /path/to/gpu_monitor_collect.py --cluster newcluster
```

Check that `data/newcluster.json` appears in the GitHub repo.

### 9. Submit as Slurm job

```bash
sbatch /path/to/gpu_monitor_job.sh newcluster
squeue -u $USER -n gpu-monitor   # Verify it's running
```

### 10. Add auto-recovery to .bashrc

```bash
cat >> ~/.bashrc << 'BASHEOF'
# GPU Monitor Auto-Recovery
if ! squeue -u "$USER" -n gpu-monitor -h 2>/dev/null | grep -q gpu-monitor; then
    sbatch /path/to/gpu_monitor_job.sh newcluster >/dev/null 2>&1
fi
BASHEOF
```

### 11. Verify dashboard

Open https://gonglitian.github.io/gpu-monitor/ and switch to the new cluster tab.

## Troubleshooting

- **"sinfo returned no nodes"**: Wrong partition name in CLUSTER_CONFIG. Run `sinfo -o "%P"` to list partitions.
- **"Resource not accessible by personal access token"**: Token lacks `repo` scope. Use a classic PAT, not fine-grained.
- **Job completes immediately**: Check `~/.gpu_monitor_slurm.log` for errors. Common: wrong SCRIPT_DIR path.
- **No network on compute node**: Some clusters block outbound HTTPS from compute nodes. Fall back to screen daemon on login node (Method 2 in README).

## Current deployments

| Cluster | Method | Partition | Script path | Status |
|---------|--------|-----------|-------------|--------|
| HPCC | Slurm job | epyc (30d) | `/rhome/lgong024/shared/bin/` | Active, auto-recovery in .bashrc |
| BCC | Not yet deployed | — | — | Pending |
