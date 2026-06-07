# brain_tact 🧠

**Claude Codeセッション群の監督脳** — 20〜30個の放置されがちなClaude Codeウィンドウを、定時(朝7/昼12/夕17/夜22時)に自動巡回し、ヘッドレスClaudeが「継続/介入/保留」を判断して、LINEに報告する。

```
launchd (7/12/17/22時)
  └─ brain-tact cycle
       ├─ ① scan: AppleScript(全タブ画面) + ps/lsof(プロセス→cwd) + jsonl mtime
       ├─ ② 脳 = claude -p (sonnet・15分タイムアウト・MCP 2つのみ)
       │     ├─ brain-actuator: act_send / act_approve / act_resume / defer
       │     │   (クールダウン・回数上限・禁止語句をコードで強制)
       │     └─ line-bridge: send_text (1サイクル1push)
       └─ ③ pending.json更新 / actions.log監査記録
ユーザー: LINEで受信 → 手元のClaude Codeで /brain → 対話で保留を処理
```

## 判断ポリシー

| セッション状態 | 脳の対応 |
|---|---|
| RUNNING(スピナーあり) | 触らない |
| IDLE(最終活動<60分) | 触らない(ユーザー作業中の可能性) |
| IDLE(放置) | 「進捗要約+残作業の続行」を送信 |
| AWAITING_APPROVAL | 安全(読取/編集/ビルド/テスト/commit)なら自動承認、危険(rm -rf/push/sudo/課金)なら保留 |
| DEAD_SHELL(claude死亡) | `claude --continue` で自動復元 |
| ERROR_RETRYING | 自動回復を待つ(報告のみ) |
| LIMIT_REACHED | 保留(ユーザー判断) |
| 2回突いて進展なし | 3ストライク → 保留へ昇格 |

ガードレール(actuatorがコードで強制、プロンプト任せにしない):

- act_send: 同一tty **6時間に1回** / claude不在タブへの送信拒否(シェル誤爆防止) / 危険語句拒否
- act_approve: 選択肢番号のみ / 1セッション3回まで
- act_resume: claude稼働中タブには拒否 / **12時間に1回**
- 合計: **1サイクル15アクションまで** / kill・タブ閉じのツールは存在しない
- 全アクションが `state/actions.log` に自動記録(脳の自己申告に依存しない)

## セットアップ

```bash
cd /Users/shigenoburyuto/Documents/GitHub/tool_dev_SGNB/brain_tact
uv sync

# 動作確認
uv run brain-tact scan            # 全タブの状態分類を確認
uv run brain-tact cycle --force --dry-run   # 脳のドライラン(LINE送信なし)

# 本登録
uv run brain-tact install --launchd   # launchd登録(7/12/17/22時)
uv run brain-tact install --skill     # /brainスキルを ~/.claude/skills/ へ
```

## コマンド

| コマンド | 用途 |
|---|---|
| `brain-tact scan [--quick] [--json]` | 全タブスキャン+状態分類 |
| `brain-tact cycle [--force] [--dry-run] [--model X]` | 巡回サイクル実行 |
| `brain-tact pending [list\|resolve <id> --note N]` | 保留リスト操作 |
| `brain-tact log [--tail N]` | 脳のアクション監査ログ |
| `brain-tact install [--launchd] [--skill] [--dry-run]` | インストール |

## /brain スキル

手元のClaude Codeで `/brain` と打つと、保留項目の一覧 → 対話で指示出し → 消し込み、ができる。LINEレポートに「→ 手元のClaude Codeで /brain」と出たらこれ。

## 運用メモ

- **デバウンス**: 前回成功から3時間未満のサイクルはスキップ(Macスリープ起床時に溜まった発火が1回にまとまる)。手動実行は `--force`
- **スリープ中は発火しない**: launchdは起床時に1回まとめ実行する。蓋閉じ運用で朝7時を確実にしたいなら:
  `sudo pmset repeat wakeorpoweron MTWRFSU 06:58:00`(1日1回のみ設定可)
- **LINE枠**: 無料枠は月200push。4回/日=120push/月で、他用途と合算すると逼迫し得る。逼迫したら22時/7時の2回に減らす(plistの`StartCalendarInterval`を編集して `install --launchd` で再登録)
- **claude-watchdogとの棲み分け**: watchdog=30秒間隔のクラッシュ即時復活(常駐)、brain_tact=定時の状況判断・介入・報告。両方併用する
- **タイムアウト**: 脳は15分でSIGKILL。失敗時はLINEに障害一報(それも失敗したら `state/cycle.log` のみ)
- **state/** はgit管理外(スナップショット履歴は14日、保留は48時間で自動期限切れ)

## テスト

```bash
uv run pytest tests/ -q
```

実機画面のfixture(`tests/fixtures/screens/`)で状態分類を回帰テストする。Claude CodeのTUI表示が変わって分類がおかしくなったら、`brain-tact scan --json` で実画面を取って新fixtureを追加すること。
