#!/usr/bin/env python3
"""
GPU Monitor Data Collector
Collects GPU allocation status via Slurm and pushes JSON to GitHub.

Usage:
    gpu_monitor_collect.py --cluster hpcc
    gpu_monitor_collect.py --cluster bcc

Env vars required:
    GPU_MONITOR_TOKEN  - GitHub Personal Access Token (fine-grained, contents read/write)
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


def collect_gpu_status(cluster):
    """Collect GPU allocation status from Slurm."""
    cfg = CLUSTER_CONFIG[cluster]
    partitions = cfg["partitions"]

    # Get unique node list
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

        # Get GRES info: gpu:a100:8, gpu:p100:2, etc.
        gres = run_cmd(
            f'sinfo -N -p "{partitions}" -n "{node}" -h -o "%G" | head -1'
        )

        if not gres or gres == "(null)":
            continue

        # Extract total GPU count (last number)
        total_match = re.search(r"(\d+)$", gres)
        if not total_match:
            continue
        total = int(total_match.group(1))
        if total == 0:
            continue

        # Extract GPU model
        parts = gres.split(":")
        gpu_model = parts[1].upper() if len(parts) >= 3 else "GPU"

        # Check node state
        state = run_cmd(f'sinfo -n "{node}" -h -o "%t" | head -1')
        if "down" in state or "drain" in state:
            node_data.append({
                "name": node,
                "gpu_model": gpu_model,
                "total": total,
                "used": 0,
                "state": "down",
            })
            continue

        # Count used GPUs from running jobs
        used_raw = run_cmd(
            f'squeue -w "{node}" -h -t R -o "%b" '
            "| awk -F: '{n=$NF; if(n~/^[0-9]+$/) sum+=n; else sum+=1} END{print sum+0}'"
        )
        used = int(used_raw) if used_raw.isdigit() else 0

        node_data.append({
            "name": node,
            "gpu_model": gpu_model,
            "total": total,
            "used": used,
            "state": "active",
        })

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    total_gpus = sum(n["total"] for n in node_data)
    used_gpus = sum(n["used"] for n in node_data if n["state"] == "active")
    down_gpus = sum(n["total"] for n in node_data if n["state"] == "down")

    snapshot = {
        "cluster": cluster,
        "timestamp": now,
        "nodes": node_data,
        "summary": {
            "total": total_gpus,
            "used": used_gpus,
            "free": total_gpus - used_gpus - down_gpus,
            "down": down_gpus,
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

    # Fetch existing file
    existing = github_api("GET", api_path, token)
    sha = existing.get("sha")

    history = []
    if "content" in existing:
        try:
            old_data = json.loads(base64.b64decode(existing["content"]))
            history = old_data.get("history", [])
        except Exception:
            pass

    # Append new history point
    history.append({
        "timestamp": snapshot["timestamp"],
        "total": snapshot["summary"]["total"],
        "used": snapshot["summary"]["used"],
        "free": snapshot["summary"]["free"],
        "down": snapshot["summary"]["down"],
    })

    # Trim history
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    snapshot["history"] = history

    # Push to GitHub
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
