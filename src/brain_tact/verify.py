"""前サイクルの介入が効いたかの検証(閉ループ)。

「入力した」で終わらせず、次のサイクルで対象セッションが実際に動いたかを
判定して actions.log に verify レコードを残す。脳はこれを見て同じ無効な
介入を繰り返さない(3ストライクの客観根拠)。KPI(介入成功率)の基礎データ。
"""

from datetime import datetime

from .state import log_action, read_actions

VERIFY_WINDOW_HOURS = 26.0   # これより古い介入は検証しない(1日+余裕)
JSONL_ADVANCE_GRACE = 5.0    # 介入後この秒数以上jsonlが進んでいたら「動いた」


def _judge(action: dict, session: dict | None) -> str:
    """介入の結果を判定する: reactivated / no_change / worse / unknown。"""
    if session is None:
        return "unknown"  # タブ自体が閉じられた等

    tool = action.get("tool")
    state = session.get("state_hint")

    if tool == "act_resume":
        # 復元の成否は単純: claudeが居るようになったか
        return "reactivated" if session.get("has_claude") else "no_change"

    # act_send / act_approve: 介入時刻以降にセッションが動いたか
    if state == "RUNNING":
        return "reactivated"
    try:
        t_action = datetime.fromisoformat(action["ts"]).timestamp()
    except (KeyError, ValueError, TypeError):
        t_action = None
    mtime = session.get("jsonl_mtime")
    if t_action and mtime and mtime > t_action + JSONL_ADVANCE_GRACE:
        return "reactivated"  # 今はIDLEでも介入後に作業が進んだ形跡がある
    if state in ("DEAD_SHELL", "PLAIN_SHELL"):
        return "worse"
    return "no_change"


def verify_interventions(snapshot: dict) -> list[dict]:
    """未検証の実介入(act_*, sent, 非dry-run)を現スナップショットで検証する。

    結果は actions.log に tool="verify" として追記され、リストでも返す。
    """
    recs = read_actions(hours=VERIFY_WINDOW_HOURS)
    already = {r.get("target_ts") for r in recs if r.get("tool") == "verify"}
    targets = [
        r for r in recs
        if r.get("tool", "").startswith("act_")
        and r.get("result") == "sent"
        and not r.get("dry_run")
        and r.get("ts") not in already
    ]

    by_tty = {s["tty"]: s for s in snapshot.get("sessions", [])}
    results = []
    for action in targets:
        outcome = _judge(action, by_tty.get(action.get("tty")))
        rec = {
            "cycle_id": snapshot.get("cycle_id"),
            "tool": "verify",
            "tty": action.get("tty"),
            "target_tool": action.get("tool"),
            "target_ts": action.get("ts"),
            "reason": f"{action.get('tool')} ({action.get('ts')}) の効果検証",
            "result": outcome,
        }
        log_action(rec)
        results.append(rec)
    return results


def summarize_outcomes(results: list[dict]) -> str:
    """LINEレポート用の一行サマリ(例: '前回介入3件: 効果2 / 不発1')。"""
    if not results:
        return ""
    ok = sum(1 for r in results if r["result"] == "reactivated")
    dud = sum(1 for r in results if r["result"] == "no_change")
    worse = sum(1 for r in results if r["result"] == "worse")
    parts = [f"効果{ok}"]
    if dud:
        parts.append(f"不発{dud}")
    if worse:
        parts.append(f"悪化{worse}")
    return f"前回介入{len(results)}件: " + " / ".join(parts)
