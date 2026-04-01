#!/usr/bin/env python3
"""
GPU Monitor Data Collector — Local (non-Slurm) servers.
Uses nvidia-smi to collect GPU status and maps processes to users via ps.

Usage:
    collect_local.py --cluster tasl
    collect_local.py --cluster tasl --dry-run

Env vars required:
    GPU_MONITOR_TOKEN  - GitHub Personal Access Token
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# --- Config ---
REPO = "Gonglitian/gpu-monitor"
BRANCH = "main"
DATA_DIR = "data"
MAX_HISTORY = 10080  # 1 week at 1-min intervals

# Local cluster config: node_name and GPU model override (optional)
CLUSTER_CONFIG = {
    "tasl": {
        "node_name": "TASL",
    },
}


def run_cmd(cmd):
    """Run shell command, return stdout or empty string on failure."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return ""


def get_pid_user(pid):
    """Get username for a PID."""
    user = run_cmd(f"ps -o user= -p {pid}")
    return user.strip() if user else None


def collect_gpu_status(cluster):
    """Collect GPU allocation status via nvidia-smi."""
    cfg = CLUSTER_CONFIG[cluster]
    node_name = cfg["node_name"]

    # Query GPU info: index, uuid, name, memory
    gpu_info_raw = run_cmd(
        'nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total --format=csv,noheader,nounits'
    )
    if not gpu_info_raw:
        print("ERROR: nvidia-smi returned no GPUs", file=sys.stderr)
        return None

    # Parse GPU list
    gpus = []
    for line in gpu_info_raw.split("\n"):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        gpus.append({
            "index": int(parts[0]),
            "uuid": parts[1],
            "name": parts[2],
            "mem_used": int(parts[3]),
            "mem_total": int(parts[4]),
        })

    if not gpus:
        return None

    total = len(gpus)

    # Derive model label for badge (e.g. "NVIDIA RTX 6000 Ada Generation" -> "ADA6000")
    raw_name = gpus[0]["name"]
    if "ada" in raw_name.lower() and "6000" in raw_name:
        gpu_model = "ADA6000"
    elif "a100" in raw_name.lower():
        gpu_model = "A100"
    elif "h100" in raw_name.lower():
        gpu_model = "H100"
    elif "p100" in raw_name.lower():
        gpu_model = "P100"
    elif "k80" in raw_name.lower():
        gpu_model = "K80"
    elif "4090" in raw_name.lower():
        gpu_model = "RTX4090"
    elif "3090" in raw_name.lower():
        gpu_model = "RTX3090"
    else:
        gpu_model = "GPU"

    # Build uuid -> gpu_index map
    uuid_to_idx = {g["uuid"]: g["index"] for g in gpus}

    # Query running compute processes: pid, gpu_uuid, used_memory
    procs_raw = run_cmd(
        'nvidia-smi --query-compute-apps=pid,gpu_uuid,used_memory --format=csv,noheader'
    )

    # Map: gpu_index -> list of {user, pid, mem}
    gpu_procs = {i: [] for i in range(total)}
    for line in procs_raw.split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        pid = parts[0]
        uuid = parts[1]
        mem = parts[2]
        user = get_pid_user(pid)
        if not user:
            continue
        idx = uuid_to_idx.get(uuid)
        if idx is None:
            continue
        gpu_procs[idx].append({"user": user, "pid": pid, "mem": mem})

    # Determine which GPUs are "used" (have at least one compute process)
    gpu_used = set()
    for idx, procs in gpu_procs.items():
        if procs:
            gpu_used.add(idx)

    used = len(gpu_used)

    # Aggregate per-user: which GPUs each user occupies
    user_gpu_set = {}  # user -> set of gpu indices
    for idx, procs in gpu_procs.items():
        for p in procs:
            u = p["user"]
            if u not in user_gpu_set:
                user_gpu_set[u] = set()
            user_gpu_set[u].add(idx)

    # Build job list (one "job" per user on this node, showing GPU count)
    node_jobs = []
    for u, idxs in sorted(user_gpu_set.items(), key=lambda x: len(x[1]), reverse=True):
        # Try to get the main process command for this user
        sample_pid = None
        for idx in idxs:
            for p in gpu_procs[idx]:
                if p["user"] == u:
                    sample_pid = p["pid"]
                    break
            if sample_pid:
                break
        job_name = ""
        elapsed = ""
        if sample_pid:
            job_name = run_cmd(f"ps -o comm= -p {sample_pid}") or ""
            # Get process elapsed time
            elapsed = run_cmd(f"ps -o etime= -p {sample_pid}").strip() or ""

        node_jobs.append({
            "user": u,
            "gpus": len(idxs),
            "job_name": job_name,
            "elapsed": elapsed,
            "time_limit": "",
        })

    # Per-GPU detail (memory)
    gpu_details = []
    for g in gpus:
        idx = g["index"]
        users_on_gpu = list({p["user"] for p in gpu_procs.get(idx, [])})
        gpu_details.append({
            "index": idx,
            "mem_used": g["mem_used"],
            "mem_total": g["mem_total"],
            "users": users_on_gpu,
        })

    node_data = [{
        "name": node_name,
        "gpu_model": gpu_model,
        "total": total,
        "used": used,
        "state": "active",
        "jobs": node_jobs,
        "gpu_details": gpu_details,
    }]

    # Per-user summary
    users = [
        {
            "user": u,
            "running_gpus": len(idxs),
            "running_jobs": 1,
            "pending_jobs": 0,
        }
        for u, idxs in sorted(user_gpu_set.items(), key=lambda x: len(x[1]), reverse=True)
    ]

    # Summary
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = {
        "cluster": cluster,
        "timestamp": now,
        "nodes": node_data,
        "pending_jobs": [],
        "users": users,
        "summary": {
            "total": total,
            "used": used,
            "free": total - used,
            "down": 0,
            "pending_jobs": 0,
            "pending_gpus": 0,
            "active_users": len(user_gpu_set),
        },
    }
    return snapshot


def github_api(method, path, token, data=None):
    """Call GitHub API via curl."""
    url = f"https://api.github.com{path}"
    cmd = [
        "curl", "-s", "-X", method,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        url,
    ]
    stdin_data = None
    if data is not None:
        cmd += ["-d", "@-"]
        stdin_data = json.dumps(data)

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                       input=stdin_data)
    if r.stdout:
        return json.loads(r.stdout)
    return {}


def push_to_github(snapshot, cluster, token):
    """Fetch existing data, append history, push updated JSON."""
    file_path = f"{DATA_DIR}/{cluster}.json"
    api_path = f"/repos/{REPO}/contents/{file_path}"

    existing = github_api("GET", api_path, token)
    sha = existing.get("sha")

    history = []
    if "content" in existing:
        try:
            old_data = json.loads(base64.b64decode(existing["content"]))
            history = old_data.get("history", [])
        except Exception:
            pass

    history.append({
        "timestamp": snapshot["timestamp"],
        "total": snapshot["summary"]["total"],
        "used": snapshot["summary"]["used"],
        "free": snapshot["summary"]["free"],
        "down": snapshot["summary"]["down"],
        "pending_jobs": snapshot["summary"]["pending_jobs"],
        "pending_gpus": snapshot["summary"]["pending_gpus"],
        "active_users": snapshot["summary"]["active_users"],
    })

    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    snapshot["history"] = history

    content_b64 = base64.b64encode(
        json.dumps(snapshot, indent=2).encode()
    ).decode()

    payload = {
        "message": f"gpu-monitor: update {cluster} data",
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    result = github_api("PUT", api_path, token, payload)

    if "content" in result:
        print(f"OK: pushed {cluster}.json ({len(history)} history points)")
        return True
    else:
        print(f"ERROR: {result.get('message', 'unknown error')}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="GPU Monitor Local Collector")
    parser.add_argument("--cluster", required=True, choices=list(CLUSTER_CONFIG.keys()))
    parser.add_argument("--dry-run", action="store_true", help="Print JSON without pushing")
    args = parser.parse_args()

    snapshot = collect_gpu_status(args.cluster)
    if not snapshot:
        sys.exit(1)

    if args.dry_run:
        print(json.dumps(snapshot, indent=2))
        return

    token = os.environ.get("GPU_MONITOR_TOKEN")
    if not token:
        print("ERROR: set GPU_MONITOR_TOKEN env var", file=sys.stderr)
        sys.exit(1)

    push_to_github(snapshot, args.cluster, token)


if __name__ == "__main__":
    main()
