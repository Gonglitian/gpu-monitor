#!/usr/bin/env python3
"""
GPU Monitor Data Collector
Collects GPU allocation status via Slurm and pushes JSON to GitHub.

Usage:
    gpu_monitor_collect.py --cluster hpcc
    gpu_monitor_collect.py --cluster bcc

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

# Cluster-specific Slurm partition config
CLUSTER_CONFIG = {
    "hpcc": {
        "partitions": "gpu,short_gpu,preempt_gpu",
    },
    "bcc": {
        "partitions": "gpu",
    },
}


def run_cmd(cmd):
    """Run shell command, return stdout or empty string on failure."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return r.stdout.strip()
    except Exception:
        return ""


def parse_gpu_count(gres_str):
    """Parse GPU count from gres string like 'gres/gpu:a100:2', 'gpu:7(S:0-1)', 'gres/gpu:1'."""
    if not gres_str:
        return 0
    # Strip trailing socket info like (S:0-1)
    clean = re.sub(r"\(.*?\)", "", gres_str)
    m = re.search(r"(\d+)$", clean)
    if m:
        return int(m.group(1))
    # If no number at end (e.g. "gres/gpu:a100"), assume 1
    if "gpu" in gres_str:
        return 1
    return 0


def collect_gpu_status(cluster):
    """Collect GPU allocation status from Slurm."""
    cfg = CLUSTER_CONFIG[cluster]
    partitions = cfg["partitions"]

    # ---- Node-level GPU info ----
    nodes_raw = run_cmd(f'sinfo -N -p "{partitions}" -h -o "%N" | sort -u')
    if not nodes_raw:
        print("ERROR: sinfo returned no nodes", file=sys.stderr)
        return None

    nodes = nodes_raw.split("\n")
    node_data = []

    for node in nodes:
        node = node.strip()
        if not node:
            continue

        gres = run_cmd(
            f'sinfo -N -p "{partitions}" -n "{node}" -h -o "%G" | head -1'
        )
        if not gres or gres == "(null)":
            continue

        # Strip socket info like (S:0-1) before parsing
        gres_clean = re.sub(r"\(.*?\)", "", gres)
        total_match = re.search(r"(\d+)$", gres_clean)
        if not total_match:
            continue
        total = int(total_match.group(1))
        if total == 0:
            continue

        parts = gres_clean.split(":")
        gpu_model = parts[1].upper() if len(parts) >= 3 else "GPU"

        state = run_cmd(f'sinfo -n "{node}" -h -o "%t" | head -1')
        if "down" in state or "drain" in state:
            node_data.append({
                "name": node, "gpu_model": gpu_model,
                "total": total, "used": 0, "state": "down", "jobs": [],
            })
            continue

        # Get per-job detail on this node
        jobs_raw = run_cmd(
            f'squeue -w "{node}" -h -t R -o "%u|%b|%j|%M|%l"'
        )
        node_jobs = []
        used = 0
        for line in jobs_raw.split("\n"):
            if not line.strip():
                continue
            fields = line.split("|")
            if len(fields) < 5:
                continue
            user, gres_req, jobname, elapsed, timelimit = fields[:5]
            gpus = parse_gpu_count(gres_req)
            used += gpus
            node_jobs.append({
                "user": user,
                "gpus": gpus,
                "job_name": jobname,
                "elapsed": elapsed,
                "time_limit": timelimit,
            })

        node_data.append({
            "name": node, "gpu_model": gpu_model,
            "total": total, "used": used, "state": "active",
            "jobs": node_jobs,
        })

    # ---- Pending (queued) jobs ----
    pending_raw = run_cmd(
        f'squeue -p "{partitions}" -t PD -h -o "%u|%b|%j|%V|%r"'
    )
    pending_jobs = []
    for line in pending_raw.split("\n"):
        if not line.strip():
            continue
        fields = line.split("|")
        if len(fields) < 5:
            continue
        user, gres_req, jobname, submit_time, reason = fields[:5]
        gpus = parse_gpu_count(gres_req)
        pending_jobs.append({
            "user": user,
            "gpus": gpus,
            "job_name": jobname,
            "submit_time": submit_time,
            "reason": reason,
        })

    # ---- Per-user summary ----
    user_gpus = {}  # user -> {"running_gpus": N, "running_jobs": N, "pending_jobs": N}
    for nd in node_data:
        for job in nd.get("jobs", []):
            u = job["user"]
            if u not in user_gpus:
                user_gpus[u] = {"running_gpus": 0, "running_jobs": 0, "pending_jobs": 0}
            user_gpus[u]["running_gpus"] += job["gpus"]
            user_gpus[u]["running_jobs"] += 1

    for pj in pending_jobs:
        u = pj["user"]
        if u not in user_gpus:
            user_gpus[u] = {"running_gpus": 0, "running_jobs": 0, "pending_jobs": 0}
        user_gpus[u]["pending_jobs"] += 1

    # Sort by running_gpus descending
    users = [
        {"user": u, **stats}
        for u, stats in sorted(user_gpus.items(), key=lambda x: x[1]["running_gpus"], reverse=True)
    ]

    # ---- Summary ----
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total_gpus = sum(n["total"] for n in node_data)
    used_gpus = sum(n["used"] for n in node_data if n["state"] == "active")
    down_gpus = sum(n["total"] for n in node_data if n["state"] == "down")

    snapshot = {
        "cluster": cluster,
        "timestamp": now,
        "nodes": node_data,
        "pending_jobs": pending_jobs,
        "users": users,
        "summary": {
            "total": total_gpus,
            "used": used_gpus,
            "free": total_gpus - used_gpus - down_gpus,
            "down": down_gpus,
            "pending_jobs": len(pending_jobs),
            "pending_gpus": sum(pj["gpus"] for pj in pending_jobs),
            "active_users": sum(1 for u in users if u["running_gpus"] > 0),
        },
    }
    return snapshot


def github_api(method, path, token, data=None):
    """Call GitHub API via curl (more portable than requests)."""
    url = f"https://api.github.com{path}"
    cmd = [
        "curl", "-s", "-X", method,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2022-11-28",
        url,
    ]
    if data is not None:
        cmd += ["-d", json.dumps(data)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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

    # Append history point (compact, no per-user detail)
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
    parser = argparse.ArgumentParser(description="GPU Monitor Collector")
    parser.add_argument("--cluster", required=True, choices=["hpcc", "bcc"])
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
