#!/usr/bin/env bash
# start_eval_client.sh — wrapper that sources the project venv and robot.env,
# then launches eval_client.py with sane defaults from environment variables.
#
# Usage:
#   export TEAM=myteam          # required
#   export TASK="Fold the Garment"
#   export N_EPISODES=2
#   export EPISODE_DURATION=60
#   bash scripts/start_eval_client.sh
#
# All variables can be overridden on the command line:
#   TEAM=myteam N_EPISODES=3 bash scripts/start_eval_client.sh
sudo usbreset 2bc5:066b

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Activate virtual environment
# ---------------------------------------------------------------------------
VENV="$REPO_ROOT/.venv/bin/activate"
if [[ -f "$VENV" ]]; then
    source "$VENV"
else
    echo "[start_eval_client] ERROR: .venv not found."
    echo "  Run:  uv venv --python 3.12 && uv pip install -e './third_party/lerobot[all]'"
    exit 1
fi

# ---------------------------------------------------------------------------
# Source robot hardware configuration
# ---------------------------------------------------------------------------
ROBOT_ENV="$REPO_ROOT/robot.env"
if [[ -f "$ROBOT_ENV" ]]; then
    source "$ROBOT_ENV"
    echo "[start_eval_client] Loaded robot.env"
else
    echo "[start_eval_client] WARNING: robot.env not found."
    echo "  Copy robot.env.template → robot.env and fill in your device paths."
    echo "  Continuing — port/camera args must be passed on the command line or already exported."
fi

# ---------------------------------------------------------------------------
# Session parameters (all can be overridden by exporting before calling)
# ---------------------------------------------------------------------------
export TEAM="${TEAM:-test_run}"
export TASK="${TASK:-Fold the Garment}"
export N_EPISODES="${N_EPISODES:-2}"
export EPISODE_DURATION="${EPISODE_DURATION:-60}"
export SERVER_ADDR="${SERVER_ADDR:-localhost:8080}"
export FPS="${FPS:-30}"
export ACTIONS_PER_CHUNK="${ACTIONS_PER_CHUNK:-20}"
export DISPLAY="${DISPLAY:-:0}"    # required for pynput under Wayland/headless

echo ""
echo "========================================================"
echo "  LeHome Hardware Evaluation"
echo "  Team     : $TEAM"
echo "  Task     : $TASK"
echo "  Episodes : $N_EPISODES  x  ${EPISODE_DURATION}s"
echo "  Server   : $SERVER_ADDR"
echo "========================================================"
echo ""

python "$REPO_ROOT/scripts/eval_client.py" "$@"
