"""セッションの作業ディレクトリのgit文脈(branch・未コミット・最終コミット経過)。

「未コミット変更を大量に抱えたまま停止している」= 成果が失われるリスクの
高いセッションを脳が確実に検知できるようにする。
"""

import subprocess
import time
from pathlib import Path

GIT_TIMEOUT = 5


def _git(cwd: str, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def git_context(cwd: str) -> dict | None:
    """gitリポジトリなら {branch, dirty, last_commit_age_h, last_commit_unix} を返す。

    last_commit_unix(epoch秒)は介入効果のgit裏取り(verify)用 —
    「介入時より新しいコミットがあるか」を絶対時刻で比較する。
    """
    if not cwd or not (Path(cwd) / ".git").exists():
        return None

    branch = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(cwd, "status", "--porcelain")
    dirty = len(status.splitlines()) if status is not None else None
    last_ct = _git(cwd, "log", "-1", "--format=%ct")
    age_h = None
    last_unix = None
    if last_ct and last_ct.isdigit():
        last_unix = int(last_ct)
        age_h = round((time.time() - last_unix) / 3600, 1)

    if branch is None and dirty is None:
        return None  # gitはあるが読めない(壊れている等)
    return {"branch": branch, "dirty": dirty, "last_commit_age_h": age_h,
            "last_commit_unix": last_unix}


def collect_git_contexts(cwds: set[str]) -> dict[str, dict | None]:
    """複数cwdのgit文脈をまとめて取得(同一cwdの重複呼び出し回避)。"""
    return {cwd: git_context(cwd) for cwd in cwds if cwd}
