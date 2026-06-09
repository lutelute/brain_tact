"""Terminal.appの全タブを1回のosascriptでアトミックに取得する。

罠(実機確認済み):
- `repeat with t in tabs of w` のループ変数に対する `contents of t` は参照の
  デリファレンスになり "tab 1 of window id 160" という文字列が返る。
  必ず明示インデックス `contents of tab ti of window wi` 形式を使う。
- ウィンドウindexはフォーカス順で変動するため、tty/title/busy/contentsは
  1回のosascript実行内でまとめて取る(複数回呼ぶとズレる)。
"""

import secrets
import subprocess
import time
from dataclasses import dataclass


@dataclass
class TabCapture:
    window_idx: int
    tab_idx: int
    tty: str          # /dev/ttys003 形式
    title: str
    busy: bool        # シェルが子プロセス実行中か(claude稼働タブはtrue)
    contents: str     # 可視画面の生テキスト


def _build_script(tab_sep: str, end_sep: str) -> str:
    # 文字列連結のO(n^2)を避けるためリストに集めて最後にjoinする。
    # 注意: tell "Terminal" 内では `tab` がタブ要素クラスに解決され
    # タブ文字定数として使えない → character id 9 を変数TABCで持つ。
    return f'''
    set chunks to {{}}
    set TABC to character id 9
    tell application "Terminal"
        set winCount to count of windows
        repeat with wi from 1 to winCount
            set tabCount to 0
            try
                set tabCount to count of tabs of window wi
            end try
            repeat with ti from 1 to tabCount
                try
                    set ttyVal to tty of tab ti of window wi
                    set busyVal to busy of tab ti of window wi
                    set titleVal to ""
                    try
                        set titleVal to custom title of tab ti of window wi
                    end try
                    set contentsVal to contents of tab ti of window wi
                    set end of chunks to "{tab_sep}" & TABC & wi & TABC & ti & TABC & ttyVal & TABC & busyVal & TABC & titleVal
                    set end of chunks to contentsVal
                    set end of chunks to "{end_sep}"
                end try
            end repeat
        end repeat
    end tell
    set AppleScript's text item delimiters to linefeed
    return chunks as text
    '''


def capture_all_tabs(timeout: float = 90.0, retries: int = 2) -> list[TabCapture]:
    """全タブの (window_idx, tab_idx, tty, title, busy, contents) を返す。

    区切りトークンはランダム化する — brain_tact自身を開発中の画面に
    区切り文字列リテラルが映り込んでも誤パースしないため。

    通常は1秒で返るが、スリープ復帰直後など Terminal.app が一時的に応答
    遅延するとタイムアウトする(実機: 朝7時のサイクルがこれでクラッシュ)。
    タイムアウト時は短い待機を挟んでリトライし、もろさを吸収する。
    """
    token = secrets.token_hex(8)
    tab_sep = f"@@@TAB-{token}"
    end_sep = f"@@@END-{token}"
    script = _build_script(tab_sep, end_sep)

    last_err = None
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                raise RuntimeError(f"osascript failed: {result.stderr.strip()[:500]}")
            return _parse(result.stdout, tab_sep, end_sep)
        except subprocess.TimeoutExpired as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(10)  # Terminal.appの一時的高負荷が収まるのを待つ
    raise RuntimeError(
        f"osascriptが{retries}回タイムアウト({timeout:.0f}s) — "
        f"Terminal.appが応答していない可能性"
    ) from last_err


def _parse(raw: str, tab_sep: str, end_sep: str) -> list[TabCapture]:
    captures: list[TabCapture] = []
    meta: list[str] | None = None
    lines: list[str] = []

    for line in raw.splitlines():
        if line.startswith(tab_sep):
            meta = line.split("\t")
            lines = []
        elif line.startswith(end_sep):
            if meta and len(meta) >= 5:
                captures.append(TabCapture(
                    window_idx=int(meta[1]),
                    tab_idx=int(meta[2]),
                    tty=meta[3].strip(),
                    # custom titleにタブ文字が含まれる場合に備えて残りを再結合
                    title="\t".join(meta[5:]).strip() if len(meta) > 5 else "",
                    busy=meta[4].strip().lower() == "true",
                    contents="\n".join(lines),
                ))
            meta = None
        elif meta is not None:
            lines.append(line)
    return captures
