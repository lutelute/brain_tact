"""stats(KPI集計)のテスト — Lv40 介入品質スコアを中心に。"""

import pytest

from brain_tact import stats


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(stats, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(stats, "load_pending",
                        lambda: {"items": []})
    return tmp_path


def _verify_rec(result, git_progress=None):
    r = {"tool": "verify", "result": result}
    if git_progress is not None:
        r["git_progress"] = git_progress
    return r


class TestQualityScore:
    def test_score_weights(self, monkeypatch):
        """produced=1.0 / moved=0.5 / silent=0 の加重平均。"""
        recs = [
            _verify_rec("reactivated", {"committed": True,
                                        "commits": ["abc fix"]}),  # produced
            _verify_rec("reactivated"),                            # moved
            _verify_rec("no_change"),                              # silent
            _verify_rec("unknown"),                                # スコア外
        ]
        monkeypatch.setattr(stats, "read_actions", lambda hours: recs)
        s = stats.compute_stats(days=1)
        ef = s["effectiveness"]
        assert ef["quality"] == {"produced": 1, "moved": 1, "silent": 1}
        assert ef["quality_score_pct"] == 50  # (1.0+0.5+0)/3
        assert ef["sample_commits"] == ["abc fix"]

    def test_no_verifies(self, monkeypatch):
        monkeypatch.setattr(stats, "read_actions", lambda hours: [])
        s = stats.compute_stats(days=1)
        assert s["effectiveness"]["quality_score_pct"] is None

    def test_backward_compat_old_records(self, monkeypatch):
        """git_progressなしの過去レコードでも壊れない。"""
        recs = [_verify_rec("reactivated"), _verify_rec("no_change")]
        monkeypatch.setattr(stats, "read_actions", lambda hours: recs)
        s = stats.compute_stats(days=1)
        assert s["effectiveness"]["quality_score_pct"] == 25  # 0.5/2

    def test_format_shows_quality(self, monkeypatch):
        recs = [_verify_rec("reactivated",
                            {"committed": True, "commits": ["abc feat: x"]})]
        monkeypatch.setattr(stats, "read_actions", lambda hours: recs)
        out = stats.format_stats(stats.compute_stats(days=1))
        assert "品質スコア 100%" in out
        assert "abc feat: x" in out


class TestWeeklySummary:
    def test_three_lines(self, monkeypatch):
        recs = [
            {"tool": "act_send", "result": "sent"},
            {"tool": "verify", "result": "reactivated",
             "git_progress": {"committed": True}},
            {"tool": "defer"},
        ]
        monkeypatch.setattr(stats, "read_actions", lambda hours: recs)
        out = stats.weekly_summary(stats.compute_stats(days=7))
        assert "介入1件" in out
        assert "品質スコア100%" in out and "実コミット1" in out
        assert "保留: 新規1" in out
        assert len(out.splitlines()) <= 3
