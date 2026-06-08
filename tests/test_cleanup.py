"""掃除判定エンジンのテスト。"""

from brain_tact.cleanup import (
    ACTIVE,
    CLOSEABLE,
    NEEDS_HANDOVER,
    NEEDS_USER,
    RESUMABLE,
    judge_session,
    summarize,
)


def rec(state="IDLE", age=None, dirty=None, last=None,
        context_full=False, stalled=False, stagnant=0):
    signals = {}
    if age is not None:
        signals["jsonl_age_min"] = age
    if context_full:
        signals["context_full"] = True
    if stalled:
        signals["stalled"] = True
    return {
        "tty": "/dev/ttys001", "project": "demo",
        "state_hint": state, "signals": signals,
        "git": {"dirty": dirty} if dirty is not None else {},
        "last_assistant": last,
        "progress": {"stagnant_cycles": stagnant},
    }


class TestCloseable:
    def test_dead_shell(self):
        assert judge_session(rec(state="DEAD_SHELL"))["category"] == CLOSEABLE

    def test_plain_shell(self):
        assert judge_session(rec(state="PLAIN_SHELL"))["category"] == CLOSEABLE

    def test_done_no_dirty(self):
        j = judge_session(rec("IDLE", age=40, dirty=0,
                              last="引き継ぎ完了です。本日の開発を終了します。"))
        assert j["category"] == CLOSEABLE
        assert j["close_ok"] is True

    def test_done_signals_variety(self):
        for msg in ["実装完了しました", "全てコミット済みです", "完成です。pushしました"]:
            j = judge_session(rec("IDLE", age=40, dirty=0, last=msg))
            assert j["category"] == CLOSEABLE, msg


class TestNeedsHandover:
    def test_context_full_is_top_priority(self):
        # 満杯なら完了宣言が無くても引き継ぎ要
        j = judge_session(rec("IDLE", age=5, context_full=True))
        assert j["category"] == NEEDS_HANDOVER
        assert j["needs_handover"] is True

    def test_done_but_dirty(self):
        j = judge_session(rec("IDLE", age=40, dirty=12,
                              last="実装完了しました"))
        assert j["category"] == NEEDS_HANDOVER

    def test_dirty_and_stale(self):
        j = judge_session(rec("IDLE", age=120, dirty=30, last=None))
        assert j["category"] == NEEDS_HANDOVER


class TestNeedsUser:
    def test_approval(self):
        assert judge_session(rec(state="AWAITING_APPROVAL"))["category"] == NEEDS_USER

    def test_question(self):
        assert judge_session(rec(state="AWAITING_QUESTION"))["category"] == NEEDS_USER

    def test_limit(self):
        assert judge_session(rec(state="LIMIT_REACHED"))["category"] == NEEDS_USER

    def test_running_stalled_is_user(self):
        j = judge_session(rec(state="RUNNING", stalled=True))
        assert j["category"] == NEEDS_USER

    def test_question_ending_not_closeable(self):
        """完了語があっても疑問で終わっていれば閉じない(返答待ち)。"""
        j = judge_session(rec("IDLE", age=40, dirty=0,
                              last="実装は完了しましたが、次はどうしますか?"))
        assert j["category"] != CLOSEABLE


class TestActiveResumable:
    def test_running(self):
        assert judge_session(rec(state="RUNNING"))["category"] == ACTIVE

    def test_recent_idle_untouched(self):
        # 直近まで動いていたIDLEは触らない
        assert judge_session(rec("IDLE", age=5, dirty=0))["category"] == ACTIVE

    def test_stale_idle_resumable(self):
        j = judge_session(rec("IDLE", age=90, dirty=0, last=None))
        assert j["category"] == RESUMABLE

    def test_stagnant_resumable(self):
        j = judge_session(rec("IDLE", age=10, dirty=0, stagnant=3))
        assert j["category"] == RESUMABLE


class TestSummarize:
    def test_summary_structure(self):
        snap = {"sessions": [
            rec(state="DEAD_SHELL"),
            rec("IDLE", age=40, dirty=0, last="完了しました"),
            rec("IDLE", age=5, context_full=True),
            rec(state="RUNNING"),
        ]}
        s = summarize(snap)
        assert len(s["closeable"]) == 2  # dead + done
        assert len(s["needs_handover"]) == 1  # context_full
        assert s["counts"][ACTIVE] == 1
        assert "閉じてOK" in s["headline"]
        # 各セッションにcleanup判定が付与されている
        assert all("cleanup" in x for x in s["sessions"])
