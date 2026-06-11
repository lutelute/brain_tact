"""異常検知(Lv80)のテスト。"""

from brain_tact.anomaly import detect_anomalies


def _snap(tabs=5, claude=5):
    return {"totals": {"tabs": tabs, "claude": claude}}


def _done(cost):
    return {"event": "cycle_done", "ok": True, "cost_usd": cost}


class TestDetect:
    def test_all_normal(self):
        events = [_done(0.4), _done(0.5), _done(0.45)]
        assert detect_anomalies(_snap(), events) == []

    def test_total_shutdown(self):
        out = detect_anomalies(_snap(tabs=8, claude=0), [])
        assert len(out) == 1 and "全停止" in out[0]

    def test_no_tabs_is_not_shutdown(self):
        """タブ自体が無い(Terminal閉鎖)は全停止扱いしない。"""
        assert detect_anomalies(_snap(tabs=0, claude=0), []) == []

    def test_three_consecutive_failures(self):
        events = [{"event": "cycle_crashed"}, {"event": "brain_timeout"},
                  {"event": "cycle_done", "ok": False}]
        out = detect_anomalies(_snap(), events)
        assert any("3回連続" in a for a in out)

    def test_skipped_does_not_count(self):
        """skipped(デバウンス)は失敗系列に数えない。"""
        events = [{"event": "cycle_crashed"}, {"event": "skipped"},
                  {"event": "cycle_crashed"}, {"event": "cycle_done", "ok": True}]
        assert detect_anomalies(_snap(), events) == []

    def test_abnormal_cost(self):
        events = [_done(0.4), _done(0.5), _done(0.45), _done(2.5)]
        out = detect_anomalies(_snap(), events)
        assert any("異常コスト" in a for a in out)

    def test_cost_floor(self):
        """平均が低くても$2未満では騒がない。"""
        events = [_done(0.1), _done(0.1), _done(0.1), _done(1.5)]
        assert detect_anomalies(_snap(), events) == []
