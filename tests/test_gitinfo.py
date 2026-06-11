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


def test_commits_since(tmp_path):
    """介入時刻より後のコミットだけが新しい順で返る。"""
    import subprocess as sp
    import time as _time
    from brain_tact.gitinfo import commits_since

    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "before-intervention")
    # 介入時刻 = 1コミット目の直後
    out = sp.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%ct"],
                 capture_output=True, text=True)
    t_intervention = int(out.stdout.strip())
    _time.sleep(1.1)  # コミットtsは秒精度のため境界を跨ぐ
    (tmp_path / "a.txt").write_text("2")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "after-intervention-fix")

    commits = commits_since(str(tmp_path), t_intervention)
    assert len(commits) == 1
    assert "after-intervention-fix" in commits[0]
    assert "before-intervention" not in " ".join(commits)


def test_commits_since_non_repo(tmp_path):
    from brain_tact.gitinfo import commits_since
    assert commits_since(str(tmp_path / "nope"), 0) is None


def test_commits_since_truncates(tmp_path):
    """limit件・80字でtruncateされる(actions.log肥大防止)。"""
    import time as _time
    from brain_tact.gitinfo import commits_since
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("0")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _time.sleep(1.1)
    for i in range(7):
        (tmp_path / "a.txt").write_text(str(i + 1))
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "x" * 200)
    commits = commits_since(str(tmp_path), 0, limit=5)
    assert len(commits) == 5
    assert all(len(c) <= 80 for c in commits)
