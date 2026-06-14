"""sessions.read_context_tokens のテスト。

jsonlの最新assistant usageから「現在コンテキストに載っているトークン量」を算出する。
Claude Codeのjsonl出力形式(usageフィールド構造)に依存するため、形式変更で静かに
壊れないよう回帰テストで固定する。総量 = input + cache_creation + cache_read
(output_tokensは含めない)。
"""

import json

from brain_tact.sessions import read_context_tokens


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _assistant(usage):
    return {"type": "assistant", "message": {"role": "assistant", "usage": usage}}


class TestReadContextTokens:
    def test_sums_input_and_cache_not_output(self, tmp_path):
        """総量 = input + cache_creation + cache_read。output_tokensは加算しない。"""
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, [_assistant({
            "input_tokens": 2,
            "cache_creation_input_tokens": 500,
            "cache_read_input_tokens": 200000,
            "output_tokens": 9999,  # 含めない
        })])
        assert read_context_tokens(str(f)) == 200502

    def test_latest_assistant_wins(self, tmp_path):
        """複数のassistant行があれば最新(末尾に近い)のusageを採る。"""
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, [
            _assistant({"input_tokens": 1, "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 100}),
            _assistant({"input_tokens": 1, "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 5000}),
        ])
        assert read_context_tokens(str(f)) == 5001

    def test_skips_assistant_without_usage(self, tmp_path):
        """usageを持たない最新assistantは飛ばし、usageを持つ直前の行を採る。"""
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            _assistant({"input_tokens": 1, "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 300}),
            {"type": "assistant", "message": {"role": "assistant"}},  # usage無し
        ])
        assert read_context_tokens(str(f)) == 301

    def test_skips_non_assistant(self, tmp_path):
        """user/tool結果などassistant以外の行は無視する。"""
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, [
            {"type": "user", "message": {"role": "user", "content": "x"}},
            {"type": "system", "content": "boot"},
        ])
        assert read_context_tokens(str(f)) is None

    def test_skips_broken_json_lines(self, tmp_path):
        """壊れたJSON行が混ざっても、読める最新assistantを拾う。"""
        f = tmp_path / "s.jsonl"
        good = json.dumps(_assistant({"input_tokens": 2, "cache_creation_input_tokens": 0,
                                      "cache_read_input_tokens": 1000}))
        f.write_text('{"broken json no close\n' + good + "\n")
        assert read_context_tokens(str(f)) == 1002

    def test_missing_file_returns_none(self):
        assert read_context_tokens("/nonexistent/path/to.jsonl") is None

    def test_empty_usage_returns_none(self, tmp_path):
        """usageが空(全フィールド欠落)なら合計0 → Noneを返す。"""
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, [_assistant({})])
        assert read_context_tokens(str(f)) is None

    def test_missing_fields_default_zero(self, tmp_path):
        """一部フィールド欠落でも、存在するフィールドだけ合計する。"""
        f = tmp_path / "s.jsonl"
        _write_jsonl(f, [_assistant({"cache_read_input_tokens": 1500})])
        assert read_context_tokens(str(f)) == 1500
