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
