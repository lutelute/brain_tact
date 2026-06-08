"""brain_tact — Claude Codeセッション群の監督脳。

定時(7/12/17/22時)に全Terminal.appタブをスキャンし、ヘッドレスClaude(脳)が
継続/介入/保留を判断、LINEに報告する。ユーザーは /brain スキルで保留を対話処理する。
"""

import os
import shutil
from pathlib import Path

# プロジェクトルート(src/brain_tact/__init__.py → ../../..)
# uv run --directory での実行を前提。BRAIN_TACT_HOME で上書き可。
BRAIN_DIR = Path(
    os.environ.get("BRAIN_TACT_HOME", Path(__file__).resolve().parent.parent.parent)
)

STATE_DIR = BRAIN_DIR / "state"
HISTORY_DIR = STATE_DIR / "history"
LATEST_JSON = STATE_DIR / "latest.json"
PENDING_JSON = STATE_DIR / "pending.json"
ACTIONS_LOG = STATE_DIR / "actions.log"
CYCLE_LOG = STATE_DIR / "cycle.log"
INCIDENTS_LOG = STATE_DIR / "incidents.log"  # 障害記録(LINEには流さずダッシュボード/翌朝要約へ)
LOCK_FILE = STATE_DIR / "cycle.lock"
LAST_SUCCESS = STATE_DIR / "last_success"
CONFIG_DIR = BRAIN_DIR / "config"
MCP_BRAIN_JSON = CONFIG_DIR / "mcp-brain.json"
MCP_BRAIN_DRY_JSON = CONFIG_DIR / "mcp-brain-dry.json"  # line-bridge無し(dry-run用)

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"

# 死んだタブの復元コマンド(watchdogと同一)
CLAUDE_RESUME_CMD = "claude --continue --dangerously-skip-permissions --effort max"


def ensure_dirs() -> None:
    """state系ディレクトリを作成する(冪等)。"""
    for d in (STATE_DIR, HISTORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def claude_bin() -> str:
    """claude CLIの実体パス(launchd環境のPATH細りに備えフォールバック付き)。"""
    found = shutil.which("claude")
    if found:
        return found
    default = os.path.expanduser("~/.local/bin/claude")
    if os.path.exists(default):
        return default
    raise FileNotFoundError("claude CLIが見つかりません")
