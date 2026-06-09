#!/bin/bash
# brain-cycle.sh — launchdエントリ。実体は Python(brain-tact cycle)。
# iCloud(~/Documents)同期が uv の editable .pth を壊すため、uv run ではなく
# iCloud外の venv python を直接呼ぶ + PYTHONPATH=src で二重に堅牢化。
export PATH="/Users/shigenoburyuto/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="/Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact/src"
exec /Users/shigenoburyuto/.venvs/brain_tact/bin/python -m brain_tact.cli cycle "$@"
