# GPU Monitor

Real-time GPU allocation dashboard for Slurm clusters, deployed on GitHub Pages.

**Live Dashboard:** https://gonglitian.github.io/gpu-monitor/

## Features

- Real-time GPU allocation status per node (used / free / down)
- Per-node job details: who's using what, job name, elapsed time
- User leaderboard: GPU usage ranking across all users
- Pending queue: queued jobs with reason (Priority, Resources, etc.)
- Historical trends: GPU usage, queue depth, active users over 7 days
- Multi-cluster support (HPCC, BCC) with tab switching
- Auto-refresh every 60 seconds

## Architecture

```
Slurm Cluster (compute node, sbatch job, every 1 min)
  └─ collect.py: sinfo/squeue → JSON → GitHub API PUT
  └─ gpu_monitor_job.sh: 30-day Slurm job, auto-resubmits before expiry
  └─ .bashrc auto-recovery: resubmits if job dies on next login

GitHub Pages (static HTML)
  └─ index.html: fetch JSON from raw.githubusercontent.com → Chart.js render
```

No build step. No backend server. Data flows through GitHub as storage.

## Deployment Methods

### Method 1: Slurm Job (recommended for HPCC/BCC)

Runs as a lightweight CPU job on a compute node. Survives login node restarts, no screen/tmux needed.

```bash
# 1. Save token
echo 'export GPU_MONITOR_TOKEN="ghp_YOUR_TOKEN"' > ~/.gpu_monitor_env && chmod 600 ~/.gpu_monitor_env

# 2. Submit as Slurm job (30-day walltime, auto-resubmits)
sbatch /path/to/gpu_monitor_job.sh hpcc

# 3. (Optional) Add auto-recovery to .bashrc
cat >> ~/.bashrc << 'EOF'
# GPU Monitor Auto-Recovery
if ! squeue -u "$USER" -n gpu-monitor -h 2>/dev/null | grep -q gpu-monitor; then
    sbatch /path/to/gpu_monitor_job.sh hpcc >/dev/null 2>&1
fi
EOF
```

**Management:**
```bash
squeue -u $USER -n gpu-monitor   # Check if running
tail -f ~/.gpu_monitor_slurm.log  # View logs
scancel -n gpu-monitor            # Stop
```

### Method 2: Screen Daemon (fallback, or non-Slurm servers)

```bash
curl -sL https://raw.githubusercontent.com/Gonglitian/gpu-monitor/main/setup.sh -o /tmp/gpu-monitor-setup.sh && bash /tmp/gpu-monitor-setup.sh <cluster> <github-token>
```

**Management:**
```bash
screen -r gpu-monitor              # View daemon logs
screen -S gpu-monitor -X quit      # Stop
cd ~/.gpu-monitor && git pull      # Update scripts
```

## Files

| File | Description |
|------|-------------|
| `index.html` | Dashboard frontend (GitHub Pages) |
| `collect.py` | Slurm data collector, pushes JSON via GitHub API |
| `daemon.sh` | Loop wrapper for screen/nohup mode |
| `setup.sh` | One-line remote setup (screen method) |
| `gpu_monitor_job.sh` | Slurm batch job wrapper (recommended) |
| `data/*.json` | Auto-updated cluster data (1-min intervals, 7-day history) |

## Adding a New Cluster

1. Add partition config in `collect.py` under `CLUSTER_CONFIG`
2. Add cluster name to `CLUSTERS` array in `index.html`
3. Deploy collector on the new cluster (Method 1 or 2)

## Data Format Specification

Each cluster pushes a JSON file to `data/<cluster>.json`. The dashboard reads this format directly — any server that produces conformant JSON will be rendered correctly.

### Top-level structure

```jsonc
{
  "cluster": "hpcc",                    // string, cluster identifier (must match filename)
  "timestamp": "2026-03-31T22:21:08Z",  // string, ISO 8601 UTC
  "nodes": [ ... ],                      // array of Node objects
  "pending_jobs": [ ... ],               // array of PendingJob objects
  "users": [ ... ],                      // array of UserSummary objects, sorted by running_gpus desc
  "summary": { ... },                    // Summary object
  "history": [ ... ]                     // array of HistoryPoint objects (appended by collector)
}
```

### Node

```jsonc
{
  "name": "gpu06",          // string, node hostname
  "gpu_model": "A100",      // string, uppercase model name (used for badge color: A100, H100, ADA6000, P100, ...)
  "total": 8,               // int, total GPU count on this node
  "used": 8,                // int, GPUs currently allocated (0 if state is "down")
  "state": "active",        // string, "active" | "down"
  "jobs": [                 // array of RunningJob objects (empty if down)
    {
      "user": "dwang177",                         // string, username
      "gpus": 1,                                   // int, GPUs allocated to this job
      "job_name": "sys-dashboard-sys-bc_jupyter",  // string, Slurm job name
      "elapsed": "4-05:04:36",                     // string, time elapsed (Slurm format: D-HH:MM:SS or HH:MM:SS)
      "time_limit": "7-00:00:00"                   // string, job time limit
    }
  ]
}
```

### PendingJob

```jsonc
{
  "user": "sitingl",                 // string, username
  "gpus": 1,                         // int, GPUs requested
  "job_name": "bash",                // string, Slurm job name
  "submit_time": "2026-03-31T10:45:53",  // string, ISO 8601 local time
  "reason": "Priority"               // string, Slurm pending reason
}
```

### UserSummary

```jsonc
{
  "user": "sitingl",       // string, username
  "running_gpus": 5,       // int, total GPUs currently in use
  "running_jobs": 5,       // int, number of running jobs
  "pending_jobs": 1        // int, number of pending jobs
}
```

### Summary

```jsonc
{
  "total": 60,            // int, total GPUs across all nodes (including down)
  "used": 33,             // int, GPUs currently allocated
  "free": 11,             // int, GPUs available (total - used - down)
  "down": 16,             // int, GPUs on down nodes
  "pending_jobs": 29,     // int, number of jobs in queue
  "pending_gpus": 325,    // int, total GPUs requested by pending jobs
  "active_users": 17      // int, number of users with running jobs
}
```

### HistoryPoint

Appended to the `history` array on each collection. Kept for 7 days (max 10080 points at 1-min intervals). Only contains summary-level data to keep file size manageable.

```jsonc
{
  "timestamp": "2026-03-31T22:21:08Z",  // string, ISO 8601 UTC
  "total": 60,
  "used": 33,
  "free": 11,
  "down": 16,
  "pending_jobs": 29,
  "pending_gpus": 325,
  "active_users": 17
}
```

### Notes for custom collectors

- The `collect.py` script handles fetching the existing JSON, appending to `history`, and pushing via GitHub API. If writing a custom collector for a non-Slurm cluster, you can either:
  - Fork `collect.py` and modify the data collection functions, keeping `push_to_github()` as-is
  - Generate the JSON externally and use the GitHub API to PUT it to `data/<cluster>.json` (you must manage `history` array appending yourself)
- `gpu_model` values are used as CSS class names for badge colors. Supported built-in colors: `A100`, `H100`, `ADA6000`, `P100`. Other values get a default gray badge.
- All timestamps should be UTC in ISO 8601 format
- The `cluster` field must match the filename (e.g., `"cluster": "bcc"` → `data/bcc.json`)
- Add new cluster names to the `CLUSTERS` array in `index.html` for the dashboard to show them

## Token Requirements

GitHub PAT (classic) with `repo` scope, or fine-grained token with Contents read/write on this repo.
