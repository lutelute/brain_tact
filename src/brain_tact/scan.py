"""タブ・プロセス・セッション・分類を束ねてスナップショットJSONを生成する。"""

import hashlib
import json
from datetime import datetime

from . import HISTORY_DIR, LATEST_JSON, ensure_dirs
from .classify import classify
from .procs import find_claude_processes
from .sessions import attach_sessions, read_last_assistant_text
from .terminal import capture_all_tabs

# 脳に渡す画面末尾の行数(空行除去後)
TAIL_RUNNING = 10   # 安定稼働中は最小限
TAIL_ATTENTION = 30  # 要注意(承認待ち・IDLE・エラー等)は文脈込みで


def _tail(screen: str, n: int) -> list[str]:
    lines = [ln.rstrip() for ln in screen.splitlines()]
    return [ln for ln in lines if ln.strip()][-n:]


def _screen_hash(tail: list[str]) -> str:
    return hashlib.md5("\n".join(tail).encode()).hexdigest()[:10]


def compute_progress(
    screen_hash: str,
    jsonl_mtime: float | None,
    prev_record: dict | None,
) -> dict:
    """前回スナップショットとの比較で進展を判定する(純関数)。

    changed = 画面が変わった or jsonlが進んだ。RUNNINGはスピナーの経過秒で
    画面が毎回変わるため自然にchanged=Trueになる(動いている証拠として正しい)。
    stagnant_cycles = 連続して変化がないスキャン回数。2以上で「停滞」扱い。
    """
    if not prev_record:
        return {"changed": True, "stagnant_cycles": 0}
    jsonl_advanced = bool(
        jsonl_mtime
        and prev_record.get("jsonl_mtime")
        and jsonl_mtime > prev_record["jsonl_mtime"] + 1.0
    )
    changed = screen_hash != prev_record.get("screen_hash") or jsonl_advanced
    if changed:
        return {"changed": True, "stagnant_cycles": 0}
    prev_stagnant = (prev_record.get("progress") or {}).get("stagnant_cycles", 0)
    return {"changed": False, "stagnant_cycles": prev_stagnant + 1}


def _load_prev_records() -> dict[str, dict]:
    """前回スナップショットの tty -> record(差分検出・DEAD_SHELL判定に使う)。"""
    if not LATEST_JSON.exists():
        return {}
    try:
        prev = json.loads(LATEST_JSON.read_text())
        return {s["tty"]: s for s in prev.get("sessions", [])}
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
    prev_records = _load_prev_records()

    # git文脈は同一cwdで1回だけ取得
    from .gitinfo import collect_git_contexts
    git_by_cwd = collect_git_contexts({p.cwd for p in procs.values() if p.cwd})

    records = []
    for tab in tabs:
        proc = procs.get(tab.tty)
        info = sess.get(tab.tty)
        prev = prev_records.get(tab.tty)
        cls = classify(tab.contents, proc, info,
                       prev.get("state_hint") if prev else None)

        n = TAIL_ATTENTION if cls.attention else TAIL_RUNNING
        screen_tail = _tail(tab.contents, n)
        # ハッシュは行数に依存しないよう常に固定30行で計算する
        h = _screen_hash(_tail(tab.contents, TAIL_ATTENTION))
        jsonl_mtime = info.mtime if info else None
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
            "git": git_by_cwd.get(proc.cwd) if proc and proc.cwd else None,
            "state_hint": cls.state_hint,
            "attention": cls.attention,
            "signals": cls.signals,
            "screen_hash": h,
            "jsonl_mtime": jsonl_mtime,
            "progress": compute_progress(h, jsonl_mtime, prev),
            # 要注意セッションのみ: 画面で折りたたまれたClaudeの最終発言を添付
            "last_assistant": (
                read_last_assistant_text(info.jsonl_path)
                if cls.attention and info and info.jsonl_path else None
            ),
            "screen_tail": screen_tail,
        })

    by_state: dict[str, int] = {}
    for r in records:
        by_state[r["state_hint"]] = by_state.get(r["state_hint"], 0) + 1

    # quickスキャン(/brainの鮮度更新)ではccusage呼び出しを省く
    usage = None
    if not quick:
        from .usage import current_usage
        usage = current_usage()

    snapshot = {
        "taken_at": now.isoformat(timespec="seconds"),
        "cycle_id": cycle_id,
        "totals": {
            "tabs": len(records),
            "claude": sum(1 for r in records if r["has_claude"]),
            "by_state": by_state,
            "usage": usage,
        },
        "sessions": records,
    }

    # 各セッションに掃除判定を付与(脳・ダッシュボード・MCPが共通で使う)
    from .cleanup import judge_session
    for r in records:
        r["cleanup"] = judge_session(r)

    LATEST_JSON.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1))
    if not quick:
        (HISTORY_DIR / f"scan-{cycle_id}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1)
        )
    return snapshot
