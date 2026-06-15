"""doctor.precompact_block_enabled のテスト。

auto-compactブロック(PreCompact hook matcher=auto)の検出。ユーザーがsettings.jsonに
登録する任意設定で、brain_tactは状態の可視化のみ行う(登録は代行しない)。matcher=auto
の予防的自動圧縮だけがブロック対象で、manual(/compact手動)は止めない。
"""

from brain_tact.doctor import precompact_block_enabled


def _hook(matcher, cmds=("exit 2",)):
    return {"matcher": matcher,
            "hooks": [{"type": "command", "command": c} for c in cmds]}


class TestPrecompactBlockEnabled:
    def test_enabled_with_auto_matcher(self):
        s = {"hooks": {"PreCompact": [_hook("auto")]}}
        assert precompact_block_enabled(s) is True

    def test_enabled_when_auto_among_multiple(self):
        s = {"hooks": {"PreCompact": [_hook("manual"), _hook("auto")]}}
        assert precompact_block_enabled(s) is True

    def test_disabled_when_no_precompact(self):
        assert precompact_block_enabled({"hooks": {}}) is False
        assert precompact_block_enabled({}) is False

    def test_disabled_with_manual_matcher_only(self):
        """手動 /compact 用(matcher=manual)だけでは自動圧縮は止まらない。"""
        s = {"hooks": {"PreCompact": [_hook("manual")]}}
        assert precompact_block_enabled(s) is False

    def test_disabled_when_hooks_list_empty(self):
        """matcher=autoでもhooksが空なら無効扱い。"""
        s = {"hooks": {"PreCompact": [{"matcher": "auto", "hooks": []}]}}
        assert precompact_block_enabled(s) is False

    def test_handles_missing_hooks_key(self):
        assert precompact_block_enabled({"permissions": {}}) is False
