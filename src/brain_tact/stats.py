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
    # git裏取り: 「動いた」でなく「実コミットに繋がった」介入の数
    git_checked = [v for v in verifies if v.get("git_progress") is not None]
    committed = sum(1 for v in git_checked
                    if v["git_progress"].get("committed"))

    # 介入品質スコア(Lv40): 実コミットを生んだ=1.0 / 動いただけ=0.5 / 不発・悪化=0。
    # unknown(タブ消失等)は判定不能としてスコアの分母に入れない
    quality = {"produced": 0, "moved": 0, "silent": 0}
    sample_commits: list[str] = []
    for v in verifies:
        gp = v.get("git_progress") or {}
        if gp.get("committed"):
            quality["produced"] += 1
            sample_commits.extend(gp.get("commits") or [])
        elif v.get("result") == "reactivated":
            quality["moved"] += 1
        elif v.get("result") in ("no_change", "worse"):
            quality["silent"] += 1
    n_scored = sum(quality.values())
    quality_score = (round((quality["produced"] + quality["moved"] * 0.5)
                           / n_scored * 100) if n_scored else None)

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
            "git_checked": len(git_checked),
            "committed": committed,
            "quality": quality,
            "quality_score_pct": quality_score,
            "sample_commits": sample_commits[:5],
        },
        "pending": {
            "deferred": len(defers),
            "status": dict(pending_counts),
        },
    }


def weekly_summary(s: dict) -> str:
    """週次サマリー(Lv55) — 日曜夜のLINEレポートに含める3行要約。

    push数は増やさない(夜の定時1通に統合)。計算済みのcompute_stats結果を渡す。
    """
    iv = s["interventions"]
    ef = s["effectiveness"]
    pd = s["pending"]
    lines = [f"巡回{len(s['cycles'])}回 / 介入{iv['sent']}件"
             f"(ガードレール拒否{iv['rejected_by_guardrails']})"]
    if ef["verified"]:
        line = f"介入効果: 成功率{ef['success_rate_pct']}%"
        if ef.get("quality_score_pct") is not None:
            line += (f" / 品質スコア{ef['quality_score_pct']}%"
                     f"(実コミット{ef['quality']['produced']})")
        lines.append(line)
    st = pd["status"]
    lines.append(f"保留: 新規{pd['deferred']} / 解決{st.get('resolved', 0)}"
                 f" / open{st.get('open', 0)}")
    return "\n".join(lines)


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
        if ef.get("quality_score_pct") is not None:
            q = ef["quality"]
            lines.append(f"  品質スコア {ef['quality_score_pct']}% — "
                         f"実コミット{q['produced']} / 動いただけ{q['moved']} / "
                         f"不発{q['silent']} (git裏取り {ef['git_checked']}件)")
        for c in ef.get("sample_commits", [])[:3]:
            lines.append(f"    ↳ {c}")
    else:
        lines.append("\n## 介入効果: 検証データなし")

    pd = s["pending"]
    lines.append(f"\n## 保留: 新規defer {pd['deferred']}件 / 状態 {pd['status'] or 'なし'}")
    return "\n".join(lines)
