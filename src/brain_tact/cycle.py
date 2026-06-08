"""定時サイクルの実行 — lock→debounce→scan→脳(claude -p)→記録。

launchdから brain-cycle.sh 経由で呼ばれる実体。macOSには timeout コマンドが
無いため、claude -p の暴走対策は subprocess.run(timeout=) で行う。
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from . import (
    BRAIN_DIR,
    CYCLE_LOG,
    INCIDENTS_LOG,
    MCP_BRAIN_DRY_JSON,
    MCP_BRAIN_JSON,
    claude_bin,
    ensure_dirs,
)
from .prompts import build_brain_prompt, time_slot
from .scan import run_scan
from .state import (
    acquire_cycle_lock,
    expire_pending,
    load_pending,
    mark_cycle_success,
    prune_history,
    read_actions,
    release_cycle_lock,
    should_debounce,
)

BRAIN_TIMEOUT_SEC = 900          # 15分でSIGKILL
MAX_BUDGET_USD = "3"

# 脳に許可するMCPツール。--strict-mcp-config 使用時は --allowedTools で明示
# しないとMCPツールがロードされない(--tools "" や無指定では全滅する。実機確認済み)。
# run_cycle_now は脳自身が呼ぶと再帰するので意図的に除外。
ACTUATOR_TOOLS = [
    "mcp__brain-actuator__get_pending",
    "mcp__brain-actuator__get_snapshot",
    "mcp__brain-actuator__get_cleanup",
    "mcp__brain-actuator__scan_now",
    "mcp__brain-actuator__act_send",
    "mcp__brain-actuator__act_approve",
    "mcp__brain-actuator__act_resume",
    "mcp__brain-actuator__defer",
    "mcp__brain-actuator__resolve_pending",
]
LINE_TOOLS = ["mcp__line-bridge__send_text"]


# 後方互換エイリアス(実体は __init__.claude_bin)
_claude_bin = claude_bin


def _log_cycle(record: dict) -> None:
    ensure_dirs()
    record.setdefault("ts", datetime.now().astimezone().isoformat(timespec="seconds"))
    with open(CYCLE_LOG, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_brain(prompt: str, cycle_id: str, model: str, dry_run: bool) -> dict:
    """claude -p(脳)を起動して結果dictを返す。"""
    # dry-run時はline-bridgeを外した構成にする(本物のLINE pushを防ぐ)
    mcp_config = MCP_BRAIN_DRY_JSON if dry_run else MCP_BRAIN_JSON
    allowed = ACTUATOR_TOOLS if dry_run else ACTUATOR_TOOLS + LINE_TOOLS
    cmd = [
        _claude_bin(), "-p",
        "--output-format", "json",
        "--model", model,
        "--fallback-model", "haiku",
        "--dangerously-skip-permissions",
        "--strict-mcp-config",
        "--mcp-config", str(mcp_config),
        # --allowedTools でMCPツールを明示許可(これが無いとMCPがロードされない)
        "--allowedTools", " ".join(allowed),
        "--max-budget-usd", MAX_BUDGET_USD,
    ]
    env = dict(os.environ)
    env["BRAIN_CYCLE_ID"] = cycle_id
    # 全セッション稼働中などの高負荷時、MCPサーバー(uv run×2)の起動が遅れて
    # 接続タイムアウト→ツールなしで脳が走る事故が実際に起きた。猶予を延ばす
    env["MCP_TIMEOUT"] = "60000"
    env["MCP_TOOL_TIMEOUT"] = "120000"
    if dry_run:
        env["BRAIN_DRY_RUN"] = "1"
    else:
        env.pop("BRAIN_DRY_RUN", None)

    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True,
        timeout=BRAIN_TIMEOUT_SEC, env=env, cwd=BRAIN_DIR,
    )
    out: dict = {"returncode": proc.returncode}
    try:
        parsed = json.loads(proc.stdout)
        out["result_text"] = parsed.get("result", "")
        out["cost_usd"] = parsed.get("total_cost_usd")
        out["num_turns"] = parsed.get("num_turns")
        out["is_error"] = parsed.get("is_error", proc.returncode != 0)
    except json.JSONDecodeError:
        out["result_text"] = proc.stdout[-2000:]
        out["is_error"] = proc.returncode != 0
    if proc.returncode != 0:
        out["stderr"] = proc.stderr[-1000:]
    return out


def record_incident(error: str) -> None:
    """サイクル失敗を障害ログに記録する(LINEには流さない)。

    方針変更(ユーザー指示): LINEは定時4通のみ。障害はこことダッシュボードに
    残し、翌朝の定時レポートで「昨日の障害n件」として要約する。
    """
    ensure_dirs()
    rec = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "error": error[:300],
    }
    with open(INCIDENTS_LOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"⚠️  障害記録: {error[:120]}", file=sys.stderr)


def recent_incidents(hours: float = 24.0) -> list[dict]:
    if not INCIDENTS_LOG.exists():
        return []
    cutoff = datetime.now().astimezone().timestamp() - hours * 3600
    out = []
    for line in INCIDENTS_LOG.read_text().splitlines():
        try:
            r = json.loads(line)
            if datetime.fromisoformat(r["ts"]).timestamp() >= cutoff:
                out.append(r)
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def run_cycle(force: bool = False, dry_run: bool = False, model: str = "sonnet") -> int:
    ensure_dirs()
    started = datetime.now()

    if not acquire_cycle_lock():
        _log_cycle({"event": "skipped", "why": "lock held(別サイクル実行中)"})
        print("⏭️  別サイクルが実行中(lock)。スキップします", file=sys.stderr)
        return 0

    caffeinate = None
    try:
        if should_debounce() and not force:
            _log_cycle({"event": "skipped", "why": "debounce(前回成功から3時間未満)"})
            print("⏭️  前回成功から3時間未満。--force で強制実行できます", file=sys.stderr)
            return 0

        # サイクル中のアイドルスリープを抑止(自PID終了で自動解除)
        try:
            caffeinate = subprocess.Popen(["caffeinate", "-w", str(os.getpid())])
        except FileNotFoundError:
            pass

        # ハウスキーピング
        n_exp = expire_pending()
        n_pru = prune_history()

        snapshot = run_scan()
        cycle_id = snapshot["cycle_id"]
        slot = time_slot()

        # 前サイクルの介入が効いたかを検証(actions.logにverifyレコード追記)
        from .verify import verify_interventions
        verify_results = verify_interventions(snapshot)
        if verify_results:
            print(f"🔍 前回介入の検証: " +
                  ", ".join(f"{r['tty']}={r['result']}" for r in verify_results),
                  file=sys.stderr)

        # 攻めモード: usage<50%なら読書係が放置プロジェクトを読み直す
        # (ホウレンソウ材料。dry-runではコスト節約のためスキップ)
        review_note = None
        if not dry_run:
            from .review import maybe_review
            review_note = maybe_review(snapshot)
            if review_note:
                print(f"📖 読書係: {review_note['project']} を読み直しました",
                      file=sys.stderr)

        pending = [i for i in load_pending().get("items", []) if i["status"] == "open"]
        recent = [
            {k: r.get(k) for k in ("ts", "cycle_id", "tool", "tty", "reason",
                                   "result", "target_tool", "target_ts")}
            for r in read_actions(hours=24)
        ]
        incidents = recent_incidents(hours=24)
        prompt = build_brain_prompt(snapshot, pending, recent, slot,
                                    dry_run=dry_run, review=review_note,
                                    incidents=incidents)

        print(f"🧠 {slot} 巡回開始 cycle={cycle_id} タブ{snapshot['totals']['tabs']} "
              f"(dry_run={dry_run}, model={model})", file=sys.stderr)

        try:
            brain = _run_brain(prompt, cycle_id, model, dry_run)
            # 脳がツール疎通確認に失敗した場合(手順0)は30秒置いて1回だけ再試行
            if "MCP_LOAD_FAILURE" in (brain.get("result_text") or ""):
                _log_cycle({"event": "mcp_load_failure_retry", "cycle_id": cycle_id,
                            "result_tail": (brain.get("result_text") or "")[-300:],
                            "stderr": (brain.get("stderr") or "")[-300:]})
                print("⚠️  MCPロード失敗 → 30秒後にリトライ", file=sys.stderr)
                time.sleep(30)
                brain = _run_brain(prompt, cycle_id, model, dry_run)
                if "MCP_LOAD_FAILURE" in (brain.get("result_text") or ""):
                    record_incident("MCPツールのロードに2回失敗(巡回未実施)")
                    _log_cycle({"event": "mcp_load_failure_final",
                                "cycle_id": cycle_id,
                                "result_tail": (brain.get("result_text") or "")[-300:],
                                "stderr": (brain.get("stderr") or "")[-300:]})
                    return 1
        except subprocess.TimeoutExpired:
            _log_cycle({"event": "brain_timeout", "cycle_id": cycle_id,
                        "timeout_sec": BRAIN_TIMEOUT_SEC})
            record_incident(f"脳が{BRAIN_TIMEOUT_SEC // 60}分でタイムアウト")
            return 1

        duration = (datetime.now() - started).total_seconds()
        _log_cycle({
            "event": "cycle_done",
            "cycle_id": cycle_id,
            "slot": slot,
            "dry_run": dry_run,
            "model": model,
            "ok": not brain.get("is_error"),
            "duration_s": round(duration, 1),
            "cost_usd": brain.get("cost_usd"),
            "num_turns": brain.get("num_turns"),
            "expired_pending": n_exp,
            "pruned_history": n_pru,
            "result_tail": (brain.get("result_text") or "")[-800:],
        })

        if brain.get("is_error"):
            record_incident(f"脳がエラー終了: {(brain.get('stderr') or '')[:150]}")
            print(f"❌ 脳がエラー終了 ({duration:.0f}s)", file=sys.stderr)
            return 1

        # dry-runは本番成功とみなさない(last_successを進めると直後の定時発火が
        # デバウンスで誤スキップされる — 07:00発火が2分差で抑止された実例あり)
        if dry_run:
            print("🧪 dry-run完了(last_successは更新しない)", file=sys.stderr)
            print(brain.get("result_text", ""))
            return 0

        # last_successはlaunchd定時発火(非force)のみ更新する。
        # 手動--force実行が更新すると次の定時がデバウンスで連鎖スキップされる
        # (実例: 09:13手動成功 → 12:00定時が2.7h<3hでスキップ)
        if not force:
            mark_cycle_success()
        print(f"✅ 巡回完了 ({duration:.0f}s, ${brain.get('cost_usd') or '?'}, "
              f"{brain.get('num_turns') or '?'}ターン)", file=sys.stderr)
        print(brain.get("result_text", ""))
        return 0

    except Exception as e:  # noqa: BLE001 — launchd運用では握って一報
        _log_cycle({"event": "cycle_crashed", "error": repr(e)})
        record_incident(f"サイクルが例外で停止: {e}")
        raise
    finally:
        if caffeinate:
            caffeinate.terminate()
        release_cycle_lock()
