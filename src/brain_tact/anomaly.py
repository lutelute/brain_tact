"""異常検知(Lv80) — ベースラインから外れたパターンの検出。

臨時LINE通知は「定時4通のみ」方針(ユーザー指示)と衝突するため使わない。
検出時は incident 記録(翌定時レポートに件数が乗る+doctorが拾う)と
macOS通知(ローカルポップアップ・LINE枠消費ゼロ)で知らせる。
"""

import subprocess

FAIL_EVENTS = {"cycle_crashed", "brain_timeout", "brain_failed_final",
               "mcp_load_failure_final", "scan_failed"}
COST_FLOOR_USD = 2.0   # 平均が小さくてもこれ以下では騒がない
COST_FACTOR = 3.0      # 平均のこの倍数超で異常コスト


def detect_anomalies(snapshot: dict, recent_events: list[dict]) -> list[str]:
    """スナップショットと直近のサイクルイベントから異常を列挙する(純関数)。"""
    out: list[str] = []

    # 1. 全停止: タブはあるのにclaudeが1つも居ない
    totals = snapshot.get("totals", {})
    if totals.get("tabs", 0) > 0 and totals.get("claude", 0) == 0:
        out.append(f"全停止: {totals['tabs']}タブ中claude稼働0 — "
                   "一斉終了/クラッシュの疑い")

    # 2. 巡回の連続失敗: skipped以外の直近3イベントが全て失敗系
    meaningful = [e for e in recent_events if e.get("event") != "skipped"]
    last3 = meaningful[-3:]
    if len(last3) == 3 and all(
            e.get("event") in FAIL_EVENTS or e.get("ok") is False
            for e in last3):
        out.append("巡回が3回連続で失敗 — 環境異常の疑い(brain-tact doctor を)")

    # 3. 異常コスト: 直近完了サイクルが過去平均の3倍超(下限$2)
    done = [e for e in recent_events
            if e.get("event") == "cycle_done"
            and isinstance(e.get("cost_usd"), (int, float))]
    if len(done) >= 3:  # 平均に最低2点
        last = done[-1]["cost_usd"]
        prev = [e["cost_usd"] for e in done[:-1]]
        baseline = max(COST_FLOOR_USD, sum(prev) / len(prev) * COST_FACTOR)
        if last > baseline:
            out.append(f"異常コスト: 直近サイクル${last:.2f} > "
                       f"基準${baseline:.2f}(過去平均×{COST_FACTOR:.0f})")
    return out


def notify_mac(title: str, message: str) -> None:
    """macOS通知センターにポップアップを出す(LINE枠を消費しない臨時通知)。

    通知権限が無い・失敗しても巡回は止めない。
    """
    safe = message.replace('"', "'")[:200]
    safe_title = title.replace('"', "'")[:60]
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe}" with title "{safe_title}"'],
            capture_output=True, timeout=10,
        )
    except Exception:  # noqa: BLE001 — 通知は best-effort
        pass
