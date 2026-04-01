#!/bin/bash
#SBATCH -p batch
#SBATCH -c 1
#SBATCH --mem=512M
#SBATCH -t 7-00:00:00
#SBATCH -J gpu-monitor
#SBATCH -o /home/eegrad/lgong024/.gpu_monitor_slurm.log
#SBATCH --requeue

# GPU Monitor as a Slurm job - runs up to 7 days on BCC compute node
# Resubmits itself before expiring

CLUSTER="${1:-bcc}"
INTERVAL=60
SCRIPT_DIR="/home/eegrad/lgong024/proj/gpu-monitor"
ENV_FILE="$HOME/.gpu_monitor_env"

source "$ENV_FILE" 2>/dev/null
if [ -z "$GPU_MONITOR_TOKEN" ]; then
    echo "ERROR: GPU_MONITOR_TOKEN not set. Check $ENV_FILE"
    exit 1
fi

# Auto-resubmit before job ends (6 days 23 hours)
RESUBMIT_AFTER=$((6 * 24 * 3600 + 23 * 3600))
START_TIME=$(date +%s)

echo "[$(date)] GPU Monitor job started: cluster=$CLUSTER, node=$(hostname)"

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))
    if [ $ELAPSED -ge $RESUBMIT_AFTER ]; then
        echo "[$(date)] Approaching time limit, resubmitting..."
        sbatch "$SCRIPT_DIR/gpu_monitor_job.sh" "$CLUSTER"
        echo "[$(date)] Resubmitted. Exiting current job."
        exit 0
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Collecting $CLUSTER data..."
    if [ -f "$SCRIPT_DIR/collect.py" ]; then
        python3 "$SCRIPT_DIR/collect.py" --cluster "$CLUSTER" 2>&1
    else
        python3 "$SCRIPT_DIR/gpu_monitor_collect.py" --cluster "$CLUSTER" 2>&1
    fi

    sleep $INTERVAL
done
