"""brain-tact stats — KPI集計(介入成功率・稼働率推移・保留処理)。

自己改善ループ(Lv70+)の基礎データ。「brainは役に立っているか」を数字で示す。
"""

import json
import time
from collections import Counter

from . import HISTORY_DIR
from .state import load_pending, read_actions


def compute_stats(days: float = 7.0) -> dict:
    cutoff = time.time() - days * 86400

    # --- サイクル推移(history/) ------------------------------------------
    cycles = []
    if HISTORY_DIR.is_dir():
        for f in sorted(HISTORY_DIR.glob("scan-*.json")):
            if f.stat().st_mtime < cutoff:
                continue
            try:
                s = json.loads(f.read_text())
            except json.JSONDecodeError:
                continue
            totals = s.get("totals", {})
            by_state = totals.get("by_state", {})
            running = by_state.get("RUNNING", 0)
            tabs = totals.get("tabs", 0)
            cycles.append({
                "cycle_id": s.get("cycle_id"),
                "tabs": tabs,
                "running": running,
                "running_rate": round(running / tabs * 100) if tabs else 0,
                "usage_pct": (totals.get("usage") or {}).get("pct"),
            })

    # --- アクション集計(actions.log) --------------------------------------
    acts = read_actions(hours=days * 24)
    real_sends = [a for a in acts
                  if a.get("tool", "").startswith("act_")
                  and a.get("result") == "sent" and not a.get("dry_run")]
    rejected = [a for a in acts
                if a.get("tool", "").startswith("act_")
                and str(a.get("result", "")).startswith("rejected")]
    verifies = [a for a in acts if a.get("tool") == "verify"]
    outcomes = Counter(v.get("result") for v in verifies)
    defers = [a for a in acts if a.get("tool") == "defer"]

    pending = load_pending().get("items", [])
    pending_counts = Counter(i.get("status") for i in pending)

    n_verified = len(verifies)
    success_rate = (round(outcomes.get("reactivated", 0) / n_verified * 100)
                    if n_verified else None)

    return {
        "window_days": days,
        "cycles": cycles,
        "interventions": {
            "sent": len(real_sends),
            "by_tool": dict(Counter(a.get("tool") for a in real_sends)),
            "rejected_by_guardrails": len(rejected),
        },
        "effectiveness": {
            "verified": n_verified,
            "outcomes": dict(outcomes),
            "success_rate_pct": success_rate,
        },
        "pending": {
            "deferred": len(defers),
            "status": dict(pending_counts),
        },
    }


def format_stats(s: dict) -> str:
    lines = [f"📊 brain-tact stats(直近{s['window_days']:.0f}日)"]

    if s["cycles"]:
        lines.append(f"\n## サイクル({len(s['cycles'])}回)")
        lines.append("cycle_id        タブ  稼働率  usage")
        for c in s["cycles"][-12:]:
            u = f"{c['usage_pct']:.0f}%" if c.get("usage_pct") is not None else "-"
            lines.append(f"{c['cycle_id']:<15} {c['tabs']:>3}  {c['running_rate']:>4}%  {u:>5}")
    else:
        lines.append("(サイクル履歴なし)")

    iv = s["interventions"]
    lines.append(f"\n## 介入: {iv['sent']}件 "
                 f"(ガードレール拒否 {iv['rejected_by_guardrails']}件)")
    for tool, n in sorted(iv["by_tool"].items()):
        lines.append(f"  {tool}: {n}")

    ef = s["effectiveness"]
    if ef["verified"]:
        lines.append(f"\n## 介入効果(検証済み {ef['verified']}件): "
                     f"成功率 {ef['success_rate_pct']}%")
        for outcome, n in sorted(ef["outcomes"].items()):
            lines.append(f"  {outcome}: {n}")
    else:
        lines.append("\n## 介入効果: 検証データなし")

    pd = s["pending"]
    lines.append(f"\n## 保留: 新規defer {pd['deferred']}件 / 状態 {pd['status'] or 'なし'}")
    return "\n".join(lines)
