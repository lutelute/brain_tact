"""capture_all_tabs のタイムアウト耐性テスト。"""

import subprocess

import pytest

from brain_tact import terminal


def test_retries_on_timeout(monkeypatch):
    """1回目タイムアウト→2回目成功なら結果を返す。"""
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

        class R:
            returncode = 0
            stdout = ""
        return R()

    monkeypatch.setattr(terminal.subprocess, "run", fake_run)
    monkeypatch.setattr(terminal.time, "sleep", lambda s: None)
    result = terminal.capture_all_tabs(timeout=1, retries=2)
    assert result == []
    assert calls["n"] == 2  # リトライした


def test_raises_after_all_retries(monkeypatch):
    """全リトライ失敗なら RuntimeError(クラッシュではなく呼び出し側で吸収)。"""
    def always_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(terminal.subprocess, "run", always_timeout)
    monkeypatch.setattr(terminal.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="タイムアウト"):
        terminal.capture_all_tabs(timeout=1, retries=2)
