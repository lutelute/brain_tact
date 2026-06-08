"""画面テキスト+プロセス情報 → 状態ヒントの分類(純関数、fixtureテスト対象)。

実機確認済みの画面シグナル(claude 2.1.x TUI):
- `❯` 入力ボックスは実行中でも常時表示される → idle判定には使えない
- 実行中の決定的シグナル: スピナー行 `✶ テストと実機確認中… (25m 53s · ↑ 48.9k tokens)`
  (スピナー文字は ✶ ✳ ✻ ✽ ✢ · 等を巡回)、および `esc to interrupt`
- idle側の強シグナル: recapブロック `(disable recaps in /config)`
- 承認: `Do you want`/`Would you like to proceed` + 番号選択肢 `❯ 1.`
- APIリトライ: `⎿ Retrying in 0s · attempt 1/10`
- ステータスバー: `⏵⏵ bypass permissions on` / `⏵⏵ don't ask on` / `⏸ plan mode on`

state_hint はあくまでPython推定。脳には screen_tail の生テキストも渡し、
矛盾時は生テキストを優先させる。
"""

import re
from dataclasses import dataclass, field

from .procs import ClaudeProc
from .sessions import SessionInfo

# --- 画面パターン(上が強いシグナル) ---------------------------------------

# スピナー行: 行頭スピナー文字 + 短い動詞句 + … + ( 経過/トークン )
SPINNER_RE = re.compile(r"^[✶✳✻✽✢·✛✦✧+*]\s+\S.{0,80}…+\s*\(")
# 経過時間+トークンカウンタ(スピナー文字が変わっても効く保険)
ELAPSED_TOKENS_RE = re.compile(
    r"\(\s*(?:(\d+)\s*h\s+)?(?:(\d+)\s*m\s+)?(\d+)\s*s\s*·.*tokens"
)
ESC_INTERRUPT = "esc to interrupt"
STILL_THINKING_RE = re.compile(r"still thinking|max effort", re.I)

# 折り返しで "(disable\nrecaps in /config)" に分断されることがあるため後半のみで判定
RECAP_MARK = "recaps in /config"

APPROVAL_RE = re.compile(
    r"Do you want|Would you like to proceed|Proceed anyway|Allow this", re.I
)
# 選択肢行はボックス枠 `│ ❯ 1. Yes` の形で出ることがある
OPTION_LINE_RE = re.compile(r"^\s*[│|]?\s*(?:❯\s*)?\d\.\s+\S")

RETRY_RE = re.compile(
    r"Retrying in \d+\s*s|attempt \d+/\d+|API Error|Connection error|overloaded", re.I
)
LIMIT_RE = re.compile(
    r"usage limit|rate limit|resets at \d|out of extra usage|limit reached", re.I
)

PROMPT_BOX_RE = re.compile(r"^\s*❯")

# ステータスバー
BYPASS_MARK = "bypass permissions"
DONT_ASK_MARK = "don't ask"
PLAN_MODE_MARK = "plan mode on"
SUBAGENT_RE = re.compile(r"^\s*[◯⏺]\s+\S")

# claude UIの痕跡(プロセスは死んだが画面にUIが残っているケースの判定用)
UI_TRACE_RE = re.compile(
    r"tokens|esc to interrupt|/config|⏵⏵|bypass permissions|Welcome to Claude"
)

# コンテキストがほぼ満杯のサイン(「new task? /clear to save 289.1k tokens」)
CONTEXT_FULL_RE = re.compile(r"new task\?\s*/clear to save")


@dataclass
class Classified:
    state_hint: str             # RUNNING / IDLE / AWAITING_APPROVAL / ...
    signals: dict = field(default_factory=dict)
    attention: bool = False     # 脳が注視すべき(画面を長めに渡す)


def _tail_nonempty(screen: str, n: int) -> list[str]:
    lines = [ln.rstrip() for ln in screen.splitlines()]
    return [ln for ln in lines if ln.strip()][-n:]


def _permission_mode(text: str) -> str:
    if PLAN_MODE_MARK in text:
        return "plan"
    if DONT_ASK_MARK in text:
        return "dont_ask"
    if BYPASS_MARK in text:
        return "bypass"
    return "normal"


def _turn_elapsed_min(text: str) -> float | None:
    m = ELAPSED_TOKENS_RE.search(text)
    if not m:
        return None
    h = int(m.group(1) or 0)
    mins = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 60 + mins + s / 60


def classify(
    screen: str,
    proc: ClaudeProc | None,
    session: SessionInfo | None,
    prev_state: str | None,
) -> Classified:
    """末尾40行(空行除去後)を対象に状態ヒントを返す。"""
    tail = _tail_nonempty(screen, 40)
    text = "\n".join(tail)
    # 承認ボックス・スピナーは画面最下部に出る — 古い表示の残骸を拾わないよう
    # 「直近シグナル」は末尾20行で判定する
    near = "\n".join(tail[-20:])

    signals: dict = {
        "permission_mode": _permission_mode(text),
        "has_subagents": bool(SUBAGENT_RE.search(text)),
        # コンテキスト満杯のセッションは新しい仕事を振れない(攻めモード対象外)
        "context_full": bool(CONTEXT_FULL_RE.search(text)),
    }
    if proc is not None:
        signals["cpu_pct"] = proc.cpu_pct
        signals["proc_etime_min"] = round(proc.etime_min, 1)
    if session is not None and session.age_min is not None:
        signals["jsonl_age_min"] = round(session.age_min, 1)
        signals["ambiguous_session"] = session.ambiguous

    # --- claudeプロセスが居ない -------------------------------------------
    if proc is None:
        had_claude = (
            prev_state not in (None, "DEAD_SHELL", "PLAIN_SHELL")
            or bool(UI_TRACE_RE.search(text))
        )
        state = "DEAD_SHELL" if had_claude else "PLAIN_SHELL"
        return Classified(state, signals, attention=(state == "DEAD_SHELL"))

    # --- claudeプロセスあり: 画面シグナルで分類(優先順) -------------------
    if LIMIT_RE.search(near):
        return Classified("LIMIT_REACHED", signals, attention=True)

    if RETRY_RE.search(near):
        return Classified("ERROR_RETRYING", signals, attention=True)

    has_options = sum(1 for ln in tail[-15:] if OPTION_LINE_RE.match(ln)) >= 2
    if APPROVAL_RE.search(near) and has_options:
        return Classified("AWAITING_APPROVAL", signals, attention=True)

    running = (
        any(SPINNER_RE.match(ln) for ln in tail[-15:])
        or ESC_INTERRUPT in near
        or bool(ELAPSED_TOKENS_RE.search(near))
    )
    if running:
        elapsed = _turn_elapsed_min(near)
        if elapsed is not None:
            signals["turn_elapsed_min"] = round(elapsed, 1)
        # 画面は実行中なのにjsonlが30分以上更新なし & CPUほぼゼロ → ハング疑い
        age = signals.get("jsonl_age_min")
        if age is not None and age > 30 and proc.cpu_pct < 0.5:
            signals["stalled"] = True
            return Classified("RUNNING", signals, attention=True)
        return Classified("RUNNING", signals, attention=False)

    # スピナーが無いのに選択肢だけ出ている → AskUserQuestion型の質問待ち
    if has_options:
        return Classified("AWAITING_QUESTION", signals, attention=True)

    if any(PROMPT_BOX_RE.match(ln) for ln in tail[-20:]):
        signals["has_recap"] = RECAP_MARK in text
        return Classified("IDLE", signals, attention=True)

    return Classified("UNKNOWN", signals, attention=True)
