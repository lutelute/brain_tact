"""claudeプロセスの cwd から ~/.claude/projects のセッションjsonlを対応付ける。

claudeはjsonlのfdを開きっぱなしにしない(lsof確認済み)ため確定対応は不可。
cwd → スラグ → 最新jsonl(mtime) の推定方式。同一cwdに複数プロセスが居る場合は
ambiguous=true を立て、mtimeは候補jsonl群のmaxを共有値として付与する。

jsonlのmtimeは「ツール結果のたびにappendされる」ため、画面のスピナー表示とは
独立した『実際に進捗しているか』のシグナルとして使える。
"""

import json
import re
import time
from dataclasses import dataclass

from . import CLAUDE_PROJECTS
from .procs import ClaudeProc

TAIL_READ_BYTES = 65536


def read_last_assistant_text(jsonl_path: str, max_chars: int = 240) -> str | None:
    """jsonl末尾からClaudeの最後のテキスト発言を抜粋する。

    画面で折りたたまれて見えない「直前に何を言っていたか」(完了報告・質問など)
    を脳に渡すため。tool_useだけの行はスキップしてテキストを遡る。
    """
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_READ_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = chunk.splitlines()
    if size > TAIL_READ_BYTES and lines:
        lines = lines[1:]  # 先頭行は途中から始まっている可能性があるため捨てる
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "assistant":
            continue
        content = (rec.get("message") or {}).get("content") or []
        texts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        text = " ".join(" ".join(t.split()) for t in texts if t.strip())
        if text:
            return text[:max_chars] + ("…" if len(text) > max_chars else "")
    return None


def read_context_tokens(jsonl_path: str) -> int | None:
    """jsonl末尾の最新assistant usageから、現在コンテキストに載っている総トークンを返す。

    総量 = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
    (output_tokensは含めない — 次ターンでinput/cacheに転写される)。満杯(context_full)に
    なる前にコンテキスト圧迫を数値で把握するための予兆シグナル。確定的な満杯判定は
    画面の context_full(new task?/clear) を引き続き使う(モデル上限がjsonlから判別できず
    =200k版か1M版か不明=絶対量だけでは満杯到達を断定できないため)。
    """
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - TAIL_READ_BYTES))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = chunk.splitlines()
    if size > TAIL_READ_BYTES and lines:
        lines = lines[1:]  # 先頭行は途中から始まっている可能性があるため捨てる
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "assistant":
            continue
        usage = (rec.get("message") or {}).get("usage") or {}
        if not usage:
            continue
        total = (usage.get("input_tokens", 0)
                 + usage.get("cache_creation_input_tokens", 0)
                 + usage.get("cache_read_input_tokens", 0))
        if total > 0:
            return total
    return None


@dataclass
class SessionInfo:
    jsonl_path: str | None
    session_id: str | None
    mtime: float | None
    age_min: float | None    # 最終活動からの経過分
    ambiguous: bool          # 同一cwdに複数claudeが居て対応が不確実
    context_tokens: int | None = None  # 現在コンテキストに載っている総トークン(満杯の予兆把握)


def path_slug(cwd: str) -> str:
    """cwd → projectsディレクトリ名。実測規則: 英数字以外は全て '-' になる
    (例: tool_dev_SGNB → tool-dev-SGNB)。"""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def attach_sessions(procs: dict[str, ClaudeProc]) -> dict[str, SessionInfo]:
    """tty -> SessionInfo。"""
    now = time.time()

    # cwdごとのプロセス数(同一cwd複数=ambiguous)
    cwd_count: dict[str, int] = {}
    for p in procs.values():
        if p.cwd:
            cwd_count[p.cwd] = cwd_count.get(p.cwd, 0) + 1

    out: dict[str, SessionInfo] = {}
    for tty, p in procs.items():
        if not p.cwd:
            out[tty] = SessionInfo(None, None, None, None, ambiguous=True)
            continue

        proj_dir = CLAUDE_PROJECTS / path_slug(p.cwd)
        jsonls = sorted(
            proj_dir.glob("*.jsonl"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        ) if proj_dir.is_dir() else []

        if not jsonls:
            out[tty] = SessionInfo(None, None, None, None, ambiguous=False)
            continue

        n_here = cwd_count[p.cwd]
        if n_here == 1:
            chosen = jsonls[0]
            mtime = chosen.stat().st_mtime
            out[tty] = SessionInfo(
                jsonl_path=str(chosen),
                session_id=chosen.stem,
                mtime=mtime,
                age_min=(now - mtime) / 60,
                ambiguous=False,
                context_tokens=read_context_tokens(str(chosen)),
            )
        else:
            # 複数プロセス共有cwd: 上位n_here本のmtime最大を共有シグナルとする
            mtimes = [f.stat().st_mtime for f in jsonls[:n_here]]
            mtime = max(mtimes)
            out[tty] = SessionInfo(
                jsonl_path=None,
                session_id=None,
                mtime=mtime,
                age_min=(now - mtime) / 60,
                ambiguous=True,
            )
    return out
