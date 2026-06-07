"""タブ・プロセス・セッション・分類を束ねてスナップショットJSONを生成する。"""

import json
from datetime import datetime

from . import HISTORY_DIR, LATEST_JSON, ensure_dirs
from .classify import classify
from .procs import find_claude_processes
from .sessions import attach_sessions
from .terminal import capture_all_tabs

# 脳に渡す画面末尾の行数(空行除去後)
TAIL_RUNNING = 10   # 安定稼働中は最小限
TAIL_ATTENTION = 30  # 要注意(承認待ち・IDLE・エラー等)は文脈込みで


def _tail(screen: str, n: int) -> list[str]:
    lines = [ln.rstrip() for ln in screen.splitlines()]
    return [ln for ln in lines if ln.strip()][-n:]


def _load_prev_states() -> dict[str, str]:
    """前回スナップショットの tty -> state_hint(DEAD_SHELL判定に使う)。"""
    if not LATEST_JSON.exists():
        return {}
    try:
        prev = json.loads(LATEST_JSON.read_text())
        return {s["tty"]: s["state_hint"] for s in prev.get("sessions", [])}
    except (json.JSONDecodeError, KeyError):
        return {}


def run_scan(quick: bool = False) -> dict:
    """スキャンを実行し、latest.json(+ 通常時はhistory/)に保存して返す。

    quick=True は /brain からの鮮度更新用 — history/ に残さない。
    """
    ensure_dirs()
    now = datetime.now().astimezone()
    cycle_id = now.strftime("%Y%m%d-%H%M")

    tabs = capture_all_tabs()
    procs = find_claude_processes()
    sess = attach_sessions(procs)
    prev_states = _load_prev_states()

    records = []
    for tab in tabs:
        proc = procs.get(tab.tty)
        info = sess.get(tab.tty)
        cls = classify(tab.contents, proc, info, prev_states.get(tab.tty))

        n = TAIL_ATTENTION if cls.attention else TAIL_RUNNING
        records.append({
            "tty": tab.tty,
            "title": tab.title,
            "window": tab.window_idx,
            "tab": tab.tab_idx,
            "busy": tab.busy,
            "has_claude": proc is not None,
            "pid": proc.pid if proc else None,
            "cwd": proc.cwd if proc else None,
            "project": (proc.cwd or "").rsplit("/", 1)[-1] if proc and proc.cwd else None,
            "session_id": info.session_id if info else None,
            "state_hint": cls.state_hint,
            "attention": cls.attention,
            "signals": cls.signals,
            "screen_tail": _tail(tab.contents, n),
        })

    by_state: dict[str, int] = {}
    for r in records:
        by_state[r["state_hint"]] = by_state.get(r["state_hint"], 0) + 1

    snapshot = {
        "taken_at": now.isoformat(timespec="seconds"),
        "cycle_id": cycle_id,
        "totals": {
            "tabs": len(records),
            "claude": sum(1 for r in records if r["has_claude"]),
            "by_state": by_state,
        },
        "sessions": records,
    }

    LATEST_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1))
    if not quick:
        (HISTORY_DIR / f"scan-{cycle_id}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1)
        )
    return snapshot
