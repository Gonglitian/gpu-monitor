#!/bin/bash
# GPU Monitor one-line setup
# Usage: ./setup.sh <cluster> <token>
# Example: ./setup.sh bcc ghp_xxxxx

set -e
CLUSTER="${1:?Usage: $0 <cluster> <token>}"
TOKEN="${2:?Usage: $0 <cluster> <token>}"
DIR="$HOME/.gpu-monitor"

# Clone or update
if [ -d "$DIR" ]; then
    cd "$DIR" && git pull --quiet
else
    git clone --depth 1 https://github.com/Gonglitian/gpu-monitor.git "$DIR"
fi

# Save token
echo "export GPU_MONITOR_TOKEN=\"$TOKEN\"" > "$HOME/.gpu_monitor_env"
chmod 600 "$HOME/.gpu_monitor_env"

# Make executable
chmod +x "$DIR/daemon.sh" "$DIR/collect.py"

# Restart screen session
screen -S gpu-monitor -X quit 2>/dev/null || true
sleep 1
screen -dmS gpu-monitor "$DIR/daemon.sh" "$CLUSTER"

echo "Done! '$CLUSTER' monitor running (1-min interval)"
echo "  View:   screen -r gpu-monitor"
echo "  Stop:   screen -S gpu-monitor -X quit"
echo "  Update: cd $DIR && git pull"
