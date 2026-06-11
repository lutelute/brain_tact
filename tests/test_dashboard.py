"""ダッシュボードHTTPの保護(トークン・Host検査)とトークン埋め込みのテスト。

POST /api/act は無認証だとブラウザCSRF経由で任意ターミナルへテキスト注入
できてしまうため、X-Brain-Token 必須を回帰テストで固定する。
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from brain_tact import dashboard


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """テスト用トークンに差し替えた実サーバーを空きポートで起動する。"""
    monkeypatch.setattr(dashboard, "TOKEN_FILE", tmp_path / "token")
    srv = dashboard._ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _post(port: int, path: str, payload: dict, headers: dict | None = None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestPostProtection:
    def test_post_without_token_is_403(self, server):
        code, body = _post(server, "/api/act", {"tool": "act_send"})
        assert code == 403
        assert "X-Brain-Token" in body["error"]

    def test_post_with_wrong_token_is_403(self, server):
        code, _ = _post(server, "/api/act", {"tool": "act_send"},
                        {"X-Brain-Token": "wrong"})
        assert code == 403

    def test_post_with_token_reaches_handler(self, server):
        token = dashboard._get_token()
        code, body = _post(server, "/api/act", {"tool": "nonexistent"},
                           {"X-Brain-Token": token})
        assert code == 200
        assert "unknown tool" in body["error"]

    def test_bad_host_is_403(self, server):
        """DNS rebinding: Hostがlocalhost系でなければ拒否。"""
        token = dashboard._get_token()
        code, body = _post(server, "/api/act", {"tool": "act_send"},
                           {"X-Brain-Token": token, "Host": "evil.example"})
        assert code == 403
        assert body["error"] == "bad host"


class TestTokenEmbedding:
    def test_page_embeds_token(self, server):
        token = dashboard._get_token()
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server}/", timeout=10) as r:
            html = r.read().decode()
        assert f"const TOKEN='{token}'" in html
        assert "__BRAIN_TOKEN__" not in html

    def test_token_file_is_owner_only(self, server):
        dashboard._get_token()
        mode = dashboard.TOKEN_FILE.stat().st_mode & 0o777
        assert mode == 0o600


class TestMiniPage:
    def test_mini_embeds_token(self, server):
        token = dashboard._get_token()
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server}/mini", timeout=10) as r:
            html = r.read().decode()
        assert f"const TOKEN='{token}'" in html
        assert "__BRAIN_TOKEN__" not in html
        assert "/events" in html  # SSE購読(リアルタイム)
        assert "↻ UI" in html      # UI再読み込み(SSE再接続)

    def test_full_page_has_rescan(self, server):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{server}/", timeout=10) as r:
            html = r.read().decode()
        assert 'id="rescan"' in html  # フル版にも再スキャンボタン
