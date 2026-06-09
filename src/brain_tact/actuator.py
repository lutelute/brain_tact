"""brain-actuator MCPサーバー — 脳(claude -p)に渡す唯一の操作系ツール。

ガードレールはプロンプトのお願いではなく、ここでコードとして強制する:
- act_send: 対象ttyにclaudeが居ることを確認(シェルへのコマンド誤爆防止)、
  同一tty 6時間1回、禁止語句拒否、1サイクル合計15アクション
- act_approve: 選択肢番号のみ、1セッション3回/サイクル
- act_resume: claudeが居ないことを確認してから復元コマンド送信、12時間1回
- kill・タブ閉じに相当するツールは存在しない(構造的に不可能)

環境変数(cycle.pyがclaude -p起動時に設定し、子プロセスの本サーバーに伝播):
- BRAIN_CYCLE_ID: 現在のサイクルID(無ければ "manual")
- BRAIN_DRY_RUN=1: 記録だけして実送信しない(P3検証用)
"""

import json
import os
import re
import subprocess

from fastmcp import FastMCP

from . import CLAUDE_RESUME_CMD, LATEST_JSON
from .procs import find_claude_processes
from .state import add_pending, check_limits, log_action, load_pending
from .state import resolve_pending as _resolve

mcp = FastMCP("brain-actuator")

CYCLE_ID = os.environ.get("BRAIN_CYCLE_ID", "manual")
DRY_RUN = os.environ.get("BRAIN_DRY_RUN", "") == "1"

# 脳がセッションに送るメッセージに含まれていたら拒否する語句
FORBIDDEN_RE = re.compile(
    r"rm\s+-rf|sudo\s|--force|force[- ]push|git\s+push\s+-f|kill\s|pkill|"
    r"shutdown|reboot|mkfs|dd\s+if=|>\s*/dev/",
    re.IGNORECASE,
)

VALID_KINDS = {"approval", "question", "stalled", "dead", "limit", "other"}


def _send_to_tab(tty: str, command: str) -> bool:
    """do script でタブにテキストを送り、Enterまで確実に押す。

    実機で確認したバグ: do script の改行はClaude TUI(Ink)でペースト扱いに
    なり「送信」されず入力欄に溜まる。テキスト投入後に少し待ってから
    空の do script(改行のみ)を追い打ちしてEnterを成立させる。
    """
    safe = command.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                try
                    if (tty of t) = "{tty}" then
                        do script "{safe}" in t
                        delay 0.5
                        do script "" in t
                        return true
                    end if
                end try
            end repeat
        end repeat
    end tell
    return false
    '''
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=20,
    )
    return result.stdout.strip().lower() == "true"


def _record(tool: str, tty: str, payload: dict, reason: str, result: str) -> None:
    log_action({
        "cycle_id": CYCLE_ID,
        "tool": tool,
        "tty": tty,
        "payload": payload,
        "reason": reason,
        "result": result,
        "dry_run": DRY_RUN,
    })


def _guarded_send(tool: str, tty: str, text: str, reason: str,
                  require_claude: bool, manual: bool = False) -> str:
    """共通ガード: 制限チェック → claude在席チェック → 送信 → 記録。

    manual=True(ダッシュボード/CLIからの人間操作)はクールダウン・回数制限を
    スキップする。脳の暴走防止のための制限であり、ユーザー直接の指示には不要。
    禁止語句チェック・claude在席チェック(安全性)は manual でも維持する。
    """
    if not manual:
        ok, why = check_limits(tty, tool, CYCLE_ID)
        if not ok:
            _record(tool, tty, {"text": text}, reason, f"rejected: {why}")
            return f"❌ 拒否: {why}"

    procs = find_claude_processes()
    has_claude = tty in procs
    if require_claude and not has_claude:
        _record(tool, tty, {"text": text}, reason, "rejected: no claude on tty")
        return (f"❌ 拒否: {tty} にclaudeプロセスが居ません。"
                f"シェルへの誤送信を防ぐため送信しません。死んだタブなら act_resume を使うこと")
    if not require_claude and has_claude:
        _record(tool, tty, {"text": text}, reason, "rejected: claude already running")
        return f"❌ 拒否: {tty} ではclaudeが稼働中です。act_resume は不要です"

    if DRY_RUN:
        _record(tool, tty, {"text": text}, reason, "sent")
        return f"🧪 DRY-RUN: {tty} への送信を記録しました(実送信なし)"

    sent = _send_to_tab(tty, text)
    _record(tool, tty, {"text": text}, reason, "sent" if sent else "failed: tab not found")
    if sent:
        return f"✅ {tty} に送信しました"
    return f"❌ {tty} のタブが見つかりません(閉じられた可能性)"


# ---------------------------------------------------------------------------
# ツール定義
# ---------------------------------------------------------------------------

@mcp.tool()
def get_snapshot() -> str:
    """最新スキャンのスナップショットJSON(全セッションの状態)を返す。"""
    if not LATEST_JSON.exists():
        return "スナップショットがありません。scan_now で取得できます。"
    return LATEST_JSON.read_text()


@mcp.tool()
def scan_now() -> str:
    """いま全Terminal.appタブをスキャンし、状態+掃除判定のサマリを返す。

    「どこからでもbrain」の入口。Claude Codeや他アプリからこれを呼べば、
    全セッションの今の状態(稼働/放置/閉じてOK/要引き継ぎ)が一覧で得られる。
    """
    from .scan import run_scan
    snap = run_scan(quick=True)
    return _state_summary(snap)


@mcp.tool()
def get_cleanup() -> str:
    """最新スナップショットの掃除判定(閉じてOK/要引き継ぎ/要判断)を返す。

    「どのウィンドウを片付けられるか」を知りたいときに使う。
    """
    if not LATEST_JSON.exists():
        return "スナップショットがありません。scan_now を先に実行してください。"
    snap = json.loads(LATEST_JSON.read_text())
    return _state_summary(snap)


def _state_summary(snap: dict) -> str:
    """スナップショット → 掃除判定込みのJSON文字列。"""
    from .cleanup import summarize
    cl = summarize(snap)
    out = {
        "taken_at": snap.get("taken_at"),
        "totals": snap.get("totals"),
        "headline": cl["headline"],
        "closeable": cl["closeable"],
        "needs_handover": cl["needs_handover"],
        "sessions": [
            {
                "tty": s["tty"], "project": s.get("project"),
                "state_hint": s["state_hint"],
                "category": s["cleanup"]["category"],
                "reason": s["cleanup"]["reason"],
                "action": s["cleanup"]["action"],
                "git": s.get("git"),
                "last_assistant": s.get("last_assistant"),
            }
            for s in cl["sessions"]
        ],
    }
    return json.dumps(out, ensure_ascii=False, indent=1)


@mcp.tool()
def run_cycle_now(dry_run: bool = True) -> str:
    """定時巡回サイクルを今すぐ1回実行する(脳が判断・介入・報告)。

    Args:
        dry_run: Trueなら判断のみで実介入・LINE送信しない(デフォルト安全側)
    """
    from .cycle import run_cycle
    rc = run_cycle(force=True, dry_run=dry_run)
    return f"巡回完了 (rc={rc}, dry_run={dry_run})。詳細は get_cleanup / brain-tact log で確認。"


# --- 実装本体(manualフラグで人間操作/脳操作を分岐) ----------------------
# manual=True: ダッシュボード/CLIからの人間操作 → クールダウン・回数制限なし
# manual=False: 脳(cycle)の自動操作 → 全ガードレール適用

def send_impl(tty: str, message: str, reason: str, manual: bool = False) -> str:
    message = " ".join(message.split())  # 改行・連続空白を畳む
    if FORBIDDEN_RE.search(message):
        _record("act_send", tty, {"text": message}, reason, "rejected: forbidden phrase")
        return "❌ 拒否: メッセージに危険語句が含まれています。defer してユーザーに委ねること"
    if len(message) > 500:
        _record("act_send", tty, {"text": message[:100]}, reason, "rejected: too long")
        return "❌ 拒否: メッセージが長すぎます(500文字まで)"
    return _guarded_send("act_send", tty, message, reason,
                         require_claude=True, manual=manual)


def approve_impl(tty: str, option: str, reason: str, manual: bool = False) -> str:
    if option not in ("", "1", "2", "3"):
        return "❌ 拒否: option は '1'〜'3' または ''(空=Enter)のみ"
    return _guarded_send("act_approve", tty, option, reason,
                         require_claude=True, manual=manual)


def resume_impl(tty: str, reason: str, manual: bool = False) -> str:
    return _guarded_send("act_resume", tty, CLAUDE_RESUME_CMD, reason,
                         require_claude=False, manual=manual)


@mcp.tool()
def act_send(tty: str, message: str, reason: str) -> str:
    """指定ttyのClaudeセッションにメッセージを送信する(送信は6時間に1回まで)。

    対象にclaudeが居ない場合は拒否される。危険語句を含むメッセージも拒否される。

    Args:
        tty: 対象TTY(例: /dev/ttys003)
        message: 送るテキスト(改行はスペースに変換される)
        reason: なぜ送るのか(監査ログに残る)
    """
    return send_impl(tty, message, reason, manual=False)


@mcp.tool()
def act_approve(tty: str, option: str, reason: str) -> str:
    """承認プロンプトに選択肢番号を送る(1セッション3回/サイクルまで)。

    Args:
        tty: 対象TTY
        option: "1"〜"3"、または ""(Enterのみ=デフォルト選択)
        reason: 何をなぜ承認するのか(監査ログに残る)
    """
    return approve_impl(tty, option, reason, manual=False)


@mcp.tool()
def act_resume(tty: str, reason: str) -> str:
    """claudeが死んでいるタブで claude --continue を起動して復元する(12時間に1回まで)。

    対象にclaudeが既に居る場合は拒否される。

    Args:
        tty: 対象TTY
        reason: 復元する理由(監査ログに残る)
    """
    return resume_impl(tty, reason, manual=False)


@mcp.tool()
def defer(tty: str, kind: str, summary: str,
          suggested_actions: list[dict] | None = None,
          project: str | None = None,
          screen_excerpt: list[str] | None = None) -> str:
    """ユーザー判断が必要な項目を保留リスト(pending.json)に積む。

    破壊的操作の承認・判断がつかない停滞・3ストライク到達などはこれを使う。

    Args:
        tty: 対象TTY
        kind: approval / question / stalled / dead / limit / other
        summary: ユーザーに見せる一行サマリ(何が起きていて何を判断してほしいか)
        suggested_actions: 推奨アクション(例: [{"label": "承認する", "tool": "act_approve", "args": {...}}])
        project: プロジェクト名
        screen_excerpt: 画面の関連部分の抜粋(10行程度)
    """
    if kind not in VALID_KINDS:
        return f"❌ kind は {sorted(VALID_KINDS)} のいずれか"
    item_id = add_pending(
        tty=tty, kind=kind, summary=summary, cycle_id=CYCLE_ID,
        project=project, screen_excerpt=screen_excerpt,
        suggested_actions=suggested_actions,
    )
    _record("defer", tty, {"kind": kind, "summary": summary}, summary, "deferred")
    return f"📌 保留リストに追加しました: {item_id}"


@mcp.tool()
def get_pending() -> str:
    """保留リスト(open項目)をJSONで返す。前サイクルからの持ち越し確認に使う。"""
    pending = load_pending()
    items = [i for i in pending.get("items", []) if i["status"] == "open"]
    return json.dumps(items, ensure_ascii=False, indent=1)


@mcp.tool()
def resolve_pending(item_id: str, resolution: str) -> str:
    """保留項目を解決済みにする(状況が変わって不要になった場合など)。

    Args:
        item_id: 保留項目のID
        resolution: どう解決したか
    """
    ok = _resolve(item_id, resolution)
    _record("resolve_pending", "-", {"id": item_id}, resolution,
            "resolved" if ok else "not found")
    return "✅ 解決済みにしました" if ok else f"❌ open状態の {item_id} が見つかりません"


def run() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
