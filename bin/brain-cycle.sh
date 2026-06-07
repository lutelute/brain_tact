#!/bin/bash
# brain-cycle.sh — launchdエントリ。実体は Python(brain-tact cycle)。
# /bin/bash経由なのはwatchdogとTCC(オートメーション権限)の帰属を揃えるため。
export PATH="/Users/shigenoburyuto/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
exec uv run --directory /Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact brain-tact cycle "$@"
