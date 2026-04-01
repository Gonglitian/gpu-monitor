#!/bin/bash
# GPU Monitor Daemon - runs in tmux/screen
# Usage: nohup gpu_monitor_daemon.sh &  OR  tmux new -d -s gpu-monitor 'gpu_monitor_daemon.sh'
# To stop: kill the tmux session or touch /tmp/gpu_monitor_stop

CLUSTER="${1:-hpcc}"
INTERVAL=60  # 1 minute
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$HOME/.gpu_monitor_env"

source "$ENV_FILE" 2>/dev/null
if [ -z "$GPU_MONITOR_TOKEN" ]; then
    echo "ERROR: GPU_MONITOR_TOKEN not set. Check $ENV_FILE"
    exit 1
fi

echo "GPU Monitor daemon started: cluster=$CLUSTER, interval=${INTERVAL}s"
echo "Stop with: tmux kill-session -t gpu-monitor  OR  touch /tmp/gpu_monitor_stop"

# Local (non-Slurm) clusters use collect_local.py
LOCAL_CLUSTERS="tasl"

while true; do
    [ -f /tmp/gpu_monitor_stop ] && echo "Stop file found, exiting." && rm /tmp/gpu_monitor_stop && break

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Collecting $CLUSTER data..."
    if echo "$LOCAL_CLUSTERS" | grep -qw "$CLUSTER"; then
        python3 "$SCRIPT_DIR/collect_local.py" --cluster "$CLUSTER" 2>&1
    elif [ -f "$SCRIPT_DIR/collect.py" ]; then
        python3 "$SCRIPT_DIR/collect.py" --cluster "$CLUSTER" 2>&1
    else
        python3 "$SCRIPT_DIR/gpu_monitor_collect.py" --cluster "$CLUSTER" 2>&1
    fi

    sleep $INTERVAL
done
