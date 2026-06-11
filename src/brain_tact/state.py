"""状態管理 — サイクルロック/デバウンス/pending CRUD/actions.log/履歴prune。

アクション制限はここで一元定義し、actuatorがコードとして強制する
(脳プロンプトへの「お願い」に依存しない)。
"""

import json
import os
import time
from datetime import datetime

from . import (
    ACTIONS_LOG,
    CYCLE_LOG,
    HISTORY_DIR,
    INCIDENTS_LOG,
    INSIGHTS_LOG,
    LAST_SUCCESS,
    LOCK_FILE,
    PENDING_JSON,
    ensure_dirs,
)

LOCK_STALE_SEC = 2 * 3600          # これより古いロックは残骸とみなして奪取
DEBOUNCE_HOURS = 3.0               # スリープ起床時のまとめ発火を1回に正規化
PENDING_EXPIRE_HOURS = 48.0
HISTORY_KEEP_DAYS = 14
LOG_KEEP_DAYS = 90                 # JSONLログ(actions/cycle/incidents)の保持期間

# --- アクション制限(actuatorが強制) ---------------------------------------
MAX_ACTIONS_PER_CYCLE = 15
PER_TTY_PER_CYCLE = {"act_send": 1, "act_approve": 3, "act_resume": 1}
COOLDOWN_HOURS = {"act_send": 6.0, "act_resume": 12.0}
STRIKE_OUT = 2                 # 連続不発(no_change)がこの回数でact_send禁止
STRIKE_WINDOW_HOURS = 48.0     # 3ストライク判定に使うverify参照期間


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# サイクルロック・デバウンス
# ---------------------------------------------------------------------------

def acquire_cycle_lock() -> bool:
    """O_EXCLでロック取得。stale(2h超)なら奪取する。"""
    ensure_dirs()
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - LOCK_FILE.stat().st_mtime > LOCK_STALE_SEC:
                LOCK_FILE.unlink(missing_ok=True)
                return acquire_cycle_lock()
        except FileNotFoundError:
            return acquire_cycle_lock()
        return False


def release_cycle_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def should_debounce() -> bool:
    """前回成功サイクルから3時間未満ならTrue(--forceで無視可)。"""
    if not LAST_SUCCESS.exists():
        return False
    return (time.time() - LAST_SUCCESS.stat().st_mtime) < DEBOUNCE_HOURS * 3600


def mark_cycle_success() -> None:
    ensure_dirs()
    LAST_SUCCESS.write_text(_now_iso())


# ---------------------------------------------------------------------------
# actions.log(JSONL) — 脳の全アクションの監査記録
# ---------------------------------------------------------------------------

def log_action(record: dict) -> None:
    ensure_dirs()
    record.setdefault("ts", _now_iso())
    with open(ACTIONS_LOG, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_actions(hours: float | None = None) -> list[dict]:
    if not ACTIONS_LOG.exists():
        return []
    out = []
    cutoff = time.time() - hours * 3600 if hours else None
    for line in ACTIONS_LOG.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if cutoff is not None:
            try:
                ts = datetime.fromisoformat(r.get("ts", "")).timestamp()
                if ts < cutoff:
                    continue
            except ValueError:
                continue
        out.append(r)
    return out


def check_limits(tty: str, tool: str, cycle_id: str) -> tuple[bool, str]:
    """(許可するか, 拒否理由)。result=='sent' の成功記録だけを数える。"""
    recs = [r for r in read_actions() if r.get("result") == "sent"]

    in_cycle = [r for r in recs if r.get("cycle_id") == cycle_id
                and r.get("tool", "").startswith("act_")]
    if len(in_cycle) >= MAX_ACTIONS_PER_CYCLE:
        return False, f"サイクル合計{MAX_ACTIONS_PER_CYCLE}アクションの上限に達しています"

    per_tty = [r for r in in_cycle if r.get("tty") == tty and r.get("tool") == tool]
    limit = PER_TTY_PER_CYCLE.get(tool, 1)
    if len(per_tty) >= limit:
        return False, f"{tool} は {tty} に対して既に{limit}回実行済み(このサイクル)"

    cooldown = COOLDOWN_HOURS.get(tool)
    if cooldown:
        recent = [r for r in read_actions(hours=cooldown)
                  if r.get("result") == "sent"
                  and r.get("tty") == tty and r.get("tool") == tool]
        if recent:
            return False, (f"{tool} は {tty} に対して過去{cooldown:.0f}時間以内に "
                           f"実行済み(クールダウン中)。必要なら defer してユーザーに委ねること")

    # 3ストライク: このttyへのact_sendが連続して不発(verify=no_change)なら禁止
    if tool == "act_send":
        verifies = [r for r in read_actions(hours=STRIKE_WINDOW_HOURS)
                    if r.get("tool") == "verify" and r.get("tty") == tty
                    and r.get("target_tool") == "act_send"]
        streak = 0
        for r in reversed(verifies):  # 新しい順に連続不発を数える
            if r.get("result") == "no_change":
                streak += 1
            else:
                break
        if streak >= STRIKE_OUT:
            return False, (f"3ストライク: {tty} への直近{streak}回の送信が不発"
                           f"(no_change)。これ以上突かず defer すること")
    return True, ""


# ---------------------------------------------------------------------------
# pending.json — ユーザー判断待ちの保留リスト
# ---------------------------------------------------------------------------

def load_pending() -> dict:
    if not PENDING_JSON.exists():
        return {"version": 1, "updated_at": None, "items": []}
    try:
        return json.loads(PENDING_JSON.read_text())
    except json.JSONDecodeError:
        return {"version": 1, "updated_at": None, "items": []}


def _save_pending(pending: dict) -> None:
    ensure_dirs()
    pending["updated_at"] = _now_iso()
    PENDING_JSON.write_text(json.dumps(pending, ensure_ascii=False, indent=1))


def add_pending(
    tty: str,
    kind: str,
    summary: str,
    cycle_id: str,
    project: str | None = None,
    cwd: str | None = None,
    screen_excerpt: list[str] | None = None,
    suggested_actions: list[dict] | None = None,
) -> str:
    """保留項目を追加してIDを返す。同tty同kindのopen項目があれば差し替える。"""
    pending = load_pending()
    # 同じタブの同種の保留が残っていたら supersede(古い方を閉じる)
    for item in pending["items"]:
        if item["status"] == "open" and item["tty"] == tty and item["kind"] == kind:
            item["status"] = "superseded"
            item["resolved_at"] = _now_iso()

    seq = sum(1 for i in pending["items"] if i["cycle_id"] == cycle_id) + 1
    item_id = f"p-{cycle_id}-{tty.rsplit('/', 1)[-1]}-{seq}"
    pending["items"].append({
        "id": item_id,
        "created_at": _now_iso(),
        "cycle_id": cycle_id,
        "tty": tty,
        "project": project,
        "cwd": cwd,
        "kind": kind,
        "summary": summary,
        "screen_excerpt": screen_excerpt or [],
        "suggested_actions": suggested_actions or [],
        "status": "open",
        "resolved_at": None,
        "resolution": None,
    })
    _save_pending(pending)
    return item_id


def resolve_pending(item_id: str, resolution: str) -> bool:
    pending = load_pending()
    for item in pending["items"]:
        if item["id"] == item_id and item["status"] == "open":
            item["status"] = "resolved"
            item["resolved_at"] = _now_iso()
            item["resolution"] = resolution
            _save_pending(pending)
            return True
    return False


def expire_pending() -> int:
    """48時間超のopen項目をexpiredにする。返り値は件数。"""
    pending = load_pending()
    n = 0
    cutoff = time.time() - PENDING_EXPIRE_HOURS * 3600
    for item in pending["items"]:
        if item["status"] != "open":
            continue
        try:
            created = datetime.fromisoformat(item["created_at"]).timestamp()
        except ValueError:
            continue
        if created < cutoff:
            item["status"] = "expired"
            item["resolved_at"] = _now_iso()
            n += 1
    if n:
        _save_pending(pending)
    return n


def prune_history() -> int:
    """history/のスナップショットを14日で削除する。"""
    if not HISTORY_DIR.is_dir():
        return 0
    cutoff = time.time() - HISTORY_KEEP_DAYS * 86400
    n = 0
    for f in HISTORY_DIR.glob("scan-*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            n += 1
    return n


# ---------------------------------------------------------------------------
# insights.jsonl — 脳の自己評価の蓄積(Lv70)
# ---------------------------------------------------------------------------

def log_insight(text: str, cycle_id: str) -> None:
    """脳の自己評価(判断の間違い・学び)を1件追記する。"""
    ensure_dirs()
    with open(INSIGHTS_LOG, "a") as f:
        f.write(json.dumps({"ts": _now_iso(), "cycle_id": cycle_id,
                            "text": text}, ensure_ascii=False) + "\n")


def read_insights(limit: int = 3) -> list[dict]:
    """直近limit件の自己評価(新しい順)。次サイクルのプロンプトに注入される。"""
    if not INSIGHTS_LOG.exists():
        return []
    out = []
    for line in INSIGHTS_LOG.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out[-limit:]))


def has_insight_for_cycle(cycle_id: str) -> bool:
    """このサイクルで既に自己評価を記録済みか(1サイクル1件の強制用)。"""
    return any(r.get("cycle_id") == cycle_id for r in read_insights(limit=20))


def rotate_logs() -> int:
    """JSONLログ(actions/cycle/incidents)の90日より古い行を落とす。返り値は削除行数。

    history/には14日pruneがあるのにログは無限成長だった非対称の解消。
    check_limitsの参照期間は最長48時間なので90日保持で判定に影響しない。
    tsが読めない行(壊れた行)は監査の欠落を避けるため保守的に残す。
    """
    cutoff = time.time() - LOG_KEEP_DAYS * 86400
    n = 0
    for log in (ACTIONS_LOG, CYCLE_LOG, INCIDENTS_LOG):
        if not log.exists():
            continue
        lines = log.read_text().splitlines()
        kept = []
        for ln in lines:
            try:
                ts = datetime.fromisoformat(json.loads(ln)["ts"]).timestamp()
                if ts < cutoff:
                    continue
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                pass  # ts不明の行は残す
            kept.append(ln)
        if len(kept) != len(lines):
            n += len(lines) - len(kept)
            log.write_text("\n".join(kept) + ("\n" if kept else ""))
    return n
