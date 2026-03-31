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
Server (screen daemon, every 1 min)
  └─ collect.py: sinfo/squeue → JSON → GitHub API PUT

GitHub Pages (static HTML)
  └─ index.html: fetch JSON from raw.githubusercontent.com → Chart.js render
```

No build step. No backend server. Data flows through GitHub as storage.

## Quick Setup (one-liner)

```bash
curl -sL https://raw.githubusercontent.com/Gonglitian/gpu-monitor/main/setup.sh -o /tmp/gpu-monitor-setup.sh && bash /tmp/gpu-monitor-setup.sh <cluster> <github-token>
```

Replace `<cluster>` with `hpcc` or `bcc`, and `<github-token>` with a GitHub PAT that has repo write access.

### What it does

1. Clones this repo to `~/.gpu-monitor/`
2. Saves token to `~/.gpu_monitor_env`
3. Starts a `screen` session (`gpu-monitor`) that collects data every 60s

### Management

```bash
screen -r gpu-monitor     # View daemon logs
screen -S gpu-monitor -X quit  # Stop
cd ~/.gpu-monitor && git pull   # Update scripts
```

## Files

| File | Description |
|------|-------------|
| `index.html` | Dashboard frontend (GitHub Pages) |
| `collect.py` | Slurm data collector, pushes JSON via GitHub API |
| `daemon.sh` | Loop wrapper, runs collect.py every 60s |
| `setup.sh` | One-line remote setup script |
| `data/*.json` | Auto-updated cluster data (1-min intervals, 7-day history) |

## Adding a New Cluster

1. Add partition config in `collect.py` under `CLUSTER_CONFIG`
2. Add cluster name to `CLUSTERS` array in `index.html`
3. Run setup on the new cluster

## Token Requirements

GitHub PAT (classic) with `repo` scope, or fine-grained token with Contents read/write on this repo.
