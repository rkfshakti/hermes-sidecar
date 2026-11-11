#!/usr/bin/env bash
# Remote pane for the demo: a short command line, then the real client.
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 demo/remote.py
