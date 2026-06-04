#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/dev/run_local_webhook_dev.sh [none|ngrok|cloudflared]

Environment:
  BUMPKIN_APP_WEBHOOK_SECRET    Required webhook secret
  BUMPKIN_APP_DB_PATH           Optional DB path (default: ./artifacts/app/bumpkin.sqlite3)
  BUMPKIN_APP_HOST              Optional bind host (default: 127.0.0.1)
  BUMPKIN_APP_PORT              Optional port (default: 8080)
  PYTHONPATH                    Optional Python path (default: src)

Examples:
  BUMPKIN_APP_WEBHOOK_SECRET=dev-secret scripts/dev/run_local_webhook_dev.sh ngrok
  BUMPKIN_APP_WEBHOOK_SECRET=dev-secret scripts/dev/run_local_webhook_dev.sh cloudflared
  BUMPKIN_APP_WEBHOOK_SECRET=dev-secret scripts/dev/run_local_webhook_dev.sh none
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "${BUMPKIN_APP_WEBHOOK_SECRET:-}" ]]; then
  echo "Error: BUMPKIN_APP_WEBHOOK_SECRET is required." >&2
  exit 2
fi

TUNNEL_PROVIDER="${1:-none}"
case "$TUNNEL_PROVIDER" in
  none|ngrok|cloudflared) ;;
  *)
    echo "Error: invalid provider '$TUNNEL_PROVIDER' (expected none|ngrok|cloudflared)." >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"
RUNNER_PATH="$SCRIPT_DIR/../run_app_server.py"
HOST="${BUMPKIN_APP_HOST:-127.0.0.1}"
PORT="${BUMPKIN_APP_PORT:-8080}"
export BUMPKIN_APP_DB_PATH="${BUMPKIN_APP_DB_PATH:-./artifacts/app/bumpkin.sqlite3}"
export PYTHONPATH="${PYTHONPATH:-src}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    echo "Error: neither 'python' nor 'python3' was found in PATH." >&2
    exit 2
  fi
fi

mkdir -p "$(dirname "$BUMPKIN_APP_DB_PATH")"

SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "Starting local app server on http://$HOST:$PORT ..."
"$PYTHON_BIN" "$RUNNER_PATH" &
SERVER_PID="$!"

sleep 1
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "http://$HOST:$PORT/healthz" >/dev/null 2>&1; then
    echo "Health check passed: http://$HOST:$PORT/healthz"
  else
    echo "Warning: health check failed (server may still be starting)." >&2
  fi
fi

case "$TUNNEL_PROVIDER" in
  none)
    echo
    echo "Server running locally."
    echo "If you need a public URL, run one of:"
    echo "  ngrok http $PORT"
    echo "  cloudflared tunnel --url http://$HOST:$PORT"
    wait "$SERVER_PID"
    ;;
  ngrok)
    if ! command -v ngrok >/dev/null 2>&1; then
      echo "Error: ngrok is not installed." >&2
      exit 2
    fi
    echo "Starting ngrok tunnel..."
    ngrok http "$PORT"
    ;;
  cloudflared)
    if ! command -v cloudflared >/dev/null 2>&1; then
      echo "Error: cloudflared is not installed." >&2
      exit 2
    fi
    echo "Starting cloudflared tunnel..."
    cloudflared tunnel --url "http://$HOST:$PORT"
    ;;
esac
