"""パラメータ調整提案(Lv75)のテスト。"""

import pytest

from brain_tact import state, tune


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "_tuning_path", lambda: tmp_path / "tuning.json")
    monkeypatch.setattr(state, "ensure_dirs", lambda: None)
    # モジュール定数をテストごとに初期値へ
    monkeypatch.setitem(state.COOLDOWN_HOURS, "act_send", 6.0)
    monkeypatch.setattr(state, "STRIKE_OUT", 2)
    return tmp_path


def _verify(result, committed=None):
    r = {"tool": "verify", "target_tool": "act_send", "result": result}
    if committed is not None:
        r["git_progress"] = {"committed": committed}
    return r


class TestPropose:
    def test_insufficient_data(self, monkeypatch):
        monkeypatch.setattr(tune, "read_actions", lambda hours: [_verify("reactivated")] * 3)
        p = tune.propose()
        assert "データ不足" in p["note"] and p["proposals"] == []

    def test_high_dud_rate_extends_cooldown(self, monkeypatch):
        recs = [_verify("reactivated")] * 6 + [_verify("no_change")] * 6
        monkeypatch.setattr(tune, "read_actions", lambda hours: recs)
        p = tune.propose()
        cd = [x for x in p["proposals"] if x["param"] == "cooldown_hours.act_send"]
        assert cd and cd[0]["proposed"] == 9.0

    def test_aligned_no_proposals(self, monkeypatch):
        recs = [_verify("reactivated", committed=True)] * 12
        monkeypatch.setattr(tune, "read_actions", lambda hours: recs)
        p = tune.propose()
        assert p["proposals"] == [] and "整合" in p["note"]

    def test_apply_writes_and_reload_respects_range(self, monkeypatch, tmp_path):
        recs = [_verify("reactivated")] * 6 + [_verify("no_change")] * 6
        monkeypatch.setattr(tune, "read_actions", lambda hours: recs)
        p = tune.propose()
        tune.apply_proposals(p)
        assert state.load_tuning()["cooldown_hours"]["act_send"] == 9.0
        applied = state.apply_tuning()
        assert any("act_send=9.0h" in a for a in applied)
        assert state.COOLDOWN_HOURS["act_send"] == 9.0

    def test_apply_tuning_rejects_out_of_range(self, monkeypatch):
        state.save_tuning({"cooldown_hours": {"act_send": 100.0},
                           "strike_out": 99})
        applied = state.apply_tuning()
        assert applied == []  # 安全レンジ外は無視
        assert state.COOLDOWN_HOURS["act_send"] == 6.0
