"""actuatorのガードレール(送信拒否判定 forbidden_reason)のテスト。

ケースは実際の監査ログ(state/actions.log)の文面から採取:
- 拒否すべき: 2026-06-09に脳が大量送信した終了誘導(「閉じてOK」「締めてOK」等)
- 許可すべき: 06-12〜14の健全な改善指示(「コミットして締めてください」等)
誤爆して健全な指示まで弾かないことが重要。
"""

import pytest

from brain_tact.actuator import forbidden_reason


class TestDanger:
    """危険コマンドは manual でも常に拒否(シェル誤爆・破壊防止)。"""

    @pytest.mark.parametrize("msg", [
        "rm -rf / を実行してください",
        "sudo apt install foo",
        "git push --force origin main",
        "git push -f",
        "pkill -9 node",
        "shutdown -h now",
    ])
    def test_danger_rejected_always(self, msg):
        assert forbidden_reason(msg) is not None
        assert forbidden_reason(msg, manual=True) is not None  # 手動でも拒否


class TestCloseInduction:
    """セッション終了誘導は脳の自動送信(manual=False)では拒否する。

    プロンプトの「閉じさせない」だけでは2026-06-09に脳が破ったため、コードで強制。
    """

    @pytest.mark.parametrize("msg", [
        # --- 2026-06-09の実際の事故文面 ---
        "採点→改修→マージ→push まで完遂お疲れさまでした。閉じてOKです。",
        "NodeDash 95点版稼働お疲れさまでした。一区切りなら閉じてOKです。",
        "mcp_codex サーバーの構築お疲れさまでした。引き継ぎ済みなので締めてOKです。",
        "v1.8.0 コミット完了お疲れさまでした。引き継ぎを保存して締めてOKです。",
        # --- その他の終了誘導 ---
        "閉じてください",
        "閉じても大丈夫です",
        "もう閉じていいです",
        "セッションを終了してください",
        "セッションを締めてください",
        "作業を終えてOKです",
        "終わりにしてください",
    ])
    def test_close_rejected_for_brain(self, msg):
        assert forbidden_reason(msg, manual=False) is not None

    @pytest.mark.parametrize("msg", [
        "採点→push まで完遂お疲れさまでした。閉じてOKです。",
        "締めてOKです",
        "セッションを終了してください",
    ])
    def test_close_allowed_for_manual(self, msg):
        """ユーザー自身の手動操作(manual=True)なら終了誘導も許可(本人の判断)。"""
        assert forbidden_reason(msg, manual=True) is None


class TestWorkInstructionsAllowed:
    """作業の締め・健全なねぎらいは脳の自動送信でも通す(誤爆させない)。"""

    @pytest.mark.parametrize("msg", [
        # 「コミットして締める」= 作業の区切り。終了誘導ではない
        "実装→テスト→コミットまで自律で締めてください",
        "テスト・lint・実行確認を通し、論理単位でコミットして締めてください",
        "コミットまで締めてください",
        "実装→テスト→コミットまで一気通貫で進めてください",
        # ねぎらい+次の改善 = 健全
        "RAG評価139件の完走お疲れさまです。ただし未検証の評価指標を追加してください",
        # 通常の改善促進
        "進捗を3行で要約し、残作業が明確なら続行してください",
        "未コミットの変更を論理単位でコミットしてください",
        "次の最も価値の高い改善を1つ実行してコミットしてください",
        "プロジェクトを批判的に自己レビューし、最も価値の高い改善を実行してください",
    ])
    def test_work_allowed_for_brain(self, msg):
        assert forbidden_reason(msg, manual=False) is None
