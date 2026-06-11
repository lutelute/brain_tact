---
name: brain
description: "Claude Codeセッション群の監督脳(brain_tact) — 定時巡回の保留項目を対話処理し、任意セッションへ指示を送る。「保留」「巡回」「セッション整理」の文脈でも使う"
user_invocable: true
---

# /brain — セッション監督の対話インターフェース

brain_tact(定時巡回脳)が積んだ保留項目をユーザーと対話で処理し、必要なら任意のセッションに指示を送る。

## 前提パス

| 対象 | パス |
|---|---|
| プロジェクト | `/Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact` |
| 保留リスト | `<プロジェクト>/state/pending.json` |
| 最新スナップショット | `<プロジェクト>/state/latest.json` |
| アクション監査ログ | `<プロジェクト>/state/actions.log`(JSONL) |
| サイクルログ | `<プロジェクト>/state/cycle.log`(JSONL) |
| CLI | `uv run --directory <プロジェクト> brain-tact <cmd>` |

## ワークフロー

### Step 1: 状況把握

1. `state/pending.json` と `state/latest.json` を Read する
2. `latest.json` の `taken_at` が **1時間以上古い場合**は再スキャンして読み直す:
   ```bash
   uv run --directory /Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact brain-tact scan --quick
   ```
3. `actions.log` の末尾30行も読む(脳が直近何をしたか)

### Step 2: ダイジェスト提示

以下の順でユーザーに提示する:

1. **open保留項目**(`status == "open"`)を**優先度順**の番号付きで。優先度は
   kind で並べる: `approval`(承認待ち=即断可能) → `dead`(復元) → `limit` →
   `stalled` → `question` → `other`。同kind内は `created_at` が古い順
   - 各項目: `summary`、`project`、`kind`、経過時間、`screen_excerpt`(あれば抜粋)、`suggested_actions`
2. **全セッション表**: tty / project / cleanup.category / state_hint / jsonl_age_min / 直近アクション
3. 保留ゼロなら「保留なし」+ セッション表だけ提示

### Step 2.5: 横断照会・一括指示(ユーザーの聞き方に応じて)

- **「<プロジェクト>の状況は?」**(例:「marginaliaどうなってる」): `latest.json` の
  `sessions[]` から `project` 部分一致で探し、state_hint / cleanup / git(dirty・最終コミット) /
  last_assistant / screen_tail 要約を1枚で提示。`actions.log` から該当ttyへの直近介入と
  verify結果(git_progress含む)も添える
- **「全部に〜して」「IDLEのやつ全部に指示」**(一括指示): 対象セッションを列挙して
  ユーザーに確認 → 承認後、各ttyに `brain-tact send` を順に実行(RUNNINGは除外。
  手動操作なのでクールダウンなし)。実行結果を表で報告
- **「品質どう?」「効果出てる?」**: `brain-tact stats --days 7` を実行し、
  品質スコア(実コミット/動いただけ/不発)と代表コミットを提示

### Step 3: 指示実行

ユーザーの指示(「1番は承認」「3番に〇〇と指示」「ttys005は再開して」等)を実行する:

- **ToolSearch で claude-watchdog ツールをロード**して使う(このセッションのuserスコープMCP):
  - メッセージ送信: `mcp__claude-watchdog__send_to_session(tty, message)`
  - 承認(選択肢番号): 同じく `send_to_session(tty, "1")` のように番号だけ送る
  - 死んだタブの復元: `mcp__claude-watchdog__resume_session(tty)`
  - 強制再起動: `mcp__claude-watchdog__restart_session(tty)`
- 送信前に `latest.json` の該当セッションの `state_hint` を確認:
  - **RUNNING のセッションへの送信はユーザーに一言確認**(実行中の作業を乱す可能性)
  - 破壊的な指示(rm・push・kill等を含む)はユーザーの明示文言があるときのみ

### Step 4: 消し込みと再提示

処理した項目を resolve する:

```bash
uv run --directory /Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact brain-tact pending resolve <id> --note "ユーザー指示で承認した"
```

残りのopen項目を再提示し、全部処理されたら「完了」を報告する。

## 補助コマンド

| 用途 | コマンド |
|---|---|
| 保留一覧 | `brain-tact pending` |
| 脳のアクション履歴 | `brain-tact log --tail 30` |
| 手動で巡回を回す | `brain-tact cycle --force`(LINEに1push飛ぶ点に注意) |
| 巡回のドライラン | `brain-tact cycle --force --dry-run`(LINE送信なし) |

## 注意

- 保留項目の `suggested_actions` は脳の提案にすぎない。ユーザーの指示を優先する
- pending.json を直接編集しない(CLI経由で resolve する)
- LINE報告は月200push枠を消費するため、手動サイクルの乱発は避ける
