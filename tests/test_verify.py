"""verify(介入効果の検証)のテスト。"""

from datetime import datetime, timedelta

import pytest

from brain_tact import state, verify
from brain_tact.verify import _judge, summarize_outcomes, verify_interventions


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "ACTIONS_LOG", tmp_path / "actions.log")
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    return tmp_path


def _ts(ago_min: float = 30.0) -> str:
    return (datetime.now().astimezone() - timedelta(minutes=ago_min)).isoformat(
        timespec="seconds")


def session(state_hint="IDLE", has_claude=True, jsonl_mtime=None):
    return {"tty": "/dev/ttys001", "state_hint": state_hint,
            "has_claude": has_claude, "jsonl_mtime": jsonl_mtime}


class TestJudge:
    def test_send_then_running(self):
        a = {"tool": "act_send", "ts": _ts(30)}
        assert _judge(a, session("RUNNING")) == "reactivated"

    def test_send_then_jsonl_advanced(self):
        """今はIDLEでも介入後に作業が進んでいればreactivated。"""
        a = {"tool": "act_send", "ts": _ts(30)}
        t_after = datetime.now().timestamp() - 10 * 60  # 介入の20分後に更新
        assert _judge(a, session("IDLE", jsonl_mtime=t_after)) == "reactivated"

    def test_send_no_movement(self):
        a = {"tool": "act_send", "ts": _ts(30)}
        t_before = datetime.now().timestamp() - 60 * 60  # 介入より前のまま
        assert _judge(a, session("IDLE", jsonl_mtime=t_before)) == "no_change"

    def test_send_then_dead(self):
        a = {"tool": "act_send", "ts": _ts(30)}
        assert _judge(a, session("DEAD_SHELL", has_claude=False)) == "worse"

    def test_resume_success(self):
        a = {"tool": "act_resume", "ts": _ts(30)}
        assert _judge(a, session("IDLE", has_claude=True)) == "reactivated"

    def test_resume_failure(self):
        a = {"tool": "act_resume", "ts": _ts(30)}
        assert _judge(a, session("PLAIN_SHELL", has_claude=False)) == "no_change"

    def test_tab_closed(self):
        a = {"tool": "act_send", "ts": _ts(30)}
        assert _judge(a, None) == "unknown"


class TestVerifyInterventions:
    def _snapshot(self, **kw):
        return {"cycle_id": "c2", "sessions": [session(**kw)]}

    def test_verifies_sent_action_once(self):
        state.log_action({"ts": _ts(60), "cycle_id": "c1", "tool": "act_send",
                          "tty": "/dev/ttys001", "result": "sent"})
        snap = self._snapshot(state_hint="RUNNING")
        r1 = verify_interventions(snap)
        assert len(r1) == 1 and r1[0]["result"] == "reactivated"
        # 2回目は検証済みなのでスキップ
        r2 = verify_interventions(snap)
        assert r2 == []

    def test_skips_dry_run_and_rejected(self):
        state.log_action({"ts": _ts(60), "cycle_id": "c1", "tool": "act_send",
                          "tty": "/dev/ttys001", "result": "sent", "dry_run": True})
        state.log_action({"ts": _ts(50), "cycle_id": "c1", "tool": "act_send",
                          "tty": "/dev/ttys001", "result": "rejected: x"})
        assert verify_interventions(self._snapshot()) == []


def test_summarize():
    rs = [{"result": "reactivated"}, {"result": "reactivated"},
          {"result": "no_change"}]
    assert summarize_outcomes(rs) == "前回介入3件: 効果2 / 不発1"
    assert summarize_outcomes([]) == ""


class TestGitProgress:
    """C1: 介入の「動いた」と「価値を生んだ(実コミット)」を区別する裏取り。"""

    def _action(self, dirty=10, unix=1000, cwd="/repo"):
        return {"tool": "act_send", "ts": _ts(30), "cwd": cwd,
                "git_before": {"dirty": dirty, "last_commit_unix": unix}}

    def _session(self, dirty=10, unix=1000, cwd="/repo"):
        s = session("IDLE")
        s["cwd"] = cwd
        s["git"] = {"dirty": dirty, "last_commit_unix": unix}
        return s

    def test_committed_detected(self):
        from brain_tact.verify import _git_progress
        p = _git_progress(self._action(unix=1000), self._session(unix=2000))
        assert p["committed"] is True

    def test_no_commit(self):
        from brain_tact.verify import _git_progress
        p = _git_progress(self._action(unix=1000), self._session(unix=1000))
        assert p["committed"] is False

    def test_dirty_delta(self):
        from brain_tact.verify import _git_progress
        p = _git_progress(self._action(dirty=12), self._session(dirty=3))
        assert p["dirty_delta"] == -9

    def test_cwd_mismatch_returns_none(self):
        from brain_tact.verify import _git_progress
        p = _git_progress(self._action(cwd="/repo-a"), self._session(cwd="/repo-b"))
        assert p is None

    def test_no_git_before_returns_none(self):
        from brain_tact.verify import _git_progress
        a = {"tool": "act_send", "ts": _ts(30)}
        assert _git_progress(a, self._session()) is None

    def test_verify_record_includes_git_progress(self):
        state.log_action({
            "ts": _ts(60), "cycle_id": "c1", "tool": "act_send",
            "tty": "/dev/ttys001", "result": "sent", "cwd": "/repo",
            "git_before": {"dirty": 5, "last_commit_unix": 1000}})
        snap = {"cycle_id": "c2", "sessions": [self._session(dirty=0, unix=2000)]}
        snap["sessions"][0]["state_hint"] = "RUNNING"
        r = verify_interventions(snap)
        assert r[0]["git_progress"] == {"committed": True, "dirty_delta": -5}

    def test_summarize_includes_commits(self):
        rs = [{"result": "reactivated", "git_progress": {"committed": True}},
              {"result": "reactivated"}]
        assert "実コミット1" in summarize_outcomes(rs)
