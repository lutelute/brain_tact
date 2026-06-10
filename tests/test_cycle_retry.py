"""脳の一時障害リトライ(_transient_failure / _run_brain_with_retry)のテスト。

実例(2026-06-10 17時): ECONNRESETで巡回が丸ごと欠けた。MCPロード失敗だけ
でなくAPIエラーもリトライ対象であることを回帰テストで固定する。
"""

import pytest

import brain_tact.cycle as cycle


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    """ログ書き込み・incident記録・sleepを無効化(実state/を汚さない)。"""
    monkeypatch.setattr(cycle, "_log_cycle", lambda r: None)
    monkeypatch.setattr(cycle, "record_incident", lambda e: None)
    monkeypatch.setattr(cycle.time, "sleep", lambda s: None)


class TestTransientFailure:
    def test_success_is_none(self):
        assert cycle._transient_failure(
            {"result_text": "巡回完了", "is_error": False}) is None

    def test_mcp_load_failure(self):
        why = cycle._transient_failure(
            {"result_text": "MCP_LOAD_FAILURE", "is_error": False})
        assert why and "MCP" in why

    def test_api_error(self):
        why = cycle._transient_failure(
            {"result_text": "API Error: Unable to connect (ECONNRESET)",
             "is_error": True})
        assert why and "エラー終了" in why

    def test_empty_result_with_error(self):
        assert cycle._transient_failure({"is_error": True}) is not None


class TestRunBrainWithRetry:
    def test_no_retry_on_success(self, monkeypatch):
        calls = []
        monkeypatch.setattr(cycle, "_run_brain", lambda *a: (
            calls.append(1), {"is_error": False, "result_text": "ok"})[1])
        brain = cycle._run_brain_with_retry("p", "c1", "sonnet", True)
        assert brain["result_text"] == "ok"
        assert len(calls) == 1

    def test_retries_once_then_succeeds(self, monkeypatch):
        results = [
            {"is_error": True, "result_text": "API Error: ECONNRESET"},
            {"is_error": False, "result_text": "ok"},
        ]
        calls = []
        monkeypatch.setattr(cycle, "_run_brain", lambda *a: (
            calls.append(1), results[len(calls) - 1])[1])
        brain = cycle._run_brain_with_retry("p", "c1", "sonnet", True)
        assert brain["result_text"] == "ok"
        assert len(calls) == 2

    def test_gives_up_after_two_failures(self, monkeypatch):
        monkeypatch.setattr(cycle, "_run_brain", lambda *a: {
            "is_error": True, "result_text": "API Error"})
        assert cycle._run_brain_with_retry("p", "c1", "sonnet", True) is None

    def test_mcp_failure_then_success(self, monkeypatch):
        """従来のMCPロード失敗リトライも同経路で動く。"""
        results = [
            {"is_error": False, "result_text": "MCP_LOAD_FAILURE"},
            {"is_error": False, "result_text": "巡回完了"},
        ]
        calls = []
        monkeypatch.setattr(cycle, "_run_brain", lambda *a: (
            calls.append(1), results[len(calls) - 1])[1])
        brain = cycle._run_brain_with_retry("p", "c1", "sonnet", True)
        assert brain["result_text"] == "巡回完了"
        assert len(calls) == 2
