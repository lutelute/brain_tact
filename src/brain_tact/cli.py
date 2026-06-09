"""brain-tact CLI — scan / cycle / pending / log / install"""

import argparse
import json
import sys


def cmd_scan(args: argparse.Namespace) -> int:
    from .scan import run_scan
    snap = run_scan(quick=args.quick)
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=1))
    else:
        t = snap["totals"]
        print(f"📸 {snap['taken_at']}  タブ{t['tabs']} / claude {t['claude']}")
        for k, v in sorted(t["by_state"].items()):
            print(f"   {k}: {v}")
        for s in snap["sessions"]:
            mark = "⚠️ " if s["attention"] else "   "
            age = s["signals"].get("jsonl_age_min")
            age_s = f" age={age:.0f}m" if age is not None else ""
            print(f"{mark}{s['tty']}  {s['state_hint']:<18} {s['project'] or '-'}{age_s}")
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    from .cycle import run_cycle
    return run_cycle(force=args.force, dry_run=args.dry_run, model=args.model)


def cmd_pending(args: argparse.Namespace) -> int:
    from .state import load_pending, resolve_pending
    if args.action == "resolve":
        if not args.id:
            print("usage: brain-tact pending resolve <id> [--note NOTE]", file=sys.stderr)
            return 2
        ok = resolve_pending(args.id, args.note or "resolved via CLI")
        print("✅ resolved" if ok else f"❌ not found: {args.id}")
        return 0 if ok else 1
    # list(デフォルト)
    pending = load_pending()
    items = [i for i in pending.get("items", []) if i["status"] == "open"]
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
        return 0
    if not items:
        print("保留項目なし 🎉")
        return 0
    for i in items:
        print(f"[{i['id']}] {i['kind']} {i['project'] or i['tty']}: {i['summary']}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    from . import ACTIONS_LOG
    if not ACTIONS_LOG.exists():
        print("(アクション記録なし)")
        return 0
    lines = ACTIONS_LOG.read_text().splitlines()[-args.tail:]
    for ln in lines:
        try:
            r = json.loads(ln)
            print(f"{r['ts']}  {r['tool']:<12} {r.get('tty', '-'):<14} "
                  f"{r.get('result', '')}: {r.get('reason', '')[:60]}")
        except json.JSONDecodeError:
            print(ln)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .stats import compute_stats, format_stats
    s = compute_stats(days=args.days)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=1))
    else:
        print(format_stats(s))
    return 0


def cmd_cleanup(args: argparse.Namespace) -> int:
    import json as _json

    from . import LATEST_JSON
    from .cleanup import summarize
    from .scan import run_scan
    if args.scan or not LATEST_JSON.exists():
        snap = run_scan(quick=True)
    else:
        snap = _json.loads(LATEST_JSON.read_text())
    s = summarize(snap)
    if args.json:
        print(_json.dumps(s, ensure_ascii=False, indent=1))
        return 0
    print(f"🧠 {s['headline']}\n")
    if s["closeable"]:
        print("🔬 要改善(完了報告だが批判的に粗を探す):")
        for x in s["closeable"]:
            print(f"   {x['project'] or x['tty']:<18} {x['reason']}")
    if s["needs_handover"]:
        print("\n⚠️ 満杯(コミットで保全し改善継続):")
        for x in s["needs_handover"]:
            print(f"   {x['project'] or x['tty']:<18} {x['reason']}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .dashboard import serve
    serve(port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    import os
    os.environ.setdefault("BRAIN_CYCLE_ID", "cli-manual")
    from .actuator import send_impl
    print(send_impl(args.tty, args.message, args.reason or "CLI手動指示", manual=True))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    import os
    os.environ.setdefault("BRAIN_CYCLE_ID", "cli-manual")
    from .actuator import approve_impl
    print(approve_impl(args.tty, args.option, args.reason or "CLI手動承認", manual=True))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    import os
    os.environ.setdefault("BRAIN_CYCLE_ID", "cli-manual")
    from .actuator import resume_impl
    print(resume_impl(args.tty, args.reason or "CLI手動復元", manual=True))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import format_doctor, run_doctor
    checks = run_doctor()
    print(format_doctor(checks))
    return 0 if all(c["ok"] for c in checks) else 1


def cmd_install(args: argparse.Namespace) -> int:
    from .install import install_launchd, install_skill
    rc = 0
    if args.launchd or not args.skill:
        rc |= install_launchd(dry=args.dry_run)
    if args.skill or not args.launchd:
        rc |= install_skill(dry=args.dry_run)
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="brain-tact",
        description="Claude Codeセッション群の監督脳 — 定時スキャン・判断・介入・LINE報告",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("scan", help="全タブをスキャンして状態スナップショットを生成")
    sp.add_argument("--quick", action="store_true", help="history/に残さない(鮮度更新用)")
    sp.add_argument("--json", action="store_true", help="スナップショットJSONを出力")
    sp.set_defaults(func=cmd_scan)

    cp = sub.add_parser("cycle", help="定時サイクル実行(scan→脳→報告)")
    cp.add_argument("--force", action="store_true", help="デバウンスを無視して実行")
    cp.add_argument("--dry-run", action="store_true", help="脳は動くがアクション送信しない")
    cp.add_argument("--model", default="sonnet", help="脳のモデル(default: sonnet)")
    cp.set_defaults(func=cmd_cycle)

    pp = sub.add_parser("pending", help="保留項目の一覧・消し込み")
    pp.add_argument("action", nargs="?", default="list", choices=["list", "resolve"])
    pp.add_argument("id", nargs="?", help="resolve対象のID")
    pp.add_argument("--note", help="解決メモ")
    pp.add_argument("--json", action="store_true")
    pp.set_defaults(func=cmd_pending)

    lp = sub.add_parser("log", help="脳のアクション記録を表示")
    lp.add_argument("--tail", type=int, default=30)
    lp.set_defaults(func=cmd_log)

    cup = sub.add_parser("cleanup", help="セッション判定(要改善/満杯/稼働)を表示")
    cup.add_argument("--scan", action="store_true", help="先に再スキャンする")
    cup.add_argument("--json", action="store_true")
    cup.set_defaults(func=cmd_cleanup)

    snp = sub.add_parser("send", help="セッションに指示を送る(手動・制限なし)")
    snp.add_argument("tty", help="対象TTY(例: /dev/ttys006)")
    snp.add_argument("message", help="送るメッセージ")
    snp.add_argument("--reason", help="監査ログに残す理由")
    snp.set_defaults(func=cmd_send)

    apr = sub.add_parser("approve", help="承認プロンプトに番号を送る(手動)")
    apr.add_argument("tty")
    apr.add_argument("option", help="'1'〜'3' または ''(Enter)")
    apr.add_argument("--reason")
    apr.set_defaults(func=cmd_approve)

    rsm = sub.add_parser("resume", help="死んだタブで claude --continue を起動(手動)")
    rsm.add_argument("tty")
    rsm.add_argument("--reason")
    rsm.set_defaults(func=cmd_resume)

    svp = sub.add_parser("serve", help="ダッシュボードをlocalhostで起動")
    svp.add_argument("--port", type=int, default=8787)
    svp.add_argument("--no-browser", action="store_true", help="ブラウザを開かない")
    svp.set_defaults(func=cmd_serve)

    dp = sub.add_parser("doctor", help="環境・依存・権限の自己診断")
    dp.set_defaults(func=cmd_doctor)

    tp = sub.add_parser("stats", help="KPI集計(介入成功率・稼働率推移)")
    tp.add_argument("--days", type=float, default=7.0)
    tp.add_argument("--json", action="store_true")
    tp.set_defaults(func=cmd_stats)

    ip = sub.add_parser("install", help="launchd plist / /brainスキルのインストール")
    ip.add_argument("--launchd", action="store_true")
    ip.add_argument("--skill", action="store_true")
    ip.add_argument("--dry-run", action="store_true")
    ip.set_defaults(func=cmd_install)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
