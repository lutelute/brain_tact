"""gitinfo(セッションのgit文脈)のテスト — 実repoをtmpに作って検証。"""

import subprocess

from brain_tact.gitinfo import git_context


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                   check=True,
                   env={"PATH": "/usr/bin:/bin",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "HOME": str(cwd)})


def test_non_repo_returns_none(tmp_path):
    assert git_context(str(tmp_path)) is None


def test_repo_context(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("x")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-q", "-m", "first")
    (tmp_path / "b.txt").write_text("y")  # dirty 1件

    g = git_context(str(tmp_path))
    assert g["dirty"] == 1
    assert isinstance(g["last_commit_unix"], int)
    assert g["last_commit_age_h"] is not None and g["last_commit_age_h"] < 1
