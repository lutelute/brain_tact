"""brain-tact tune — KPIに基づくパラメータ調整の提案と適用(Lv75)。

自動では変えない: 直近のverify/品質データから提案を計算して表示し、
人間が --apply したときだけ state/tuning.json に保存する
(state.apply_tuning がモジュールロード時に読み込み、安全レンジ内で上書き)。
"""

from . import state
from .state import read_actions, save_tuning

MIN_DATA_POINTS = 10   # これ未満は「データ不足」として提案しない
DUD_HIGH = 0.30        # 不発率がこれ超 → 突きすぎ(クールダウン延長)
DUD_LOW = 0.10         # 不発率がこれ未満かつCD拒否多 → 機会損失(短縮)


def propose(days: float = 14.0) -> dict:
    """KPIからチューニング提案を計算する(適用はしない)。"""
    acts = read_actions(hours=days * 24)
    verifies = [a for a in acts if a.get("tool") == "verify"
                and a.get("target_tool") == "act_send"]
    ok = sum(1 for v in verifies if v.get("result") == "reactivated")
    dud = sum(1 for v in verifies if v.get("result") == "no_change")
    judged = ok + dud
    cd_rejects = sum(1 for a in acts
                     if a.get("tool") == "act_send"
                     and "クールダウン" in str(a.get("result", "")))
    produced = sum(1 for v in verifies
                   if (v.get("git_progress") or {}).get("committed"))

    current = {
        "cooldown_act_send_h": state.COOLDOWN_HOURS["act_send"],
        "strike_out": state.STRIKE_OUT,
        "max_actions_per_cycle": state.MAX_ACTIONS_PER_CYCLE,
    }
    out = {
        "window_days": days,
        "data_points": judged,
        "metrics": {
            "reactivated": ok, "no_change": dud,
            "dud_rate": round(dud / judged, 2) if judged else None,
            "produced": produced,
            "cooldown_rejects": cd_rejects,
        },
        "current": current,
        "proposals": [],
    }
    if judged < MIN_DATA_POINTS:
        out["note"] = (f"検証データ{judged}件 < {MIN_DATA_POINTS} — "
                       "データ不足のため現状維持(蓄積を待つ)")
        return out

    dud_rate = dud / judged
    cd_now = state.COOLDOWN_HOURS["act_send"]
    if dud_rate > DUD_HIGH and cd_now < 12.0:
        out["proposals"].append({
            "param": "cooldown_hours.act_send",
            "current": cd_now, "proposed": min(cd_now + 3.0, 12.0),
            "reason": f"不発率{dud_rate:.0%} > {DUD_HIGH:.0%} — 突きすぎ。"
                      f"間隔を空けて1回の介入を重くする",
        })
    elif dud_rate < DUD_LOW and cd_rejects >= 5 and cd_now > 3.0:
        out["proposals"].append({
            "param": "cooldown_hours.act_send",
            "current": cd_now, "proposed": max(cd_now - 2.0, 3.0),
            "reason": f"不発率{dud_rate:.0%}と低いのにCD拒否{cd_rejects}件 — "
                      f"効く介入の機会損失。短縮して回転を上げる",
        })

    # 実コミットがほぼ出ないのに動いただけが多い → 早めに見切る
    if judged >= MIN_DATA_POINTS and produced == 0 and ok >= 5 \
            and state.STRIKE_OUT > 1:
        out["proposals"].append({
            "param": "strike_out",
            "current": state.STRIKE_OUT, "proposed": state.STRIKE_OUT - 1,
            "reason": "reactivatedはあるが実コミット0 — 空回り傾向。"
                      "早めにdeferへ回す",
        })

    if not out["proposals"]:
        out["note"] = "現在のパラメータはKPIと整合 — 変更不要"
    return out


def apply_proposals(p: dict) -> dict:
    """提案をtuning.jsonに保存する(次回ロードから有効)。"""
    tuning = state.load_tuning()
    for pr in p.get("proposals", []):
        if pr["param"].startswith("cooldown_hours."):
            key = pr["param"].split(".", 1)[1]
            tuning.setdefault("cooldown_hours", {})[key] = pr["proposed"]
        elif pr["param"] == "strike_out":
            tuning["strike_out"] = pr["proposed"]
        elif pr["param"] == "max_actions_per_cycle":
            tuning["max_actions_per_cycle"] = pr["proposed"]
    save_tuning(tuning)
    return tuning


def format_proposals(p: dict) -> str:
    m = p["metrics"]
    lines = [f"🎛  brain-tact tune(直近{p['window_days']:.0f}日 "
             f"/ 検証{p['data_points']}件)"]
    if m["dud_rate"] is not None:
        lines.append(f"  介入: 効果{m['reactivated']} / 不発{m['no_change']}"
                     f"(不発率{m['dud_rate']:.0%}) / 実コミット{m['produced']}"
                     f" / CD拒否{m['cooldown_rejects']}")
    lines.append(f"  現在値: act_send CD {p['current']['cooldown_act_send_h']}h"
                 f" / strike_out {p['current']['strike_out']}"
                 f" / 上限 {p['current']['max_actions_per_cycle']}/サイクル")
    if p.get("note"):
        lines.append(f"  → {p['note']}")
    for pr in p.get("proposals", []):
        lines.append(f"  💡 {pr['param']}: {pr['current']} → {pr['proposed']}"
                     f" ({pr['reason']})")
    if p.get("proposals"):
        lines.append("  適用するには: brain-tact tune --apply")
    return "\n".join(lines)
