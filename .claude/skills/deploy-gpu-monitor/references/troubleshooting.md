# Troubleshooting GPU Monitor

## Data not updating

1. **Check if the Slurm job is running:**
   ```bash
   squeue -u $USER -n gpu-monitor
   ```
   If empty, the job died. Resubmit:
   ```bash
   sbatch /path/to/gpu_monitor_job.sh <cluster>
   ```

2. **Check the log:**
   ```bash
   tail -50 ~/.gpu_monitor_slurm.log
   ```
   Look for: Python errors, network errors, GitHub API errors.

3. **Test collection manually:**
   ```bash
   source ~/.gpu_monitor_env
   python3 /path/to/gpu_monitor_collect.py --cluster <cluster> --dry-run
   ```

4. **Test GitHub API access from compute node:**
   ```bash
   srun -p epyc -c 1 --mem=512M -t 5:00 bash -c 'curl -s -o /dev/null -w "%{http_code}" https://api.github.com/zen'
   ```
   Should return `200`. If not, compute nodes may block outbound HTTPS.

## Common errors in logs

### "sinfo returned no nodes"
Wrong partition name in `CLUSTER_CONFIG`. Fix:
```bash
sinfo -o "%P %G" | grep gpu   # Find correct partition names
```
Then update `CLUSTER_CONFIG` in `gpu_monitor_collect.py`.

### "Resource not accessible by personal access token"
Token lacks permissions. Requirements:
- Classic PAT: needs `repo` scope
- Fine-grained PAT: needs Contents read/write on `Gonglitian/gpu-monitor`

Check token:
```bash
source ~/.gpu_monitor_env
curl -s -H "Authorization: Bearer $GPU_MONITOR_TOKEN" https://api.github.com/repos/Gonglitian/gpu-monitor | grep full_name
```

### "422 Unprocessable Entity" or SHA mismatch
Usually means the data file was updated by another collector between fetch and push. Self-resolves on the next cycle (60s). If persistent, check if two collectors are running for the same cluster.

### Python file not found
`SCRIPT_DIR` in `gpu_monitor_job.sh` is wrong. Slurm copies the batch script to a spool directory, so `$(dirname "$0")` doesn't work. Must use an absolute path:
```bash
SCRIPT_DIR="/rhome/lgong024/shared/bin"  # Hardcoded absolute path
```

## Job keeps dying

- **Node went down for maintenance**: Job gets requeued if `--requeue` is set (it is by default). Check `sacct -j <jobid> --format=State`.
- **OOM**: Unlikely with 512M for this workload, but check `sacct -j <jobid> --format=MaxRSS`.
- **Walltime expired**: The job auto-resubmits at 29d23h. If it didn't, the resubmit itself may have failed. Check log for "resubmitting" message.

## Screen fallback (non-Slurm or blocked network)

If compute nodes can't reach GitHub, run on the login node:
```bash
screen -dmS gpu-monitor bash /path/to/gpu_monitor_daemon.sh <cluster>
```
Caveat: `systemd-tmpfiles-clean` may kill the screen socket daily. Add auto-recovery to `.bashrc`:
```bash
if [[ -z "$STY" ]] && ! screen -ls gpu-monitor 2>/dev/null | grep -q gpu-monitor; then
    screen -dmS gpu-monitor bash /path/to/gpu_monitor_daemon.sh <cluster> 2>/dev/null
fi
```
