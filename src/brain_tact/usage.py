"""Claude Code利用枠(usage)の計測 — ccusage blocks 連携。

サブスクの正確な上限はAPIから取れないため、ccusageの5時間ブロック集計を使い
「過去最大ブロックのトークン数」を実効上限の代理として利用率%を推計する。
取得失敗時はNoneを返し、呼び出し側は安全側(攻めモード発動なし)に倒す。
"""

import json
import subprocess

CCUSAGE_TIMEOUT = 90  # npx初回解決が遅いことがある


def current_usage() -> dict | None:
    """現在のアクティブブロックの利用状況を返す。

    Returns:
        {
          "pct": float | None,        # 過去最大ブロック比の消費率(0-100+)
          "tokens": int,              # 現ブロックの消費トークン
          "max_block_tokens": int,    # 過去最大ブロック(代理上限)
          "remaining_minutes": int | None,  # ブロックリセットまでの分
        }
        取得失敗時は None。
    """
    try:
        result = subprocess.run(
            ["npx", "-y", "ccusage", "blocks", "--json", "--offline"],
            capture_output=True, text=True, timeout=CCUSAGE_TIMEOUT,
        )
        if result.returncode != 0:
            # --offline非対応バージョンへのフォールバック
            result = subprocess.run(
                ["npx", "-y", "ccusage", "blocks", "--json"],
                capture_output=True, text=True, timeout=CCUSAGE_TIMEOUT,
            )
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError,
            json.JSONDecodeError, FileNotFoundError):
        return None

    blocks = data.get("blocks", [])
    if not blocks:
        return None

    # gap(空白期間)エントリを除いた実ブロックから過去最大を求める
    real = [b for b in blocks if not b.get("isGap") and b.get("totalTokens")]
    if not real:
        return None
    max_tokens = max(b["totalTokens"] for b in real)

    active = next((b for b in real if b.get("isActive")), None)
    if active is None:
        # アクティブブロックなし=この5時間枠は未使用
        return {"pct": 0.0, "tokens": 0, "max_block_tokens": max_tokens,
                "remaining_minutes": None}

    tokens = active.get("totalTokens", 0)
    pct = round(tokens / max_tokens * 100, 1) if max_tokens else None
    remaining = (active.get("projection") or {}).get("remainingMinutes")
    return {
        "pct": pct,
        "tokens": tokens,
        "max_block_tokens": max_tokens,
        "remaining_minutes": remaining,
    }
