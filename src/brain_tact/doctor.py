"""brain-tact doctor — 環境・依存・権限の自己診断。

朝7時の定時発火が静かに失敗していた、を防ぐための健全性チェック。
"""

import json
import subprocess
import time
from pathlib import Path

from . import (
    ACTIONS_LOG,
    CYCLE_LOG,
    LAST_SUCCESS,
    LATEST_JSON,
    MCP_BRAIN_DRY_JSON,
    MCP_BRAIN_JSON,
    PENDING_JSON,
    STATE_DIR,
    claude_bin,
)

PLIST_DST = Path.home() / "Library" / "LaunchAgents" / "com.sgnb.brain-tact.plist"
DASH_PLIST_DST = (Path.home() / "Library" / "LaunchAgents"
                  / "com.sgnb.brain-tact-dashboard.plist")
SKILL_DST = Path.home() / ".claude" / "skills" / "brain" / "SKILL.md"
DASHBOARD_URL = "http://127.0.0.1:8787/api/state"


def precompact_block_enabled(settings: dict) -> bool:
    """settingsにauto-compact(matcher=auto)を止めるPreCompact hookがあるか(純関数)。

    ユーザーがsettings.jsonに登録する任意設定。brain_tactは登録を代行せず(ユーザーの
    領分)、設定状態の可視化(doctor)と設定スニペットの案内のみ行う。
    """
    for entry in (settings.get("hooks") or {}).get("PreCompact") or []:
        if entry.get("matcher") == "auto" and entry.get("hooks"):
            return True
    return False


def _check(name: str, fn) -> dict:
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001 — 診断自体は決して落とさない
        ok, detail = False, f"例外: {e}"
    return {"name": name, "ok": ok, "detail": detail}


def run_doctor() -> list[dict]:
    """全チェックを実行して結果リストを返す。"""
    checks = []

    def claude_cli():
        path = claude_bin()
        r = subprocess.run([path, "--version"], capture_output=True,
                           text=True, timeout=30)
        return r.returncode == 0, f"{path} ({r.stdout.strip()[:40]})"
    checks.append(_check("claude CLI", claude_cli))

    def lsof():
        r = subprocess.run(["/usr/sbin/lsof", "-v"], capture_output=True,
                           text=True, timeout=10)
        return r.returncode == 0, "/usr/sbin/lsof"
    checks.append(_check("lsof", lsof))

    def osascript():
        r = subprocess.run(
            ["osascript", "-e",
             'tell application "Terminal" to count windows'],
            capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return False, f"オートメーション権限を確認: {r.stderr.strip()[:80]}"
        return True, f"Terminal.app {r.stdout.strip()}ウィンドウ"
    checks.append(_check("osascript(TCC)", osascript))

    def mcp_configs():
        for p in (MCP_BRAIN_JSON, MCP_BRAIN_DRY_JSON):
            if not p.exists():
                return False, f"{p.name} が無い"
            json.loads(p.read_text())  # 構文チェック
        return True, "mcp-brain.json / mcp-brain-dry.json OK"
    checks.append(_check("MCP構成", mcp_configs))

    def ccusage():
        r = subprocess.run(["npx", "-y", "ccusage", "--version"],
                           capture_output=True, text=True, timeout=90)
        ok = r.returncode == 0
        return ok, (r.stdout.strip()[:30] if ok else "ccusage実行不可(攻めモード無効)")
    checks.append(_check("ccusage", ccusage))

    def launchd():
        if not PLIST_DST.exists():
            return False, "plist未配置(brain-tact install --launchd)"
        r = subprocess.run(["launchctl", "list", "com.sgnb.brain-tact"],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0, ("登録済み" if r.returncode == 0
                                    else "未ロード(launchctl load)")
    checks.append(_check("launchd(巡回)", launchd))

    def dashboard():
        # ダッシュボード常駐が死んでいてもdoctorが緑のままだった盲点の解消。
        # 登録チェックだけでなくHTTP死活まで見る(ポート競合等を捕まえる)
        if not DASH_PLIST_DST.exists():
            return True, "plist未配置(手動serve運用)"
        r = subprocess.run(["launchctl", "list", "com.sgnb.brain-tact-dashboard"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return False, "plist配置済みだが未ロード(launchctl load)"
        import urllib.request
        try:
            with urllib.request.urlopen(DASHBOARD_URL, timeout=3) as resp:
                resp.read(1)
            return True, "登録済み・HTTP応答あり(:8787)"
        except OSError:
            return False, "登録済みだがHTTP応答なし(:8787) — kickstartで再起動を"
    checks.append(_check("launchd(ダッシュボード)", dashboard))

    def skill():
        return SKILL_DST.exists(), str(SKILL_DST)
    checks.append(_check("/brainスキル", skill))

    def classify_health():
        # TUI変更でclassifyが静かに壊れていないか(最新スナップショットで判定)
        if not LATEST_JSON.exists():
            return True, "スナップショット無し(未稼働)"
        from .scan import classify_health_alert
        snap = json.loads(LATEST_JSON.read_text())
        alert = classify_health_alert(snap)
        if alert:
            return False, alert
        n = sum(1 for s in snap.get("sessions", []) if s.get("has_claude"))
        return True, f"claude稼働{n}タブの分類正常"
    checks.append(_check("分類健全性", classify_health))

    def state_health():
        if not STATE_DIR.is_dir():
            return False, "state/が無い"
        msgs = []
        if PENDING_JSON.exists():
            json.loads(PENDING_JSON.read_text())
        if LATEST_JSON.exists():
            age_h = (time.time() - LATEST_JSON.stat().st_mtime) / 3600
            msgs.append(f"latest.json {age_h:.1f}h前")
        if LAST_SUCCESS.exists():
            age_h = (time.time() - LAST_SUCCESS.stat().st_mtime) / 3600
            msgs.append(f"最終成功 {age_h:.1f}h前")
            if age_h > 8:
                return False, " / ".join(msgs) + " ← 8時間以上成功なし"
        return True, " / ".join(msgs) or "初期状態"
    checks.append(_check("state健全性", state_health))

    def recent_errors():
        if not CYCLE_LOG.exists():
            return True, "cycle.logなし(未稼働)"
        events = []
        for line in CYCLE_LOG.read_text().splitlines()[-20:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        # 最後に成功したサイクル以降のエラーだけを問題視する(解決済みは情報扱い)
        last_ok = -1
        for i, r in enumerate(events):
            if r.get("event") == "cycle_done" and r.get("ok"):
                last_ok = i
        bad = []
        for r in events[last_ok + 1:]:
            ev = r.get("event", "")
            if ev in ("cycle_crashed", "brain_timeout", "brain_failed_final",
                      "mcp_load_failure_final") or r.get("ok") is False:
                bad.append(f"{r.get('ts', '?')[:16]} {ev or 'cycle_failed'}")
        if bad:
            return False, "最終成功後にエラー: " + " / ".join(bad[-3:])
        return True, "最終成功サイクル以降エラーなし"
    checks.append(_check("直近サイクル", recent_errors))

    def actions_log_writable():
        ACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ACTIONS_LOG, "a"):
            pass
        return True, "書き込み可"
    checks.append(_check("actions.log", actions_log_writable))

    def precompact_block():
        # auto-compactブロックは任意設定。未設定でも問題視せず(ok=True)状態を示すだけ。
        sp = Path.home() / ".claude" / "settings.json"
        if not sp.exists():
            return True, "settings.json無し → 未設定(任意)"
        try:
            data = json.loads(sp.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return True, f"settings.json読めず → 状態不明({str(e)[:40]})"
        if precompact_block_enabled(data):
            return True, "有効(PreCompact matcher=auto) — 勝手な自動圧縮を防止中"
        return True, ("未設定(任意) — 有効化は settings.json の hooks に "
                      "PreCompact[matcher=auto → exit 2] を追加")
    checks.append(_check("auto-compactブロック", precompact_block))

    return checks


def format_doctor(checks: list[dict]) -> str:
    lines = ["🩺 brain-tact doctor"]
    for c in checks:
        mark = "✅" if c["ok"] else "❌"
        lines.append(f"{mark} {c['name']}: {c['detail']}")
    n_bad = sum(1 for c in checks if not c["ok"])
    lines.append("—— " + ("全項目OK 🎉" if n_bad == 0 else f"{n_bad}件の問題あり"))
    return "\n".join(lines)
