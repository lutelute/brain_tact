"""state.py のガードレールロジック(上限・クールダウン・pending)のテスト。"""

from datetime import datetime, timedelta

import pytest

from brain_tact import state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """実際のstate/を汚さないよう全パスをtmpに差し替える。"""
    monkeypatch.setattr(state, "ACTIONS_LOG", tmp_path / "actions.log")
    monkeypatch.setattr(state, "PENDING_JSON", tmp_path / "pending.json")
    monkeypatch.setattr(state, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(state, "LAST_SUCCESS", tmp_path / "last_success")
    monkeypatch.setattr(state, "LOCK_FILE", tmp_path / "cycle.lock")
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    return tmp_path


def _sent(tty: str, tool: str, cycle: str, ago_hours: float = 0.0) -> None:
    ts = (datetime.now().astimezone() - timedelta(hours=ago_hours)).isoformat(
        timespec="seconds")
    state.log_action({
        "ts": ts, "cycle_id": cycle, "tool": tool, "tty": tty,
        "payload": {}, "reason": "t", "result": "sent",
    })


class TestCheckLimits:
    def test_allows_first_action(self):
        ok, _ = state.check_limits("/dev/ttys001", "act_send", "c1")
        assert ok

    def test_per_tty_per_cycle(self):
        _sent("/dev/ttys001", "act_send", "c1")
        ok, why = state.check_limits("/dev/ttys001", "act_send", "c1")
        assert not ok and "1回実行済み" in why

    def test_approve_allows_three(self):
        _sent("/dev/ttys001", "act_approve", "c1")
        _sent("/dev/ttys001", "act_approve", "c1")
        ok, _ = state.check_limits("/dev/ttys001", "act_approve", "c1")
        assert ok
        _sent("/dev/ttys001", "act_approve", "c1")
        ok, why = state.check_limits("/dev/ttys001", "act_approve", "c1")
        assert not ok

    def test_cooldown_across_cycles(self):
        """サイクルが変わっても6時間以内のact_sendはクールダウン拒否。"""
        _sent("/dev/ttys001", "act_send", "c1", ago_hours=2.0)
        ok, why = state.check_limits("/dev/ttys001", "act_send", "c2")
        assert not ok and "クールダウン" in why

    def test_cooldown_expires(self):
        _sent("/dev/ttys001", "act_send", "c1", ago_hours=7.0)
        ok, _ = state.check_limits("/dev/ttys001", "act_send", "c2")
        assert ok

    def test_resume_cooldown_12h(self):
        _sent("/dev/ttys001", "act_resume", "c1", ago_hours=10.0)
        ok, why = state.check_limits("/dev/ttys001", "act_resume", "c2")
        assert not ok
        _sent("/dev/ttys002", "act_resume", "c1", ago_hours=13.0)
        ok, _ = state.check_limits("/dev/ttys002", "act_resume", "c2")
        assert ok

    def test_cycle_total_cap(self):
        for i in range(state.MAX_ACTIONS_PER_CYCLE):
            _sent(f"/dev/ttys{i:03d}", "act_send", "c1")
        ok, why = state.check_limits("/dev/ttys999", "act_send", "c1")
        assert not ok and "上限" in why

    def test_rejections_dont_count(self):
        """拒否された記録(result != sent)は上限カウントに入らない。"""
        state.log_action({"cycle_id": "c1", "tool": "act_send",
                          "tty": "/dev/ttys001", "result": "rejected: x"})
        ok, _ = state.check_limits("/dev/ttys001", "act_send", "c1")
        assert ok


def _verify(tty: str, result: str, ago_hours: float) -> None:
    ts = (datetime.now().astimezone() - timedelta(hours=ago_hours)).isoformat(
        timespec="seconds")
    state.log_action({"ts": ts, "cycle_id": "cx", "tool": "verify",
                      "tty": tty, "target_tool": "act_send", "result": result})


class TestThreeStrikes:
    def test_two_consecutive_duds_block_send(self):
        _verify("/dev/ttys001", "no_change", 12.0)
        _verify("/dev/ttys001", "no_change", 6.0)
        ok, why = state.check_limits("/dev/ttys001", "act_send", "c9")
        assert not ok and "3ストライク" in why

    def test_reactivated_resets_streak(self):
        """間に効いた介入があれば連続カウントはリセット。"""
        _verify("/dev/ttys001", "no_change", 24.0)
        _verify("/dev/ttys001", "reactivated", 12.0)
        _verify("/dev/ttys001", "no_change", 6.0)
        ok, _ = state.check_limits("/dev/ttys001", "act_send", "c9")
        assert ok

    def test_strikes_dont_block_other_ttys(self):
        _verify("/dev/ttys001", "no_change", 12.0)
        _verify("/dev/ttys001", "no_change", 6.0)
        ok, _ = state.check_limits("/dev/ttys002", "act_send", "c9")
        assert ok

    def test_strikes_dont_block_resume(self):
        """3ストライクはact_sendのみ。復元(resume)は別物。"""
        _verify("/dev/ttys001", "no_change", 12.0)
        _verify("/dev/ttys001", "no_change", 6.0)
        ok, _ = state.check_limits("/dev/ttys001", "act_resume", "c9")
        assert ok


class TestPending:
    def test_add_and_resolve(self):
        item_id = state.add_pending("/dev/ttys001", "approval", "rm承認待ち", "c1")
        items = state.load_pending()["items"]
        assert len(items) == 1 and items[0]["status"] == "open"
        assert state.resolve_pending(item_id, "承認した")
        assert state.load_pending()["items"][0]["status"] == "resolved"

    def test_supersede_same_tty_kind(self):
        """同tty同kindの古いopen項目は新規追加時にsupersededになる。"""
        state.add_pending("/dev/ttys001", "approval", "古い", "c1")
        state.add_pending("/dev/ttys001", "approval", "新しい", "c2")
        items = state.load_pending()["items"]
        statuses = sorted(i["status"] for i in items)
        assert statuses == ["open", "superseded"]
        open_item = next(i for i in items if i["status"] == "open")
        assert open_item["summary"] == "新しい"

    def test_resolve_unknown_returns_false(self):
        assert not state.resolve_pending("p-nope", "x")


class TestLockDebounce:
    def test_lock_exclusive(self):
        assert state.acquire_cycle_lock()
        assert not state.acquire_cycle_lock()
        state.release_cycle_lock()
        assert state.acquire_cycle_lock()
        state.release_cycle_lock()

    def test_debounce(self):
        assert not state.should_debounce()  # 初回は実行可
        state.mark_cycle_success()
        assert state.should_debounce()      # 直後は抑止


class TestManualBypass:
    """手動操作(manual=True)はクールダウンをバイパスする検証(check_limitsは脳用)。"""
    def test_manual_skips_check_limits_logic(self):
        # check_limits自体は脳用に変更なし(クールダウン拒否)
        _sent("/dev/ttys001", "act_send", "c1", ago_hours=2.0)
        ok, _ = state.check_limits("/dev/ttys001", "act_send", "c2")
        assert not ok  # 脳ならクールダウン拒否
        # manual経路は_guarded_sendでcheck_limitsを呼ばない(actuator側の分岐)
        # = 統合はactuatorのmanualフラグで担保(ここではcheck_limitsの脳用挙動のみ確認)


class TestRotateLogs:
    def _patch_logs(self, monkeypatch, tmp_path):
        paths = {}
        for name in ("ACTIONS_LOG", "CYCLE_LOG", "INCIDENTS_LOG"):
            p = tmp_path / f"{name.lower()}.log"
            monkeypatch.setattr(state, name, p)
            paths[name] = p
        return paths

    def _line(self, ago_days: float) -> str:
        import json
        ts = (datetime.now().astimezone() - timedelta(days=ago_days)).isoformat(
            timespec="seconds")
        return json.dumps({"ts": ts, "tool": "act_send", "result": "sent"})

    def test_drops_old_keeps_recent(self, monkeypatch, tmp_path):
        logs = self._patch_logs(monkeypatch, tmp_path)
        logs["ACTIONS_LOG"].write_text(
            self._line(ago_days=120) + "\n" + self._line(ago_days=1) + "\n")
        n = state.rotate_logs()
        assert n == 1
        remaining = logs["ACTIONS_LOG"].read_text().splitlines()
        assert len(remaining) == 1

    def test_keeps_unparsable_lines(self, monkeypatch, tmp_path):
        """tsの読めない行は監査の欠落を避けるため残す。"""
        logs = self._patch_logs(monkeypatch, tmp_path)
        logs["CYCLE_LOG"].write_text("not-json\n" + self._line(ago_days=200) + "\n")
        n = state.rotate_logs()
        assert n == 1
        assert logs["CYCLE_LOG"].read_text().splitlines() == ["not-json"]

    def test_noop_when_all_recent(self, monkeypatch, tmp_path):
        logs = self._patch_logs(monkeypatch, tmp_path)
        content = self._line(ago_days=2) + "\n"
        logs["INCIDENTS_LOG"].write_text(content)
        mtime_before = logs["INCIDENTS_LOG"].stat().st_mtime
        assert state.rotate_logs() == 0
        # 変化なしなら書き戻さない(mtime温存)
        assert logs["INCIDENTS_LOG"].stat().st_mtime == mtime_before

    def test_missing_files_ok(self, monkeypatch, tmp_path):
        self._patch_logs(monkeypatch, tmp_path)
        assert state.rotate_logs() == 0
