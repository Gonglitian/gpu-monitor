#!/bin/bash
#SBATCH -c 1
#SBATCH --mem=512M
#SBATCH -J gpu-monitor
#SBATCH --requeue

# GPU Monitor Slurm Job — universal for all clusters
# Usage:
#   sbatch gpu_monitor_job.sh <cluster>    (submits with default partition/walltime)
#   bash  gpu_monitor_job.sh <cluster>     (auto-submits via sbatch with correct flags)

CLUSTER="${1:?Usage: sbatch gpu_monitor_job.sh <cluster>}"
INTERVAL=60

# --- Per-cluster configuration ---
case "$CLUSTER" in
    hpcc)
        PARTITION="epyc"
        WALLTIME="30-00:00:00"
        RESUBMIT_AFTER=$((29 * 24 * 3600 + 23 * 3600))  # 29d 23h
        SCRIPT_DIR="/rhome/lgong024/shared/bin"
        LOG_FILE="/rhome/lgong024/.gpu_monitor_slurm.log"
        ;;
    bcc)
        PARTITION="batch"
        WALLTIME="7-00:00:00"
        RESUBMIT_AFTER=$((6 * 24 * 3600 + 23 * 3600))   # 6d 23h
        SCRIPT_DIR="/home/eegrad/lgong024/proj/gpu-monitor"
        LOG_FILE="/home/eegrad/lgong024/.gpu_monitor_slurm.log"
        ;;
    *)
        echo "ERROR: Unknown cluster '$CLUSTER'. Add config in gpu_monitor_job.sh."
        exit 1
        ;;
esac

# If not inside a Slurm job, re-submit with correct partition/walltime
if [ -z "$SLURM_JOB_ID" ]; then
    echo "Submitting gpu-monitor job for $CLUSTER (partition=$PARTITION, walltime=$WALLTIME)..."
    sbatch --partition="$PARTITION" --time="$WALLTIME" --output="$LOG_FILE" \
        "$0" "$CLUSTER"
    exit $?
fi

# --- Running inside Slurm from here ---

# Load token
ENV_FILE="$HOME/.gpu_monitor_env"
source "$ENV_FILE" 2>/dev/null
if [ -z "$GPU_MONITOR_TOKEN" ]; then
    echo "ERROR: GPU_MONITOR_TOKEN not set. Check $ENV_FILE"
    exit 1
fi

# Prevent duplicate jobs: exit if another gpu-monitor job is already running
RUNNING=$(squeue -u "$USER" -n gpu-monitor -t R -h -o "%i" | grep -v "^${SLURM_JOB_ID}$" | head -1)
if [ -n "$RUNNING" ]; then
    echo "[$(date)] Another gpu-monitor job ($RUNNING) already running. Exiting."
    exit 0
fi

START_TIME=$(date +%s)
echo "[$(date)] GPU Monitor started: cluster=$CLUSTER, node=$(hostname), partition=$PARTITION, walltime=$WALLTIME"

while true; do
    ELAPSED=$(( $(date +%s) - START_TIME ))
    if [ $ELAPSED -ge $RESUBMIT_AFTER ]; then
        echo "[$(date)] Approaching time limit, resubmitting..."
        sbatch --partition="$PARTITION" --time="$WALLTIME" --output="$LOG_FILE" \
            "$SCRIPT_DIR/gpu_monitor_job.sh" "$CLUSTER"
        echo "[$(date)] Resubmitted. Exiting current job."
        exit 0
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Collecting $CLUSTER data..."
    python3 "$SCRIPT_DIR/collect.py" --cluster "$CLUSTER" 2>&1

    sleep $INTERVAL
done
