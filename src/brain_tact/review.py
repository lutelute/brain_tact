"""読書係 — usage余力があるとき、放置プロジェクトを読み直して提案を生成する。

ユーザー指示(2026-06-08):
「usageが50%未満であれば、何かしら自分のプロジェクトをGitHubからさらって
 提案したり読み直したりして私にホウレンソウするのです」

別のヘッドレスclaude(Read/Glob/Grep のみ・書き込み不可)にプロジェクトを
読ませ、現状要約+次の一手3案を生成。結果は脳のプロンプトに注入され、
LINEレポートの「💡提案」としてホウレンソウされる(push数は増やさない)。
"""

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from . import STATE_DIR, claude_bin

GITHUB_ROOT = Path.home() / "Documents" / "GitHub"
REVIEW_HISTORY = STATE_DIR / "review_history.json"
REVIEW_COOLDOWN_DAYS = 7     # 同じプロジェクトを再レビューするまでの間隔
REVIEWER_TIMEOUT = 300
REVIEWER_BUDGET_USD = "1"

REVIEWER_PROMPT = """このプロジェクトの現状を読み取って、以下を簡潔にまとめてください(全体で400字以内):

1. **概要**: 何のプロジェクトか(1行)
2. **現状**: 直近のコミット・TODO・READMEから見える状態(2行まで)
3. **放置されている課題**: 未完了・未コミット・壊れている箇所(あれば)
4. **次の一手(3案)**: 価値が高い順に各1行

調べ方: README・ROADMAP・TODO・git log(直近5件)・主要ソースの冒頭を読む程度で十分。
深追いせず、ユーザーが「再開するかどうか」を判断できる材料を返すこと。"""


def find_repos(root: Path = GITHUB_ROOT, depth: int = 2) -> list[Path]:
    """rootから2階層までの.git持ちディレクトリを列挙する。"""
    repos: list[Path] = []

    def walk(d: Path, lvl: int) -> None:
        if (d / ".git").exists():
            repos.append(d)
            return
        if lvl >= depth:
            return
        try:
            children = sorted(d.iterdir())
        except PermissionError:
            return
        for c in children:
            if c.is_dir() and not c.name.startswith("."):
                walk(c, lvl + 1)

    if root.is_dir():
        walk(root, 0)
    return repos


def _load_history() -> dict:
    if not REVIEW_HISTORY.exists():
        return {}
    try:
        return json.loads(REVIEW_HISTORY.read_text())
    except json.JSONDecodeError:
        return {}


def _save_history(history: dict) -> None:
    REVIEW_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1))


def pick_review_target(snapshot: dict) -> Path | None:
    """レビュー対象を選ぶ: セッションが開いておらず、最近レビューしておらず、
    最近まで触っていた(=関心が高い)プロジェクトを優先。"""
    open_cwds = {s.get("cwd") for s in snapshot.get("sessions", []) if s.get("cwd")}
    history = _load_history()
    cutoff = datetime.now().astimezone() - timedelta(days=REVIEW_COOLDOWN_DAYS)

    candidates: list[tuple[float, Path]] = []
    for repo in find_repos():
        if str(repo) in open_cwds:
            continue  # いまセッションが開いている=サボっていない
        last = history.get(str(repo))
        if last:
            try:
                if datetime.fromisoformat(last) > cutoff:
                    continue  # 最近レビュー済み
            except ValueError:
                pass
        try:
            # .git の mtime ≒ 最後にgit操作した頃(関心の代理指標)
            mtime = (repo / ".git").stat().st_mtime
        except OSError:
            continue
        candidates.append((mtime, repo))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def run_reviewer(project: Path) -> str | None:
    """読書係(ヘッドレスclaude、読み取り専用)を起動して報告テキストを返す。"""
    try:
        proc = subprocess.run(
            [
                claude_bin(), "-p",
                "--model", "haiku",
                "--dangerously-skip-permissions",
                "--strict-mcp-config",          # userスコープMCPを読まない
                "--tools", "Read,Glob,Grep",    # 読み取り専用サンドボックス
                "--max-budget-usd", REVIEWER_BUDGET_USD,
            ],
            input=REVIEWER_PROMPT,
            capture_output=True, text=True,
            timeout=REVIEWER_TIMEOUT, cwd=project,
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    history = _load_history()
    history[str(project)] = datetime.now().astimezone().isoformat(timespec="seconds")
    _save_history(history)
    return proc.stdout.strip()


def maybe_review(snapshot: dict) -> dict | None:
    """攻めモード条件を満たすときだけ読書係を走らせる。

    Returns: {"project": 名前, "path": パス, "report": テキスト} or None
    """
    usage = (snapshot.get("totals") or {}).get("usage")
    if not usage or usage.get("pct") is None or usage["pct"] >= 50:
        return None  # usage不明(安全側)or 余力なし
    target = pick_review_target(snapshot)
    if target is None:
        return None
    report = run_reviewer(target)
    if report is None:
        return None
    return {"project": target.name, "path": str(target), "report": report}
