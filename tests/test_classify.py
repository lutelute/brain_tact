"""classify() のfixtureベーステスト。

fixtures/screens/ の実機捕捉画面+合成画面を分類し、期待状態と照合する。
"""

from pathlib import Path

import pytest

from brain_tact.classify import classify
from brain_tact.procs import ClaudeProc
from brain_tact.sessions import SessionInfo

FIXTURES = Path(__file__).parent / "fixtures" / "screens"


def proc(cpu: float = 3.0) -> ClaudeProc:
    return ClaudeProc(
        pid=12345, tty="/dev/ttys099", cpu_pct=cpu,
        etime="01:00:00", etime_min=60.0,
        cmd="claude",
    )


def session(age_min: float = 5.0) -> SessionInfo:
    import time
    return SessionInfo(
        jsonl_path="/tmp/x.jsonl", session_id="x",
        mtime=time.time() - age_min * 60, age_min=age_min, ambiguous=False,
    )


def load(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text()


# (fixture名, proc, session, prev_state, 期待state_hint)
CASES = [
    ("idle_recap", proc(0.3), session(52.6), None, "IDLE"),
    ("running_tokens", proc(6.0), session(0.2), None, "RUNNING"),
    ("running_thinking", proc(4.6), session(0.3), None, "RUNNING"),
    ("awaiting_approval", proc(0.1), session(12.0), None, "AWAITING_APPROVAL"),
    ("error_retrying", proc(0.5), session(8.0), None, "ERROR_RETRYING"),
    ("plain_shell", None, None, None, "PLAIN_SHELL"),
    # 前回claudeが居たタブにプロセスが居ない → 死亡判定
    ("plain_shell", None, None, "RUNNING", "DEAD_SHELL"),
]


@pytest.mark.parametrize("name,p,s,prev,expected", CASES)
def test_classify_fixtures(name, p, s, prev, expected):
    result = classify(load(name), p, s, prev)
    assert result.state_hint == expected, (
        f"{name}: expected {expected}, got {result.state_hint} "
        f"(signals={result.signals})"
    )


def test_idle_recap_signal():
    """折り返されたrecapマークも検出できる。"""
    result = classify(load("idle_recap"), proc(0.3), session(52.6), None)
    assert result.signals.get("has_recap") is True


def test_running_elapsed_extracted():
    """スピナー行から経過分が抽出される。"""
    result = classify(load("running_tokens"), proc(6.0), session(0.2), None)
    assert result.signals.get("turn_elapsed_min") == pytest.approx(29.1, abs=0.1)


def test_stalled_detection():
    """画面はRUNNINGだがjsonl 30分以上停止+CPUゼロ → stalledシグナル。"""
    result = classify(load("running_tokens"), proc(0.0), session(45.0), None)
    assert result.state_hint == "RUNNING"
    assert result.signals.get("stalled") is True
    assert result.attention is True


def test_running_not_attention():
    """健全なRUNNINGはattention対象外(画面を短く渡す)。"""
    result = classify(load("running_tokens"), proc(6.0), session(0.2), None)
    assert result.attention is False


def test_approval_takes_priority_over_stale_spinner():
    """承認ボックスが最下部にあれば、上に残ったスピナー痕跡よりも優先。"""
    screen = load("running_tokens") + "\n" + load("awaiting_approval")
    result = classify(screen, proc(0.1), session(3.0), None)
    assert result.state_hint == "AWAITING_APPROVAL"
