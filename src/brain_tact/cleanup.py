"""セッション判定エンジン — brainの頭脳(批判的改善ファースト)。

方針(ユーザー指示 2026-06-09): セッションは**閉じさせない**。完了報告を鵜呑みに
せず、批判的に粗・改善余地を見つけて自己改善ループを回し続けさせる。落ちたら復元する。

各セッションを active / needs_user / needs_handover(満杯) / closeable(=完了報告だが
改善余地あり=改善ループに戻す) / resumable(放置・要復元=ループ駆動) /
ignored(claude未起動=対象外) に分類する。
※ closeable は「閉じてOK」ではなく「完了と言っているが改善対象」の意味に転じた。

純関数。CLI・MCP・ダッシュボード・脳プロンプトの全入口から同じ判定を使う。
"""

import re

# 完了宣言の検出(last_assistant = Claudeの最後のテキスト発言から)
DONE_RE = re.compile(
    r"完了|完成|終了します|終わりました|引き継ぎ完了|お疲れ|done|finished|complete|"
    r"コミット(済|しました)|プッシュ(済|しました)|pushed|全て実装|すべて実装|"
    r"実装完了|対応完了|作業完了|まとめました|保存しました",
    re.IGNORECASE,
)
# 質問・指示待ちで終わっている(=ユーザーの返答待ち、勝手に閉じてはいけない)
QUESTION_RE = re.compile(
    r"でしょうか[?？]?$|ますか[?？]$|どちら|いずれ|教えてください|"
    r"お知らせください|ご確認ください|選んでください|どうしますか",
)

# 判定カテゴリ
CLOSEABLE = "closeable"          # 完了報告で停止(=批判的改善の最優先対象)
NEEDS_HANDOVER = "needs_handover"  # 満杯/未コミット — 保全してから改善継続
NEEDS_USER = "needs_user"        # ユーザー判断待ち(承認・質問・上限)
ACTIVE = "active"                # 稼働中、触らない
RESUMABLE = "resumable"          # 放置・claude死亡 — 復元/再開して改善ループへ
IGNORED = "ignored"              # claude未起動のただのシェル(対象外)

DIRTY_THRESHOLD = 5              # これ以上の未コミット変更は「成果あり」扱い
STALE_MIN = 30                   # これ以上放置されたIDLEを掃除検討対象に


def _has_done_signal(last_assistant: str | None) -> bool:
    if not last_assistant:
        return False
    # 質問で終わっているなら完了ではない(返答待ち)
    if QUESTION_RE.search(last_assistant):
        return False
    return bool(DONE_RE.search(last_assistant))


def judge_session(rec: dict) -> dict:
    """1セッションの掃除判定。

    Returns: {category, reason, action} のdict。
      action: 推奨する掃除アクション(human向け文 + 機械処理用ヒント)
    """
    state = rec.get("state_hint")
    signals = rec.get("signals") or {}
    git = rec.get("git") or {}
    last = rec.get("last_assistant")
    age = signals.get("jsonl_age_min")
    dirty = git.get("dirty")
    context_full = signals.get("context_full")
    progress = rec.get("progress") or {}
    stagnant = progress.get("stagnant_cycles", 0)

    # --- claude不在 -------------------------------------------------------
    if state == "DEAD_SHELL":
        return _j(RESUMABLE, "claudeが終了している(画面に痕跡のみ)",
                  "act_resume で復元し、改善ループに戻す")
    if state == "PLAIN_SHELL":
        return _j(IGNORED, "claudeを使っていないシェル",
                  "対象外(claude未起動)")

    # --- ユーザー判断が要る状態(掃除より先に判断) ------------------------
    if state in ("AWAITING_APPROVAL", "AWAITING_QUESTION"):
        return _j(NEEDS_USER, f"{state}: 入力を待っている",
                  "画面の選択肢に応答が必要")
    if state in ("LIMIT_REACHED", "ERROR_RETRYING"):
        return _j(NEEDS_USER, f"{state}: 自動回復待ち/上限",
                  "回復を待つか、別ブロックで再開")

    # --- 稼働中 -----------------------------------------------------------
    if state == "RUNNING":
        if signals.get("stalled"):
            return _j(NEEDS_USER, "RUNNING表示だが長時間jsonl更新なし(ハング疑い)",
                      "画面を確認。ESCで中断が必要かも")
        return _j(ACTIVE, "作業中", "触らない")

    # --- コンテキスト満杯(最優先の掃除対象) ------------------------------
    if context_full:
        return _j(NEEDS_HANDOVER, "コンテキストがほぼ満杯",
                  "引き継ぎ保存(/引き継ぎ)してから /clear で再開",
                  handover=True)

    # --- IDLE の掃除判定 --------------------------------------------------
    if state == "IDLE":
        done = _has_done_signal(last)
        has_work = isinstance(dirty, int) and dirty >= DIRTY_THRESHOLD

        if done and not has_work:
            # 完了宣言あり → 鵜呑みにせず批判的に粗を探させる(閉じない)
            return _j(CLOSEABLE,
                      "完了報告で止まっている",
                      "批判的にレビューし、粗・改善余地を1つ見つけて次の改善へ",
                      close_ok=True)
        if done and has_work:
            # 完了報告だが未コミット → コミットして改善継続
            return _j(NEEDS_HANDOVER,
                      f"完了報告だが未コミット{dirty}件",
                      "コミットで成果を保全し、批判的レビューで改善を継続",
                      handover=True)
        if has_work and (age or 0) >= STALE_MIN:
            # 未コミットを抱えて放置 → 成果喪失リスク
            return _j(NEEDS_HANDOVER,
                      f"未コミット{dirty}件を抱えて{age:.0f}分放置",
                      "成果が消える前にコミット/引き継ぎを", handover=True)
        if (age or 0) >= STALE_MIN or stagnant >= 2:
            # 残作業がありそうなのに止まっている → 再開候補
            return _j(RESUMABLE,
                      f"放置({age:.0f}分・停滞{stagnant}回)・残作業ありそう",
                      "進捗要約+続行を促す(攻めモード対象)")
        # 直近まで動いていた → ユーザー作業中かもしれない、触らない
        return _j(ACTIVE, "直近まで活動(ユーザー作業中かも)", "触らない")

    # UNKNOWN等
    return _j(RESUMABLE, f"{state}: 判定保留", "画面を確認")


def _j(category: str, reason: str, action: str,
       close_ok: bool = False, handover: bool = False) -> dict:
    return {
        "category": category,
        "reason": reason,
        "action": action,
        "close_ok": close_ok,        # ダッシュボード「🔬要改善」列に出す(完了報告のみ)
        "needs_handover": handover,   # 引き継ぎ保存を促す対象
    }


def summarize(snapshot: dict) -> dict:
    """スナップショット全体の掃除サマリ。各セッションにjudgmentを付与して返す。"""
    sessions = snapshot.get("sessions", [])
    judged = []
    counts: dict[str, int] = {}
    for rec in sessions:
        # scan時に付与済みならそれを使う(再判定せず一貫性を保つ)
        j = rec.get("cleanup") or judge_session(rec)
        counts[j["category"]] = counts.get(j["category"], 0) + 1
        judged.append(rec if "cleanup" in rec else {**rec, "cleanup": j})

    closeable = [s for s in judged if s["cleanup"]["close_ok"]]
    handover = [s for s in judged if s["cleanup"]["needs_handover"]]

    return {
        "counts": counts,
        "closeable": [_brief(s) for s in closeable],
        "needs_handover": [_brief(s) for s in handover],
        "sessions": judged,
        "headline": _headline(counts, len(closeable), len(handover)),
    }


def _brief(s: dict) -> dict:
    return {
        "tty": s["tty"],
        "project": s.get("project"),
        "reason": s["cleanup"]["reason"],
        "action": s["cleanup"]["action"],
    }


def _headline(counts: dict, n_close: int, n_handover: int) -> str:
    parts = []
    if n_close:
        parts.append(f"🔬 要改善 {n_close}件")
    if n_handover:
        parts.append(f"⚠️ 満杯 {n_handover}件")
    parts.append(f"▶ 稼働{counts.get(ACTIVE, 0)}")
    if counts.get(NEEDS_USER):
        parts.append(f"⏸ 要判断{counts[NEEDS_USER]}")
    return " / ".join(parts)
