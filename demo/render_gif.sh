#!/usr/bin/env bash
# Record the two-pane demo and render it to a README GIF.
set -euo pipefail
cd "$(dirname "$0")/.."

asciinema rec demo/demo.cast --overwrite --idle-time-limit 0.8 \
  --command "bash -c 'stty cols 138 rows 44 2>/dev/null || true; bash demo/tmux_run.sh'"

# asciinema's headless recorder starts at 80x24; the tmux panes are 138x44.
python3 - <<'PY'
import json
src, dst = "demo/demo.cast", "demo/demo-fixed.cast"
lines = [json.loads(line) for line in open(src, encoding="utf-8") if line.strip()]
lines[0]["term"] = {"cols": 138, "rows": 44}
with open(dst, "w", encoding="utf-8") as handle:
    for item in lines:
        handle.write(json.dumps(item) + "\n")
PY
agg --font-size 16 demo/demo-fixed.cast demo/demo.gif
ls -lh demo/demo.gif
