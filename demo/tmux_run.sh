#!/usr/bin/env bash
# Two-pane Sidecar demo: remote brain on the left, local hands on the right.
# Usage: bash demo/tmux_run.sh [--no-attach]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${SIDECAR_DEMO_PROFILE:-sidecar-test}"
PORT="${SIDECAR_DEMO_PORT:-8798}"
WS="${SIDECAR_DEMO_WORKSPACE:-$ROOT}"
SESSION="${SIDECAR_DEMO_SESSION:-sidecar-demo}"
HERMES="${HERMES_BIN:-/Users/shakti/.local/bin/hermes}"
ATTACH=1
[[ "${1:-}" == "--no-attach" ]] && ATTACH=0

token_file="$HOME/.hermes/profiles/$PROFILE/plugin-data/sidecar/token"
if [[ ! -s "$token_file" ]]; then
  "$HERMES" -p "$PROFILE" sidecar pair --json >/dev/null
fi
TOKEN="$(cat "$token_file")"

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -x 138 -y 40
tmux split-window -h -t "$SESSION"
tmux resize-pane -t "$SESSION:0.0" -x 64 || true
tmux resize-pane -t "$SESSION:0.1" -x 74 || true
tmux set-option -t "$SESSION" status-style "fg=#94a3b8,bg=#0b0f14"
tmux set-option -t "$SESSION" pane-border-style "fg=#334155"
tmux set-option -t "$SESSION" pane-active-border-style "fg=#4ade80"
tmux set-option -t "$SESSION" status-left " SIDECAR "
tmux set-option -t "$SESSION" status-right " remote brain · local hands "

# Right pane: the local daemon.
tmux send-keys -t "$SESSION:0.1" "clear; cd '$ROOT' && bash demo/serve_local.sh" C-m

# Wait for the daemon to answer, then start the remote script in the left pane.
for _ in $(seq 1 80); do
  if curl -fsS -m 0.5 -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
tmux send-keys -t "$SESSION:0.0" "clear; cd '$ROOT' && bash demo/run_remote.sh" C-m


# Approve the interactive commands as they arrive. The remote script sends six
# commands; the first (pwd) is auto-allowed, the next four ask, the last is a
# denied Apple Events attempt.
approve() {
  for _ in $(seq 1 80); do
    if tmux capture-pane -p -t "$SESSION:0.1" 2>/dev/null | grep -q "Approve?"; then
      sleep 0.4
      tmux send-keys -t "$SESSION:0.1" -l "y"
      sleep 0.15
      tmux send-keys -t "$SESSION:0.1" C-m
      return 0
    fi
    sleep 0.1
  done
  return 0
}
(
  sleep 1
  for _ in 1 2 3 4; do approve; done
  # Wait for the remote script to finish (or fail), then close the demo.
  for _ in $(seq 1 80); do
    if tmux capture-pane -p -t "$SESSION:0.0" 2>/dev/null | grep -qE "Done\\.|Traceback|command not found"; then
      break
    fi
    sleep 0.1
  done
  sleep 2
  tmux capture-pane -p -t "$SESSION:0.0" > /tmp/sidecar-demo-left.txt 2>/dev/null || true
  tmux capture-pane -p -t "$SESSION:0.1" > /tmp/sidecar-demo-right.txt 2>/dev/null || true
  tmux kill-session -t "$SESSION" 2>/dev/null || true
) &
CONTROLLER=$!

if [[ "$ATTACH" == "1" ]]; then
  tmux attach -t "$SESSION" || true
else
  wait "$CONTROLLER" || true
  echo "===== REMOTE (left) ====="
  cat /tmp/sidecar-demo-left.txt 2>/dev/null || true
  echo "===== LOCAL (right) ====="
  cat /tmp/sidecar-demo-right.txt 2>/dev/null || true
fi
wait "$CONTROLLER" 2>/dev/null || true
