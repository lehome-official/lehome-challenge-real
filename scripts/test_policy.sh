#!/usr/bin/env bash
# test_policy.sh — one-script smoke test for a LeHome policy server Docker image.
#
# Usage:
#   bash scripts/test_policy.sh <docker-image-name> [port]
#
# Examples:
#   bash scripts/test_policy.sh lehome-policy-myteam
#   bash scripts/test_policy.sh lehome-policy-myteam 8081   # custom port
#
# What it does:
#   1. Starts your Docker image with the given port mapped.
#   2. Waits up to 20 s for "listening" to appear in the logs.
#   3. Runs Stage 1 (handshake) then Stage 2 (obs→action loop).
#   4. Stops the container and prints a final PASS / FAIL.
#
# Requirements (on the host):
#   - Docker
#   - Python 3 with grpcio, numpy, torch  (pip install grpcio numpy torch)

set -euo pipefail

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
IMAGE="${1:-}"
PORT="${2:-8080}"

if [[ -z "$IMAGE" ]]; then
    echo "Usage: bash scripts/test_policy.sh <docker-image-name> [port]"
    echo "Example: bash scripts/test_policy.sh lehome-policy-myteam"
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEST_CLIENT="$REPO_ROOT/docker/policy_server/test_client.py"
SERVER_ADDR="localhost:${PORT}"

# ---------------------------------------------------------------------------
# Cleanup on exit
# ---------------------------------------------------------------------------
CONTAINER_ID=""
cleanup() {
    if [[ -n "$CONTAINER_ID" ]]; then
        echo ""
        echo "[test_policy] Stopping container ${CONTAINER_ID:0:12} ..."
        docker stop "$CONTAINER_ID" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Start Docker
# ---------------------------------------------------------------------------
echo "========================================================"
echo "  LeHome Policy Server Test"
echo "  Image   : $IMAGE"
echo "  Port    : $PORT"
echo "========================================================"
echo ""
echo "[test_policy] Starting container ..."

CONTAINER_ID=$(docker run --rm -d -p "${PORT}:8080" "$IMAGE")
echo "[test_policy] Container: ${CONTAINER_ID:0:12}"

# ---------------------------------------------------------------------------
# Wait for server to be ready
# ---------------------------------------------------------------------------
echo "[test_policy] Waiting for server (up to 20 s) ..."
READY=0
for i in $(seq 1 40); do
    if docker logs "$CONTAINER_ID" 2>&1 | grep -q "listening"; then
        READY=1
        break
    fi
    sleep 0.5
done

if [[ $READY -eq 0 ]]; then
    echo ""
    echo "[test_policy] ERROR: Server did not print 'listening' within 20 s."
    echo "  Container logs:"
    docker logs "$CONTAINER_ID" 2>&1 | tail -20 | sed 's/^/    /'
    echo ""
    echo "RESULT: FAIL — server did not start correctly."
    exit 1
fi

echo "[test_policy] Server is up. Running tests ..."
echo ""

# ---------------------------------------------------------------------------
# Resolve Python interpreter — prefer the project venv, fall back to PATH
# ---------------------------------------------------------------------------
REPO_VENV="$REPO_ROOT/.venv/bin/python"
if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x "$REPO_VENV" ]]; then
        PYTHON="$REPO_VENV"
        echo "[test_policy] Using venv Python: $PYTHON"
    else
        PYTHON="python3"
        echo "[test_policy] Using system Python: $(which python3 2>/dev/null || echo 'python3 not found')"
        echo "[test_policy] If this fails, install deps: pip install grpcio>=1.73.1 numpy torch"
    fi
fi

set +e   # allow test script to return non-zero without killing this script

"$PYTHON" "$TEST_CLIENT" \
    --server_addr="$SERVER_ADDR" \
    --stage=2 \
    --n_steps=5 \
    --actions_per_chunk=20
TEST_EXIT=$?

set -e

# ---------------------------------------------------------------------------
# Final result
# ---------------------------------------------------------------------------
echo ""
if [[ $TEST_EXIT -eq 0 ]]; then
    echo "========================================================"
    echo "  RESULT: PASS — image '$IMAGE' is ready for submission."
    echo "========================================================"
else
    echo "========================================================"
    echo "  RESULT: FAIL — fix the errors above and re-run."
    echo "  Tip: check server logs with:"
    echo "    docker logs ${CONTAINER_ID:0:12}"
    echo "========================================================"
fi

exit $TEST_EXIT
