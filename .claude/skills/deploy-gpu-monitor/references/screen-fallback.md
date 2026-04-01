# Screen Daemon Fallback

Use this method when compute nodes cannot reach GitHub (outbound HTTPS blocked) or when Slurm is unavailable.

## Setup

```bash
# 1. Save token
echo 'export GPU_MONITOR_TOKEN="ghp_XXXXX"' > ~/.gpu_monitor_env
chmod 600 ~/.gpu_monitor_env

# 2. Start screen daemon on login node
screen -dmS gpu-monitor bash /path/to/gpu_monitor_daemon.sh <cluster>

# 3. Verify
screen -ls   # Should show gpu-monitor session
```

## Management

```bash
screen -r gpu-monitor              # Attach to see logs
# Ctrl-A D to detach
screen -S gpu-monitor -X quit      # Stop
```

## Known issue: systemd-tmpfiles-clean

On RHEL/Rocky systems, `systemd-tmpfiles-clean` runs daily and may remove screen socket files from `/run/screen/`. This kills the screen session.

Mitigation: add auto-recovery to `.bashrc`:
```bash
if [[ -z "$STY" ]] && ! screen -ls gpu-monitor 2>/dev/null | grep -q gpu-monitor; then
    rm -f /tmp/gpu_monitor_stop
    screen -dmS gpu-monitor bash /path/to/gpu_monitor_daemon.sh <cluster> 2>/dev/null
fi
```

This checks on every login and restarts if needed. Not as reliable as the Slurm job method, but works for environments where Slurm jobs can't reach the network.

## One-liner setup (alternative)

For quick remote setup, use the setup script:
```bash
curl -sL https://raw.githubusercontent.com/Gonglitian/gpu-monitor/main/setup.sh \
  -o /tmp/gpu-monitor-setup.sh && bash /tmp/gpu-monitor-setup.sh <cluster> <token>
```
This clones the repo, saves the token, and starts the screen daemon.
