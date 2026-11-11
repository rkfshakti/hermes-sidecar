#!/usr/bin/env bash
# Local pane for the demo: a compact header, then the real daemon.
set -euo pipefail
cd "$(dirname "$0")/.."
printf '\033[1;35mLOCAL SIDECAR\033[0m  ·  this Mac\n'
printf '\033[2mthe remote brain is asking. approve or deny.\033[0m\n\n'
exec "${HERMES_BIN:-hermes}" -p "${SIDECAR_DEMO_PROFILE:-sidecar-test}" sidecar serve \
  --port "${SIDECAR_DEMO_PORT:-8798}" \
  --workspace "${SIDECAR_DEMO_WORKSPACE:-$PWD}" \
  --approval "${SIDECAR_DEMO_APPROVAL:-ask}" \
  --quiet
