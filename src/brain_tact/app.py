"""brain_tact メニューバーアプリ — 通知とボタンだけの簡易UI(rumps)。

メニューバーに 🧠+保留数 を常駐表示し:
- 新しい保留項目・巡回完了を macOS 通知で知らせる
- 保留項目をワンクリックで処理(推奨アクション実行 / 解決済みにする)
- 「今すぐスキャン」「今すぐ巡回」ボタン

起動: uv run brain-tact-app  (ログイン自動起動は install --app)
"""

import json
import subprocess
import threading

import rumps

from . import BRAIN_DIR, CYCLE_LOG, LATEST_JSON
from .state import load_pending, resolve_pending

REFRESH_SEC = 30
APP_CYCLE_ID = "app-manual"


def _notify(title: str, message: str) -> None:
    """通知。rumpsが失敗したらosascriptにフォールバック。"""
    try:
        rumps.notification(title, "", message[:180])
    except Exception:
        safe = message[:180].replace('"', "'")
        safe_t = title.replace('"', "'")
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe}" with title "{safe_t}"'],
            capture_output=True, timeout=10,
        )


def _run_actuator_tool(tool: str, args: dict) -> str:
    """suggested_action をactuator関数(ガードレール込み)で実行する。"""
    import os
    os.environ.setdefault("BRAIN_CYCLE_ID", APP_CYCLE_ID)
    from . import actuator
    fn = {
        "act_send": actuator.act_send,
        "act_approve": actuator.act_approve,
        "act_resume": actuator.act_resume,
    }.get(tool)
    if fn is None:
        return f"未対応のツール: {tool}"
    try:
        return fn(**args)
    except TypeError as e:
        return f"引数エラー: {e}"


class BrainApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("🧠", quit_button=None)
        self._known_pending: set[str] = set()
        self._last_cycle_ts: str | None = None
        self._first_refresh = True
        self._timer = rumps.Timer(self._refresh, REFRESH_SEC)
        self._timer.start()
        self._refresh(None)
        print(f"[app] menu ready: title={self.title} "
              f"items={len(self.menu)}", flush=True)

    # ------------------------------------------------------------------
    # 定期更新
    # ------------------------------------------------------------------

    def _refresh(self, _sender) -> None:
        pending = [i for i in load_pending().get("items", [])
                   if i["status"] == "open"]

        self.title = f"🧠{len(pending)}" if pending else "🧠"

        # 新規保留を通知(初回読み込み分は既知扱いにして通知しない)
        current_ids = {i["id"] for i in pending}
        if not self._first_refresh:
            for item in pending:
                if item["id"] not in self._known_pending:
                    _notify(
                        f"🧠 保留: {item.get('project') or item['tty']}",
                        item["summary"],
                    )
        self._known_pending = current_ids

        # 巡回完了の通知
        self._check_cycle_done()
        self._rebuild_menu(pending)
        self._first_refresh = False

    def _check_cycle_done(self) -> None:
        if not CYCLE_LOG.exists():
            return
        last = None
        for line in CYCLE_LOG.read_text().splitlines()[-5:]:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("event") == "cycle_done":
                last = r
        if last is None:
            return
        ts = last.get("ts")
        if ts and ts != self._last_cycle_ts:
            if self._last_cycle_ts is not None:  # 起動直後の過去分は通知しない
                ok = "✅" if last.get("ok") else "❌"
                _notify("🧠 巡回完了 " + ok,
                        f"{last.get('cycle_id')} / "
                        f"{last.get('duration_s', '?')}s")
            self._last_cycle_ts = ts

    # ------------------------------------------------------------------
    # メニュー構築
    # ------------------------------------------------------------------

    def _rebuild_menu(self, pending: list[dict]) -> None:
        self.menu.clear()

        # 状況サマリ(クリックでスキャン更新)
        summary = "状況: 未スキャン"
        try:
            snap = json.loads(LATEST_JSON.read_text())
            t = snap["totals"]
            by = t.get("by_state", {})
            usage = t.get("usage") or {}
            pct = usage.get("pct")
            usage_s = f" / 枠{pct:.0f}%" if pct is not None else ""
            summary = (f"稼働{by.get('RUNNING', 0)} 待機{by.get('IDLE', 0)}"
                       f" 全{t.get('tabs', 0)}タブ{usage_s}"
                       f"  ({snap.get('taken_at', '')[11:16]})")
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        self.menu.add(rumps.MenuItem(summary))
        self.menu.add(rumps.separator)

        # 保留項目
        if pending:
            for item in pending:
                label = (f"⏸ {item.get('project') or item['tty']}: "
                         f"{item['summary'][:45]}")
                mi = rumps.MenuItem(label)
                for sa in (item.get("suggested_actions") or [])[:3]:
                    sa_label = sa.get("label") or sa.get("tool", "実行")
                    mi.add(rumps.MenuItem(
                        f"▶ {sa_label}",
                        callback=self._make_action_cb(item, sa),
                    ))
                mi.add(rumps.MenuItem(
                    "✓ 解決済みにする(何もしない)",
                    callback=self._make_resolve_cb(item),
                ))
                self.menu.add(mi)
        else:
            self.menu.add(rumps.MenuItem("保留なし 🎉"))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("🔄 今すぐスキャン", callback=self._do_scan))
        self.menu.add(rumps.MenuItem("🧠 今すぐ巡回(LINE 1push)",
                                     callback=self._do_cycle))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("終了", callback=rumps.quit_application))

    # ------------------------------------------------------------------
    # アクション
    # ------------------------------------------------------------------

    def _make_action_cb(self, item: dict, sa: dict):
        def cb(_sender):
            result = _run_actuator_tool(sa.get("tool", ""), sa.get("args") or {})
            if result.startswith("✅") or result.startswith("🧪"):
                resolve_pending(item["id"],
                                f"アプリから実行: {sa.get('label', sa.get('tool'))}")
            _notify("🧠 実行結果", result)
            self._refresh(None)
        return cb

    def _make_resolve_cb(self, item: dict):
        def cb(_sender):
            resolve_pending(item["id"], "アプリから解決済みにした")
            _notify("🧠", f"解決済み: {item['summary'][:60]}")
            self._refresh(None)
        return cb

    def _do_scan(self, _sender) -> None:
        def work():
            subprocess.run(
                ["uv", "run", "--directory", str(BRAIN_DIR),
                 "brain-tact", "scan", "--quick"],
                capture_output=True, timeout=120,
            )
            self._refresh(None)
        threading.Thread(target=work, daemon=True).start()
        _notify("🧠", "スキャン中…")

    def _do_cycle(self, _sender) -> None:
        res = rumps.alert(
            "今すぐ巡回しますか?",
            "脳が全セッションを判断し、LINEに1push送信されます(2〜4分)。",
            ok="巡回する", cancel="やめる",
        )
        if res != 1:
            return

        def work():
            subprocess.run(
                ["uv", "run", "--directory", str(BRAIN_DIR),
                 "brain-tact", "cycle", "--force"],
                capture_output=True, timeout=1200,
            )
            self._refresh(None)
        threading.Thread(target=work, daemon=True).start()
        _notify("🧠", "巡回を開始しました(完了時に通知します)")


def main() -> None:
    BrainApp().run()


if __name__ == "__main__":
    main()
